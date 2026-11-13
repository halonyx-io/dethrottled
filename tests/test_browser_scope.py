"""Every browser caller gives a public target the public browser scope.

Internal scope pins all browser egress to allowed_hosts, so subresources on
other hosts never load (crates.io READMEs, Bluesky profiles, AWS WAF
challenges). research.browser_public is the single rule; these tests cover
the callers that previously bypassed it and the rendered-shell additions.
"""
import pytest

from dethrottled import fetch, research
from dethrottled.readplan import run

fastapi_testclient = pytest.importorskip("fastapi.testclient")
from dethrottled import search as fs  # noqa: E402
from dethrottled import server as srv  # noqa: E402

URL = "https://fixture.example/report"


def test_browser_public_rule(monkeypatch):
    monkeypatch.setattr(research, "public_url", lambda url: url.startswith("https://pub"))
    assert research.browser_public("https://public.example/") is True
    assert research.browser_public("http://intranet.lan/") is False
    assert research.browser_public("http://intranet.lan/", requested=True) is True


def test_read_plan_recovery_uses_public_scope(monkeypatch):
    monkeypatch.setattr(research, "public_url", lambda url: True)
    sent = []

    def drive(payload, timeout=None):
        sent.append(payload)
        return {"ok": False}

    thin = {"url": URL, "quality": "thin", "content": "A report is loading.",
            "content_status": "short"}
    run(URL, thin, read=lambda *a, **k: {}, drive=drive, options={}, browser_available=True)
    assert sent and all(p["public_only"] is True for p in sent)
    assert all(p["allowed_hosts"] == ["fixture.example"] for p in sent)


def _drive_client(monkeypatch, responder):
    monkeypatch.setattr(srv.fs, "BROWSER_SEARCH_URL", "http://browser-search:19888")
    monkeypatch.setattr(srv.fs, "browser_drive", responder)
    return fastapi_testclient.TestClient(srv.app)


def _echo(payload):
    return {"ok": True, "steps": [], "echo": dict(payload),
            "session": {"id": payload.get("session"), "persistent": True}}


@pytest.mark.parametrize("public_target", [True, False])
def test_drive_defaults_public_targets_to_public_scope(monkeypatch, public_target):
    monkeypatch.setattr(research, "public_url", lambda url: public_target)
    client = _drive_client(monkeypatch, _echo)
    body = client.post("/drive", json={"url": "https://crates.io/crates/serde"}).json()
    assert body["echo"]["public_only"] is public_target


def test_drive_respects_an_explicit_scope(monkeypatch):
    monkeypatch.setattr(research, "public_url", lambda url: True)
    client = _drive_client(monkeypatch, _echo)
    body = client.post("/drive", json={"url": "https://crates.io/", "public_only": False}).json()
    assert body["echo"]["public_only"] is False


def test_drive_keeps_internal_scope_for_private_allowed_hosts(monkeypatch):
    monkeypatch.setattr(research, "public_url", lambda url: "intranet" not in url)
    client = _drive_client(monkeypatch, _echo)
    body = client.post("/drive", json={"url": "https://crates.io/",
                                       "allowed_hosts": ["crates.io", "intranet.lan"]}).json()
    assert body["echo"]["public_only"] is False


def test_drive_retries_once_with_the_sessions_own_scope(monkeypatch):
    calls = []

    def responder(payload):
        calls.append(payload.get("public_only"))
        if len(calls) == 1:
            raise fs.BrowserWorkerError(409, "session_scope_changed_use_new_session")
        return _echo(payload)

    client = _drive_client(monkeypatch, responder)
    body = client.post("/drive", json={"session": "s1",
                                       "steps": [{"action": "text"}]}).json()
    assert calls == [False, True]
    assert body["echo"]["public_only"] is True


def test_drive_does_not_retry_an_explicit_scope(monkeypatch):
    def responder(payload):
        raise fs.BrowserWorkerError(409, "session_scope_changed_use_new_session")

    client = _drive_client(monkeypatch, responder)
    response = client.post("/drive", json={"session": "s1", "public_only": False,
                                           "steps": [{"action": "text"}]})
    assert response.status_code == 409


def test_rendered_shell_escalates_using_source_size():
    rendered = {"chars": 1500, "content_type": ""}
    assert fetch._looks_like_shell("crawl4ai", rendered, 120_000)
    assert not fetch._looks_like_shell("crawl4ai", rendered, 20_000)
    assert not fetch._looks_like_shell("headed", rendered, 120_000)


def test_crawl_payload_keeps_source_size_and_descriptions():
    html = ('<html><head><meta property="og:description" content="Official account: '
            'bugs, feature requests, feedback."></head><body>' + "<div></div>" * 3000
            + "</body></html>")
    payload, reason, _ = fetch._crawl4ai_payload(
        {"markdown": "Trending topics and links. " * 20, "html": html}, URL)
    assert reason == ""
    assert payload["source_html_bytes"] == len(html)
    assert payload["page_descriptions"] == ["Official account: bugs, feature requests, feedback."]


def test_thin_render_is_supplemented_from_kept_descriptions():
    candidate = {"text": "Trending", "chars": 8, "content_type": "",
                 "extraction": {}, "warnings": []}
    fetch._supplement_thin(candidate, "", ["Official account: bugs, feature requests."])
    assert candidate["text"].startswith("Official account")
    assert candidate["extraction"]["pre_supplement_chars"] == 8


def _headed(monkeypatch, replies):
    calls = []

    class Response:
        def __init__(self, value):
            self.value = value

        def raise_for_status(self):
            pass

        def json(self):
            return self.value

    def post(url, json=None, headers=None, timeout=None):
        calls.append(json)
        reply = replies[len(calls) - 1] if len(calls) <= len(replies) else replies[-1]
        if isinstance(reply, Exception):
            raise reply
        return Response(reply)

    monkeypatch.setattr(fetch.requests, "post", post)
    monkeypatch.setattr(research, "public_url", lambda url: True)
    return calls


FIRST = "<html><body><p>" + "Trending topics. " * 10 + "</p></body></html>"
SETTLED = ("<html><body><p>" + "Official account: bugs, feature requests, feedback. " * 30
           + "</p></body></html>")


def _reply(html):
    return {"ok": True, "steps": [{"action": "html", "data": html,
                                   "document_ready_state": "complete"}]}


def test_headed_read_takes_the_settled_capture_when_it_reads_more(monkeypatch):
    calls = _headed(monkeypatch, [_reply(FIRST), _reply(SETTLED)])
    payload, reason, _ = fetch._headed_read("https://bsky.app/profile/bsky.app", "http://dnb")
    assert reason == "" and "Official account" in payload["html"]
    assert calls[0]["steps"][0]["action"] == "wait"
    assert calls[1]["steps"][0]["action"] == "settle" and "url" not in calls[1]


def test_failed_settle_keeps_the_first_capture(monkeypatch):
    failed = {"ok": False, "steps": [{"action": "settle", "ok": False,
                                      "reason": "navigation_outside_allowed_hosts"}]}
    _headed(monkeypatch, [_reply(SETTLED), failed])
    payload, reason, _ = fetch._headed_read("https://www.indeed.com/cmp/Google", "http://dnb")
    assert reason == "" and "Official account" in payload["html"]


def test_headed_settle_can_be_disabled(monkeypatch):
    monkeypatch.setenv("DETHROTTLED_HEADED_SETTLE", "0")
    calls = _headed(monkeypatch, [_reply(FIRST), _reply(SETTLED)])
    fetch._headed_read("https://bsky.app/profile/bsky.app", "http://dnb")
    assert not any(step["action"] == "settle" for call in calls for step in call["steps"])
