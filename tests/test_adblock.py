"""Domain policy, durable updates and real local redirect regressions."""

import io
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from dethrottled import adblock, netfilter


def body(extra="ads.example"):
    rules = [extra] + [f"track{i}.invalid" for i in range(10000)]
    return (
        "[Adblock Plus]\n! Title: HaGeZi's Multi PRO\n! Number of entries: "
        + str(len(rules))
        + "\n"
        + "\n".join("||" + r + "^" for r in rules)
        + "\n"
    ).encode()


class Reply(io.BytesIO):
    def __init__(self, payload=b"", code=200, headers=None):
        super().__init__(payload)
        self.code, self.headers = code, headers or {}


@pytest.fixture
def policy(tmp_path, monkeypatch):
    monkeypatch.setenv("DETHROTTLED_ADBLOCK", "1")
    manager = adblock.Filter(tmp_path)
    monkeypatch.setattr(adblock, "FILTER", manager)
    monkeypatch.setattr(manager, "start", lambda: None)
    manager.update(
        lambda *a, **k: Reply(body(), headers={"ETag": "v1", "Last-Modified": "yesterday"}), now=100
    )
    assert len(manager.rules) == 10001
    return manager


@pytest.mark.parametrize(
    "url,blocked",
    [
        ("https://ADS.EXAMPLE./path?q=1", True),
        ("https://a.b.ads.example", True),
        ("https://notads.example", False),
        ("https://ads.example.other", False),
        ("http://localhost", False),
        ("http://127.0.0.1", False),
        ("http://[::1]", False),
        ("http://browser-search:19888", False),
        ("file:///ads.example", False),
        ("wss://a.ads.example/socket", True),
        ("https://ads.example@clean.example", False),
    ],
)
def test_domain_boundaries(policy, url, blocked):
    assert bool(policy.match(url)) is blocked


def test_disabled_has_no_io_updates_or_counts(policy, monkeypatch):
    monkeypatch.setenv("DETHROTTLED_ADBLOCK", "0")
    policy.update(lambda *a, **k: pytest.fail("disabled updater called"))
    policy.check("https://ads.example")
    policy.load()
    assert policy.status()["state"] == "disabled" and not policy.counts
    adblock.Filter("/must-not-create").start()


def test_conditional_304_and_restart(policy):
    previous = policy.metadata["updated_at"]

    def opener(request, **kwargs):
        assert request.get_header("If-none-match") == "v1"
        assert request.get_header("If-modified-since") == "yesterday"
        raise urllib.error.HTTPError(request.full_url, 304, "", {}, io.BytesIO())

    policy.update(opener, now=200)
    restored = adblock.Filter(policy.directory)
    restored.load()
    assert restored.match("https://ads.example")
    assert restored.last_check == 200 and restored.metadata["updated_at"] == previous
    assert restored.error is None


@pytest.mark.parametrize(
    "bad",
    [
        b"<html>offline</html>",
        body().replace(b"||ads.example^", b"@@||ads.example^"),
        body().replace(b"10001", b"10002"),
        body()[:100],
    ],
)
def test_bad_download_retains_working_list(policy, bad):
    previous = policy.path.read_bytes()
    old = policy.rules
    policy.update(lambda *a, **k: Reply(bad), now=300)
    assert policy.path.read_bytes() == previous and policy.rules is old
    assert policy.error.startswith("update_failed:")


def test_offline_uses_last_good_snapshot(policy):
    def offline(*a, **k):
        raise OSError("offline")

    policy.update(offline, now=300)
    assert policy.rules and "offline" in policy.error
    fresh = adblock.Filter(policy.directory)
    fresh.load()
    assert fresh.match("http://ads.example")


def test_corrupt_disk_does_not_replace_live_rules(policy):
    policy.path.write_text("{corrupt")
    policy.load()
    assert policy.match("https://ads.example") and policy.error.startswith("cache_invalid:")
    restarted = adblock.Filter(policy.directory)
    restarted.load()
    assert restarted.status()["state"] == "unavailable" and restarted.error


def test_atomic_activation_failure_keeps_snapshot(policy, monkeypatch):
    old = policy.path.read_bytes()

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(adblock.os, "replace", fail)
    policy.update(lambda *a, **k: Reply(body("other.example")), now=400)
    assert policy.path.read_bytes() == old and policy.match("https://ads.example")
    assert not list(policy.directory.glob(".adblock-*"))


def test_reader_never_downloads(policy):
    reader = adblock.Filter(policy.directory, reader=True)
    reader.update(lambda *a, **k: pytest.fail("reader downloaded"))
    reader.load()
    assert reader.match("https://ads.example")


def test_start_does_not_wait_for_download(tmp_path, monkeypatch):
    monkeypatch.setenv("DETHROTTLED_ADBLOCK", "1")
    manager = adblock.Filter(tmp_path)
    entered, release = threading.Event(), threading.Event()

    def update():
        entered.set()
        release.wait(3)

    monkeypatch.setattr(manager, "update", update)
    manager.start()
    try:
        assert entered.wait(1) and manager.status()["state"] == "unavailable"
    finally:
        manager.stop()
        release.set()
        manager.thread.join(2)


def test_long_running_scheduler_checks_again(policy, monkeypatch):
    ticks = iter([100 + adblock.INTERVAL - 1, 100 + adblock.INTERVAL + 1])
    calls = []
    monkeypatch.setattr(adblock.time, "time", lambda: next(ticks, 100 + adblock.INTERVAL + 1))
    # Use a controlled wait to advance the clock without a real 24-hour delay.
    waits = []

    def wait(seconds):
        waits.append(seconds)
        if len(waits) == 2:
            policy.stop_event.set()

    monkeypatch.setattr(policy.stop_event, "wait", wait)
    monkeypatch.setattr(policy, "update", lambda: calls.append(1))
    policy._run()
    assert calls == [1]


@pytest.fixture
def origin():
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            hits.append(self.path)
            self.send_response(302 if self.path == "/redirect" else 200)
            self.send_header("Content-Type", "text/plain")
            if self.path == "/redirect":
                self.send_header("Location", "http://ads.example/should-not-arrive")
            self.end_headers()
            self.wfile.write(b"legitimate fact 7341")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", hits
    server.shutdown()
    server.server_close()


def test_requests_redirect_blocked_and_internal_preserved(policy, origin):
    base, hits = origin
    assert netfilter.get(base + "/content").text == "legitimate fact 7341"
    with pytest.raises(adblock.AdblockBlocked, match=r"adblock_blocked:ads\.example"):
        netfilter.get(base + "/redirect")
    assert hits == ["/content", "/redirect"]
    assert policy.counts["http"] == 1


def test_tls_redirects_are_checked_before_getter(policy):
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(
            status_code=302, headers={"Location": "https://ads.example"}, close=lambda: None
        )

    with pytest.raises(adblock.AdblockBlocked):
        netfilter.get_using(get, "https://clean.example")
    assert calls == ["https://clean.example"]


def test_native_tls_redirect(policy, origin):
    tls = pytest.importorskip("curl_cffi.requests")
    base, hits = origin
    with pytest.raises(adblock.AdblockBlocked):
        netfilter.get_using(tls.get, base + "/redirect", impersonate="chrome")
    assert hits == ["/redirect"]


def test_ddgs_native_redirect(policy, origin):
    pytest.importorskip("ddgs.http_client")
    from ddgs.http_client import HttpClient

    netfilter.install_ddgs()
    base, hits = origin
    with pytest.raises(adblock.AdblockBlocked):
        HttpClient().get(base + "/redirect")
    assert hits == ["/redirect"]


def test_fetch_policy_does_not_escalate(policy, monkeypatch):
    from dethrottled import fetch

    monkeypatch.setattr(fetch, "_tier_direct", lambda *a, **k: pytest.fail("blocked URL fetched"))
    result = fetch.fetch_and_extract("https://ads.example/doc.pdf")
    assert result["policy_blocked"] == "adblock" and result["reason"].startswith("adblock_blocked:")


def test_transcript_gets_guarded_session(policy, monkeypatch):
    from dethrottled import media

    def api(**kwargs):
        assert isinstance(kwargs["http_client"], netfilter.Session)
        raise adblock.AdblockBlocked("ads.example")

    import sys

    monkeypatch.setitem(
        sys.modules,
        "youtube_transcript_api",
        SimpleNamespace(
            YouTubeTranscriptApi=api, NoTranscriptFound=type("NoTranscriptFound", (Exception,), {})
        ),
    )
    assert media.transcript("https://youtu.be/abcdefghijk")[2] == "adblock_blocked:ads.example"


def test_new_valid_list_activates_and_reader_reloads(policy):
    reader = adblock.Filter(policy.directory, reader=True)
    reader.load()
    policy.update(lambda *a, **k: Reply(body("other.example")), now=400)
    reader.load()
    assert reader.match("https://other.example") and not reader.match("https://ads.example")
    assert reader.metadata["updated_at"] == 400


def test_corrupt_metadata_is_reported_without_crashing(policy):
    data = __import__("json").loads(policy.path.read_text())
    data["checked_at"] = {"wrong": "type"}
    policy.path.write_text(__import__("json").dumps(data))
    policy.load()
    assert policy.rules and policy.error.startswith("cache_invalid:")


def test_configured_rpc_origin_preserved_but_content_fetch_filtered(policy, monkeypatch):
    monkeypatch.setenv("DETHROTTLED_CRAWL4AI_URL", "https://ads.example")
    import requests

    calls = []

    def send(self, request, **kwargs):
        calls.append(request.url)
        response = requests.Response()
        response.status_code = 200
        response._content = b"ok"
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    assert netfilter.get("https://ads.example/health").status_code == 200
    with pytest.raises(adblock.AdblockBlocked):
        # A content fetch's identity session never inherits the RPC exemption.
        netfilter.Session().get("https://ads.example/article")
    assert calls == ["https://ads.example/health"]


def test_agent_workflow_stops_on_policy_refusal(policy):
    from dethrottled.workflow import guidance

    result = guidance(
        {"url": "https://ads.example", "quality": "failed", "policy_blocked": "adblock"}
    )
    assert result["state"] == "policy_blocked" and not result["next_actions"]


def test_crawl_policy_reply_is_not_reported_as_antibot_failure():
    from dethrottled.fetch import _crawl4ai_target_error

    payload = {
        "success": False,
        "error_message": "Blocked by anti-bot protection: Structural: minimal_text",
        "status_code": 451,
        "response_headers": {"X-Dethrottled-Blocked": "adblock"},
    }
    assert _crawl4ai_target_error(payload).startswith("adblock_blocked:")


def test_cache_permissions_without_descriptor_chmod(tmp_path, monkeypatch):
    monkeypatch.setenv('DETHROTTLED_ADBLOCK', '1')
    monkeypatch.delattr(adblock.os, 'fchmod', raising=False)
    manager = adblock.Filter(tmp_path)
    manager.update(lambda *a, **k: Reply(body()), now=100)
    assert manager.rules and manager.error is None
    restored = adblock.Filter(tmp_path)
    restored.load()
    assert restored.rules == manager.rules
