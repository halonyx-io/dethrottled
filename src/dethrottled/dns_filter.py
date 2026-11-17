"""DNS filter: the browser worker's only resolver on the native lane (1.9.0).

Listens on 127.0.0.1:53 (UDP and TCP) and forwards to the resolver the
container started with (Docker's), saved before /etc/resolv.conf is pointed
here. For every answer:

* a query for a HaGeZi domain gets NXDOMAIN: the same list and domain-level
  granularity the CONNECT gate applied to CONNECT hosts;
* A/AAAA records with a non-public address are removed, and a query left
  with none gets REFUSED. Chrome connects only to addresses it resolved, so
  this is what makes DNS rebinding toothless on the native lane;
* ipv4hint/ipv6hint are removed from HTTPS/SVCB records, so no address
  reaches Chrome except through the checked A/AAAA path.

Started as root by the worker's start script, it binds port 53 and drops to
an unprivileged user before reading any query.
"""
from __future__ import annotations

import argparse
import ipaddress
import os
import socket
import socketserver
import sys
import threading

import dns.flags
import dns.message
import dns.query
import dns.rcode
import dns.rdatatype
import dns.rdtypes.svcbbase
import dns.resolver

try:
    from . import adblock
except ImportError:
    import dethrottled_adblock as adblock

HINTS = {"ipv4hint", "ipv6hint"}
COUNTS = {"queries": 0, "adblock": 0, "private_answer": 0, "upstream_error": 0}
_counts_lock = threading.Lock()


def _count(key):
    with _counts_lock:
        COUNTS[key] += 1


def upstreams(path: str) -> list[str]:
    try:
        resolver = dns.resolver.Resolver(filename=path, configure=True)
        return [ns for ns in resolver.nameservers if ns not in {"127.0.0.1", "::1"}]
    except Exception:
        return []


def _public(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_global
    except ValueError:
        return False


def _strip_hints(rdata):
    params = getattr(rdata, "params", None)
    if not params:
        return rdata
    keep = {k: v for k, v in params.items()
            if dns.rdtypes.svcbbase.ParamKey.to_text(k).lower() not in HINTS}
    if len(keep) == len(params):
        return rdata
    return rdata.replace(params=keep)


def filter_response(response: dns.message.Message) -> dns.message.Message:
    """Remove non-public addresses and address hints; REFUSED if nothing is left."""
    had_address = removed = False
    for section in (response.answer, response.additional):
        for rrset in list(section):
            if rrset.rdtype in (dns.rdatatype.A, dns.rdatatype.AAAA):
                had_address = True
                keep = [r for r in rrset if _public(r.address)]
                if len(keep) != len(rrset):
                    removed = True
                    if keep:
                        new = rrset.copy()
                        new.clear()
                        for r in keep:
                            new.add(r)
                        section[section.index(rrset)] = new
                    else:
                        section.remove(rrset)
            elif rrset.rdtype in (dns.rdatatype.HTTPS, dns.rdatatype.SVCB):
                new = rrset.copy()
                new.clear()
                for r in rrset:
                    new.add(_strip_hints(r))
                section[section.index(rrset)] = new
    if removed:
        _count("private_answer")
        left = any(rrset.rdtype in (dns.rdatatype.A, dns.rdatatype.AAAA)
                   for rrset in response.answer)
        if had_address and not left:
            response.set_rcode(dns.rcode.REFUSED)
    return response


def answer(wire: bytes, servers: list[str], *, timeout: float = 4.0) -> bytes:
    query = dns.message.from_wire(wire)
    _count("queries")
    name = query.question[0].name.to_text(omit_final_dot=True) if query.question else ""
    if name and adblock.FILTER.match("https://" + name + "/"):
        _count("adblock")
        adblock.FILTER.blocked(name, "dns")
        reply = dns.message.make_response(query)
        reply.set_rcode(dns.rcode.NXDOMAIN)
        return reply.to_wire()
    for server in servers:
        try:
            response = dns.query.udp(query, server, timeout=timeout)
            if response.flags & dns.flags.TC:
                response = dns.query.tcp(query, server, timeout=timeout)
            return filter_response(response).to_wire()
        except Exception:
            _count("upstream_error")
            continue
    reply = dns.message.make_response(query)
    reply.set_rcode(dns.rcode.SERVFAIL)
    return reply.to_wire()


def _safe(wire, servers):
    try:
        return answer(wire, servers)
    except Exception:
        return None  # malformed query: no reply, as a resolver would


def _drop_capabilities():
    """Empty the bounding set and set no_new_privs, so the UID change is final."""
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    pr_capbset_drop, pr_set_no_new_privs = 24, 38
    for cap in range(64):
        libc.prctl(pr_capbset_drop, cap, 0, 0, 0)  # EINVAL past the last cap is fine
    if libc.prctl(pr_set_no_new_privs, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "no_new_privs")


def serve(host: str, port: int, servers: list[str], user: int | None, groups: list[int]):
    class UDP(socketserver.BaseRequestHandler):
        def handle(self):
            data, sock = self.request
            reply = _safe(data, servers)
            if reply:
                sock.sendto(reply, self.client_address)

    class TCP(socketserver.StreamRequestHandler):
        def handle(self):
            head = self.rfile.read(2)
            if len(head) < 2:
                return
            data = self.rfile.read(int.from_bytes(head, "big"))
            reply = _safe(data, servers)
            if reply:
                self.wfile.write(len(reply).to_bytes(2, "big") + reply)

    class UDPServer(socketserver.ThreadingMixIn, socketserver.UDPServer):
        daemon_threads = True
        allow_reuse_address = True

    class TCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        daemon_threads = True
        allow_reuse_address = True

    udp, tcp = UDPServer((host, port), UDP), TCPServer((host, port), TCP)
    if user is not None:  # bound; now give up root before reading anything
        _drop_capabilities()
        os.setgroups(groups)
        os.setgid(user)
        os.setuid(user)
    adblock.FILTER.start()
    threading.Thread(target=tcp.serve_forever, daemon=True).start()
    print("dns_filter ready on %s:%d -> %s" % (host, port, ",".join(servers)), flush=True)
    udp.serve_forever()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=53)
    parser.add_argument("--upstream-file", required=True)
    parser.add_argument("--user", type=int, default=None)
    parser.add_argument("--groups", default="")
    args = parser.parse_args(argv)
    servers = upstreams(args.upstream_file)
    if not servers:
        print("dns_filter: no upstream resolver in " + args.upstream_file, file=sys.stderr)
        return 2
    groups = [int(g) for g in args.groups.split(",") if g.strip()]
    serve(args.listen, args.port, servers, args.user, groups)
    return 0


def resolve_unfiltered(host: str, port: int, upstream_file: str) -> list[str]:
    """For the scoped lane (gate), which may reach private hosts by design."""
    try:
        ipaddress.ip_address(host.strip("[]"))
        return [host.strip("[]")]
    except ValueError:
        pass
    for line in _read(HOSTS):
        fields = line.split("#", 1)[0].split()
        if len(fields) >= 2 and host.lower().rstrip(".") in (f.lower() for f in fields[1:]):
            return [fields[0]]
    resolver = dns.resolver.Resolver(filename=upstream_file, configure=True)
    resolver.nameservers = upstreams(upstream_file) or resolver.nameservers
    addresses = []
    for kind in ("A", "AAAA"):
        try:
            addresses += [r.address for r in resolver.resolve(host, kind, lifetime=5)]
        except Exception:
            continue
    if not addresses:
        raise socket.gaierror(socket.EAI_NONAME, "name not resolved: " + host)
    return addresses


HOSTS = "/etc/hosts"


def _read(path):
    try:
        return open(path, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return []


if __name__ == "__main__":
    sys.exit(main())
