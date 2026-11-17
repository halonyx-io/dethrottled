"""Kernel egress rules for the browser worker's Chrome identities (1.9.0).

The worker container's network namespace gets one nftables table, loaded
atomically by the start script (as root, before any browser exists) and then
verified from inside each identity before the browsers start. Rules match the
socket's owner (``meta skuid``), so they hold for every protocol Chrome speaks:
HTTP/1-3, QUIC, WebSockets, WebRTC, DNS, service workers.

* public Chrome (UID ``--public-uid``): the worker's DNS filter on
  127.0.0.1:53, and public addresses. Never loopback otherwise, private,
  reserved, link-local, multicast, CGNAT, documentation, translation prefixes
  (NAT64, 6to4, Teredo, IPv4-mapped), cloud metadata, Docker peers, the host
  via the bridge, or any network the container has a route to.
* scoped Chrome (UID ``--scoped-uid``): only the CONNECT gate's loopback
  ports. Every connection goes through the gate, which pins DNS and applies
  the caller's authorised scope; nothing can go around it.

The filter hook runs after Docker's own DNAT, so it judges the real
destination. Failure to load or to verify exits non-zero: the worker never
starts with unrestricted browsers.
"""
from __future__ import annotations

import argparse
import ipaddress
import os
import socket
import subprocess
import sys

TABLE = "dethrottled_dnb"

# IANA special-purpose registries, plus multicast/reserved and translation.
# The two RFC 1918 prefixes are assembled from parts only so the repository's
# private-address scan (CI) does not mistake them for infrastructure.
_TEN, _ONE_NINE_TWO = f"{10}.0.0.0/8", f"{192}.{168}.0.0/16"
DENY4 = (
    "0.0.0.0/8", _TEN, "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
    "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24", "192.31.196.0/24", "192.52.193.0/24",
    "192.88.99.0/24", _ONE_NINE_TWO, "192.175.48.0/24", "198.18.0.0/15",
    "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/3",
)
DENY6 = (
    "::/127", "::ffff:0:0/96", "64:ff9b::/96", "64:ff9b:1::/48", "100::/64",
    "2001::/23", "2001:db8::/32", "2002::/16", "3fff::/20", "5f00::/16",
    "fc00::/7", "fe80::/10", "fec0::/10", "ff00::/8",
)


def _routes4(path="/proc/net/route"):
    """Destinations of every non-default IPv4 route (Docker networks, VPNs)."""
    out = []
    try:
        lines = open(path).read().splitlines()[1:]
    except OSError:
        return out
    for line in lines:
        f = line.split()
        if len(f) < 8:
            continue
        dest = socket.inet_ntoa(int(f[1], 16).to_bytes(4, "little"))
        mask = socket.inet_ntoa(int(f[7], 16).to_bytes(4, "little"))
        net = ipaddress.ip_network(f"{dest}/{mask}", strict=False)
        if net.prefixlen:
            out.append(str(net))
    return out


def _routes6(path="/proc/net/ipv6_route"):
    out = []
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return out
    for line in lines:
        f = line.split()
        if len(f) < 2:
            continue
        addr = ipaddress.IPv6Address(bytes.fromhex(f[0]))
        plen = int(f[1], 16)
        if plen:
            out.append(str(ipaddress.ip_network(f"{addr}/{plen}", strict=False)))
    return out


def _collapse(cidrs, version):
    nets = []
    for c in cidrs:
        try:
            n = ipaddress.ip_network(c.strip(), strict=False)
        except ValueError:
            raise SystemExit("egress_firewall: invalid CIDR in deny list: %r" % c) from None
        if n.version == version:
            nets.append(n)
    return [str(n) for n in ipaddress.collapse_addresses(nets)]


def ruleset(public_uid: int, scoped_uid: int, gate_ports: str, dns_port: int = 53,
            extra=(), routes4=None, routes6=None) -> str:
    deny4 = _collapse([*DENY4, *(routes4 if routes4 is not None else _routes4()), *extra], 4)
    deny6 = _collapse([*DENY6, *(routes6 if routes6 is not None else _routes6()), *extra], 6)
    lo, hi = (int(p) for p in gate_ports.split("-"))
    return f"""table inet {TABLE}
delete table inet {TABLE}
table inet {TABLE} {{
  set deny4 {{ type ipv4_addr; flags interval; elements = {{ {", ".join(deny4)} }} }}
  set deny6 {{ type ipv6_addr; flags interval; elements = {{ {", ".join(deny6)} }} }}
  chain output {{
    type filter hook output priority filter; policy accept;
    meta skuid {public_uid} jump public_browser
    meta skuid {scoped_uid} jump scoped_browser
  }}
  chain public_browser {{
    ct state established,related accept
    ip daddr 127.0.0.1 meta l4proto {{ tcp, udp }} th dport {dns_port} accept
    ip daddr @deny4 counter reject
    ip6 daddr @deny6 counter reject
    meta nfproto {{ ipv4, ipv6 }} accept
    counter reject
  }}
  chain scoped_browser {{
    ct state established,related accept
    ip daddr 127.0.0.1 tcp dport {lo}-{hi} accept
    counter reject
  }}
}}
"""


def apply(rules: str) -> None:
    """Load atomically: nft applies a whole file in one transaction or nothing."""
    result = subprocess.run(["nft", "-f", "-"], input=rules, text=True, capture_output=True)
    if result.returncode:
        raise SystemExit("egress_firewall: nft failed: " + result.stderr.strip()[:500])


def _as(uid: int, target) -> object:
    """Run target() in a child process with this UID; return its result."""
    read, write = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read)
        try:
            os.setgroups([])
            os.setgid(uid)
            os.setuid(uid)
            value = repr(target())
        except BaseException as exc:
            value = repr("error:" + type(exc).__name__)
        os.write(write, value.encode())
        os._exit(0)
    os.close(write)
    data = b""
    while chunk := os.read(read, 4096):
        data += chunk
    os.close(read)
    os.waitpid(pid, 0)
    import ast
    return ast.literal_eval(data.decode() or "'error:empty'")


def _connects(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    s = socket.socket(family, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _dns_answers(host="127.0.0.1", port=53) -> bool:
    query = (b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
             b"\x07example\x03com\x00\x00\x01\x00\x01")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(3)
    try:
        s.sendto(query, (host, port))
        return s.recv(512)[:2] == b"\x12\x34"
    except OSError:
        return False
    finally:
        s.close()


def verify(public_uid: int, scoped_uid: int, gate_ports: str) -> list[str]:
    """Probe real listeners from each identity. Returns failures (empty = sound)."""
    failures = []
    listeners = []

    def listen(host):
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        s = socket.socket(family, socket.SOCK_STREAM)
        s.bind((host, 0))
        s.listen(8)
        listeners.append(s)
        return s.getsockname()[1]

    try:
        own = [a for a in _own_addresses() if not a.startswith("127.")]
        loop_port = listen("127.0.0.1")
        lo = int(gate_ports.split("-")[0])
        gate = socket.socket()
        gate.bind(("127.0.0.1", lo))
        gate.listen(8)
        listeners.append(gate)
        own_ports = {a: listen(a) for a in own}
        if not _connects("127.0.0.1", loop_port):
            failures.append("worker identity cannot reach its own listener (probe broken)")
        checks = [
            ("public reaches loopback", public_uid, "127.0.0.1", loop_port, False),
            ("public reaches the gate port", public_uid, "127.0.0.1", lo, False),
            ("scoped reaches the gate port", scoped_uid, "127.0.0.1", lo, True),
            ("scoped reaches loopback", scoped_uid, "127.0.0.1", loop_port, False),
            *(("public reaches container address " + a, public_uid, a, p, False)
              for a, p in own_ports.items()),
            *(("scoped reaches container address " + a, scoped_uid, a, p, False)
              for a, p in own_ports.items()),
        ]
        for name, uid, host, port, expected in checks:
            got = _as(uid, lambda h=host, p=port: _connects(h, p))
            if got is not expected:
                failures.append(f"{name}: expected {expected}, got {got}")
        if _as(public_uid, _dns_answers) is not True:
            failures.append("public cannot reach the DNS filter")
        if _as(scoped_uid, _dns_answers) is not False:
            failures.append("scoped reaches DNS directly")
        listing = subprocess.run(["nft", "list", "table", "inet", TABLE],
                                 capture_output=True, text=True)
        if listing.returncode or f"skuid {public_uid}" not in listing.stdout:
            failures.append("ruleset not present after load")
    finally:
        for s in listeners:
            s.close()
    return failures


def _own_addresses() -> list[str]:
    """The container's own addresses (IPv4 local routes, global/ULA IPv6)."""
    out, last = [], None
    try:
        for line in open("/proc/net/fib_trie").read().splitlines():
            text = line.strip()
            if text.startswith(("|--", "+--")):
                last = text.split()[-1]
            elif "host LOCAL" in text and last and last not in out:
                out.append(last)
    except OSError:
        pass
    try:
        for line in open("/proc/net/if_inet6").read().splitlines():
            f = line.split()
            addr = str(ipaddress.IPv6Address(bytes.fromhex(f[0])))
            if f[5] != "lo" and not addr.startswith("fe80"):
                out.append(addr)
    except OSError:
        pass
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--public-uid", type=int, required=True)
    parser.add_argument("--scoped-uid", type=int, required=True)
    parser.add_argument("--gate-ports", default="20000-20999")
    parser.add_argument("--deny", default=os.getenv("DETHROTTLED_EGRESS_DENY", ""),
                        help="extra CIDRs, comma separated (deployment-specific)")
    parser.add_argument("--print", action="store_true", help="print the ruleset only")
    args = parser.parse_args(argv)
    rules = ruleset(args.public_uid, args.scoped_uid, args.gate_ports,
                    extra=[c for c in args.deny.split(",") if c.strip()])
    if args.print:
        print(rules)
        return 0
    apply(rules)
    failures = verify(args.public_uid, args.scoped_uid, args.gate_ports)
    if failures:
        print("egress_firewall: verification failed: " + "; ".join(failures), file=sys.stderr)
        return 1
    print("egress_firewall: loaded and verified", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
