"""Native browser lane (1.9.0): the DNS filter and the browser guard."""
import dns.message
import dns.rcode
import dns.rrset
import pytest

from dethrottled import adblock_browser, dns_filter
from dethrottled import browser_guard as guard
from dethrottled import egress_firewall as egress


def response(name, rtype, *records):
    query = dns.message.make_query(name, rtype)
    reply = dns.message.make_response(query)
    for owner, kind, value in records:
        reply.answer.append(dns.rrset.from_text(owner, 60, "IN", kind, value))
    return reply


# ── DNS filter ────────────────────────────────────────────────────────────────

def test_a_private_address_is_removed_and_a_public_one_kept():
    out = dns_filter.filter_response(response(
        "mixed.example.com", "A", ("mixed.example.com.", "A", "172.16.0.5"),
        ("mixed.example.com.", "A", "93.184.215.14")))
    assert out.rcode() == dns.rcode.NOERROR
    assert [r.address for r in out.answer[0]] == ["93.184.215.14"]


@pytest.mark.parametrize("address", ["127.0.0.1", "172.20.1.3", "172.31.1.4", "169.254.169.254",
                                     "100.64.0.1", "0.0.0.0"])
def test_a_public_name_that_points_at_a_private_address_is_refused(address):
    out = dns_filter.filter_response(response(
        "rebind.example.com", "A", ("rebind.example.com.", "A", address)))
    assert out.rcode() == dns.rcode.REFUSED and not out.answer


def test_a_cname_chain_that_ends_inside_the_network_is_refused():
    out = dns_filter.filter_response(response(
        "cdn.example.com", "A", ("cdn.example.com.", "CNAME", "intranet.corp."),
        ("intranet.corp.", "A", "172.16.4.2")))
    assert out.rcode() == dns.rcode.REFUSED


@pytest.mark.parametrize("address", ["::1", "fd00::1", "fe80::1", "::ffff:127.0.0.1"])
def test_private_ipv6_answers_are_refused(address):
    out = dns_filter.filter_response(response(
        "six.example.com", "AAAA", ("six.example.com.", "AAAA", address)))
    assert out.rcode() == dns.rcode.REFUSED


def test_https_records_lose_address_hints_but_keep_alpn():
    out = dns_filter.filter_response(response(
        "svc.example.com", "HTTPS", ("svc.example.com.", "HTTPS",
                                     '1 . alpn="h3,h2" ipv4hint="127.0.0.1" ipv6hint="::1"')))
    text = out.answer[0].to_text()
    assert "alpn" in text and "hint" not in text


def test_a_hagezi_domain_gets_nxdomain_without_asking_upstream(monkeypatch):
    monkeypatch.setattr(dns_filter.adblock.FILTER, "match",
                        lambda url: "tracker.example" if "tracker.example" in url else None)
    monkeypatch.setattr(dns_filter.adblock.FILTER, "blocked", lambda *a: None)
    monkeypatch.setattr(dns_filter.dns.query, "udp", lambda *a, **k: pytest.fail("asked upstream"))
    wire = dns.message.make_query("ads.tracker.example", "A").to_wire()
    out = dns.message.from_wire(dns_filter.answer(wire, ["192.0.2.53"]))
    assert out.rcode() == dns.rcode.NXDOMAIN


def test_upstreams_never_include_the_filter_itself(tmp_path):
    conf = tmp_path / "resolv.conf"
    conf.write_text("nameserver 127.0.0.1\nnameserver 127.0.0.11\noptions ndots:0\n")
    assert dns_filter.upstreams(str(conf)) == ["127.0.0.11"]


def test_the_scoped_lane_resolves_literals_and_hosts_entries_without_dns(tmp_path, monkeypatch):
    hosts = tmp_path / "hosts"
    hosts.write_text("172.16.0.7 intranet.local intranet\n")
    monkeypatch.setattr(dns_filter, "HOSTS", str(hosts))
    assert dns_filter.resolve_unfiltered("172.18.5.5", 80, "/missing") == ["172.18.5.5"]
    assert dns_filter.resolve_unfiltered("intranet", 80, "/missing") == ["172.16.0.7"]


# ── egress firewall (rules; loading and probing need root, see security-1.9.0) ──

def rules(**kw):
    return egress.ruleset(10005, 10006, "20000-20999", routes4=kw.pop("routes4", []),
                          routes6=kw.pop("routes6", []), **kw)


def covered(cidr, elements):
    import ipaddress
    entries = elements.split("elements = {")[1].replace(" ", "").split(",")
    target = ipaddress.ip_network(cidr)
    return any(target.subnet_of(ipaddress.ip_network(e)) for e in entries
               if ipaddress.ip_network(e).version == target.version)


def test_the_public_browser_may_reach_only_the_dns_filter_locally():
    text = rules()
    public = text.split("chain public_browser")[1].split("chain scoped_browser")[0]
    assert "ip daddr 127.0.0.1 meta l4proto { tcp, udp } th dport 53 accept" in public
    assert public.index("dport 53 accept") < public.index("@deny4")
    assert "meta skuid 10005 jump public_browser" in text


def test_the_scoped_browser_may_reach_only_the_gate_ports():
    scoped = rules().split("chain scoped_browser")[1]
    lines = [line.strip() for line in scoped.splitlines() if line.strip()]
    gate = "ip daddr 127.0.0.1 tcp dport 20000-20999 accept"
    assert gate in lines and lines.index("counter reject") > lines.index(gate)
    assert not any("dport 53" in line for line in lines)


@pytest.mark.parametrize("cidr", [egress._TEN, "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
                                  "172.16.0.0/12", "224.0.0.0/3", "198.18.0.0/15"])
def test_private_reserved_and_multicast_ipv4_is_denied(cidr):
    assert covered(cidr, rules().split("set deny4")[1].split("}")[0])


@pytest.mark.parametrize("cidr", ["::/127", "::ffff:0:0/96", "64:ff9b::/96", "2002::/16",
                                  "fc00::/7", "fe80::/10", "ff00::/8", "2001::/23"])
def test_loopback_private_translation_and_multicast_ipv6_is_denied(cidr):
    assert covered(cidr, rules().split("set deny6")[1].split("}")[0])


def test_routes_and_deployment_extras_are_denied_and_collapsed():
    text = rules(routes4=["203.0.113.0/24", "198.51.100.0/24"], routes6=["2001:db8:1::/48"],
                 extra=["8.8.8.0/24", "2620:fe::/48"])
    deny4 = text.split("set deny4")[1].split("}")[0]
    deny6 = text.split("set deny6")[1].split("}")[0]
    assert "8.8.8.0/24" in deny4 and "2620:fe::/48" in deny6
    assert "2001:db8:1::/48" not in deny6  # already inside 2001:db8::/32


def test_a_malformed_deny_entry_stops_the_start():
    with pytest.raises(SystemExit):
        rules(extra=["172.16.0.0/33"])


def test_route_tables_are_read_from_proc(tmp_path):
    route = tmp_path / "route"
    route.write_text("Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\n"
                     "eth0\t00000000\t010012AC\t0003\t0\t0\t0\t00000000\n"
                     "eth0\t000012AC\t00000000\t0001\t0\t0\t0\t0000FFFF\n")
    assert egress._routes4(str(route)) == ["172.18.0.0/16"]
    six = tmp_path / "ipv6_route"
    six.write_text("fd000000000000000000000000000000 40 " + "0" * 32 + " 00 " + "0" * 32
                   + " 00000100 00000001 00000000 00000001 eth0\n")
    assert egress._routes6(str(six)) == ["fd00::/64"]


def test_the_native_lane_needs_a_verified_firewall(monkeypatch):
    monkeypatch.setenv("DETHROTTLED_BROWSER_NETWORK", "native")
    monkeypatch.delenv("DETHROTTLED_EGRESS_FIREWALL", raising=False)
    assert not adblock_browser.native_lane()
    monkeypatch.setenv("DETHROTTLED_EGRESS_FIREWALL", "verified")
    assert adblock_browser.native_lane()
    monkeypatch.setenv("DETHROTTLED_BROWSER_NETWORK", "gate")
    assert not adblock_browser.native_lane()


def test_the_guard_records_only_adblocked_lookups(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    monkeypatch.setattr(guard.adblock.FILTER, "match",
                        lambda url: "ads.example" if "ads.example" in url else None)
    monkeypatch.setattr(guard.adblock.FILTER, "blocked", lambda *a: None)
    handlers = {}
    context = SimpleNamespace(on=lambda name, fn: handlers.setdefault(name, fn))
    events = asyncio.run(guard.install(context))
    handlers["requestfailed"](SimpleNamespace(url="https://ads.example/x",
                                              failure="net::ERR_NAME_NOT_RESOLVED"))
    handlers["requestfailed"](SimpleNamespace(url="https://site.example/",
                                              failure="net::ERR_NAME_NOT_RESOLVED"))
    handlers["requestfailed"](SimpleNamespace(url="https://ads.example/y",
                                              failure="net::ERR_CONNECTION_RESET"))
    assert [e["domain"] for e in events] == ["ads.example"]
    assert context._dethrottled_lane == "native"


def test_the_machines_language_becomes_one_consistent_context_locale(monkeypatch):
    monkeypatch.setenv("DETHROTTLED_BROWSER_LANG", "en_GB.UTF-8")
    assert adblock_browser.browser_locale() == "en-GB"
    monkeypatch.setenv("DETHROTTLED_BROWSER_LANG", "")
    assert adblock_browser.browser_locale() == ""
    monkeypatch.setenv("DETHROTTLED_BROWSER_LANG", "en_GB; rm -rf /")
    assert adblock_browser.browser_locale() == ""
