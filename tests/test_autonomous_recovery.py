"""Observable acquisition and validation behavior, including negative controls."""

import asyncio
import json

import pytest

from dethrottled import extract
from dethrottled import fetch as f
from dethrottled.access import AccessError, AccessMiddleware
from dethrottled.challenges import classify

ARTICLE = (
    "<html><body><article>"
    + ("The regional allocation is 7341 tonnes. " * 40)
    + "</article></body></html>"
)
CHALLENGE = (
    "<html><title>Verification Required</title><body>Please wait while we verify your request"
    '<script src="https://geo.captcha-delivery.com/check"></script></body></html>'
)


@pytest.mark.parametrize(
    "body,provider",
    [
        (CHALLENGE, "datadome"),
        ("<title>Just a moment...</title><body>Verifying you are human</body>", "cloudflare"),
        ('<body><div id="px-captcha">Press & hold to verify</div></body>', "perimeterx"),
        (
            '<body>Complete the security check<div class="sec-if-cpt-container"></div></body>',
            "akamai",
        ),
        ("<body>Verification required incapsula incident id 123</body>", "imperva"),
        ("Please wait while we verify your request...", "generic"),
    ],
)
def test_challenge_families(body, provider):
    assert classify(body) == provider


@pytest.mark.parametrize(
    "body",
    [
        ARTICLE.replace(
            "<article>",
            '<article><script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>',
        ),
        (
            "<html><body>This article discusses datadome, akamai, reference # "
            "and incident id.</body></html>"
        ),
        (
            "<html><body>Cloudflare challenge-platform shows Just a moment "
            "while verifying you are human.</body></html>"
        ),
    ],
)
def test_vendor_mentions_do_not_block_articles(body):
    assert not classify(body)


@pytest.fixture
def tiers(monkeypatch, tmp_path):
    monkeypatch.setenv("DETHROTTLED_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DETHROTTLED_BROWSER_SEARCH_URL", "http://browser")
    monkeypatch.setattr(f, "ENABLE_TLS", True)
    monkeypatch.setattr(f, "ENABLE_JINA", False)
    monkeypatch.setattr(f, "CRAWL4AI_URL", "")
    monkeypatch.setattr(f, "_tier_direct", lambda *a: ({}, "challenge_detected", a[0]))
    monkeypatch.setattr(f, "_tier_tls", lambda u: ({"html": CHALLENGE}, "", u))
    f._tier_rest.clear()
    return monkeypatch


def test_default_read_recovers_challenge_without_opt_in(tiers):
    seen = []

    def headed(u):
        seen.append(u)
        return {"html": ARTICLE}, "", u

    tiers.setattr(f, "_tier_headed", headed)
    result = f.fetch_and_extract("https://source.example/report")
    assert result["ok"] and result["tier"] == "headed" and len(seen) == 1


def test_explicit_render_never_skips_automatic_browser(tiers):
    tiers.setattr(f, "_tier_headed", lambda u: pytest.fail("render forbidden"))
    assert not f.fetch_and_extract("https://source.example/report", allow_render=False)["ok"]


def test_normal_prose_does_not_acquire_browser(tiers):
    tiers.setattr(f, "_tier_direct", lambda *a: ({"html": ARTICLE}, "", a[0]))
    tiers.setattr(f, "_tier_headed", lambda u: pytest.fail("unnecessary browser"))
    assert f.fetch_and_extract("https://source.example/report")["tier"] == "direct"


def test_headed_waits_and_checkpoints_with_scoped_identity(monkeypatch):
    calls = []
    reads = iter([CHALLENGE, ARTICLE, ARTICLE, ARTICLE])

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            body = calls[-1]
            data = next(reads) if body["steps"][-1]["action"] == "html" else True
            return {
                "ok": True,
                "steps": [{"data": data}],
                "final": {"url": "https://source.example"},
            }

    def post(url, **kwargs):
        calls.append(kwargs["json"])
        return Response()

    monkeypatch.setenv("DETHROTTLED_BROWSER_SEARCH_URL", "http://browser")
    monkeypatch.setattr(f.requests, "post", post)
    for namespace in ["alice", "alice", "bob"]:
        token = f._READ_OPTIONS.set({"admission_key": namespace, "public_only": True})
        try:
            payload, reason, _ = f._tier_headed("https://source.example")
        finally:
            f._READ_OPTIONS.reset(token)
        assert payload.get("html") == ARTICLE and not reason
    navigations = [c for c in calls if c.get("url")]
    assert navigations[0]["session"] == navigations[1]["session"]
    assert navigations[1]["session"] != navigations[2]["session"]
    assert any(c["steps"][0]["action"] == "checkpoint" for c in calls)
    assert all(not c.get("close_session") for c in calls)


def test_challenge_deadline_reports_unresolved(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True, "steps": [{"data": CHALLENGE}]}

    monkeypatch.setenv("DETHROTTLED_BROWSER_SEARCH_URL", "http://browser")
    monkeypatch.setenv("DETHROTTLED_CHALLENGE_WAIT_SECONDS", "0")
    monkeypatch.setattr(f.requests, "post", lambda *a, **kw: Response())
    payload, reason, _ = f._tier_headed("https://source.example")
    assert not payload and reason == "headed_challenge_unresolved:datadome"


def test_whitespace_is_not_extracted_evidence(tiers):
    tiers.setattr(f, "_tier_direct", lambda *a: ({"html": "<body>   </body>"}, "", a[0]))
    tiers.setattr(f, "_tier_tls", lambda u: ({}, "empty", u))
    tiers.setattr(
        extract,
        "extract",
        lambda *a, **kw: {
            "ok": True,
            "text": "   ",
            "chars": 3,
            "tier": "short",
            "reason": "empty",
        },
    )
    assert not f.fetch_and_extract("https://source.example")["ok"]


def test_thin_is_retained_with_explicit_quality(tiers):
    from dethrottled import server

    short = (
        "<body><p>A real announcement with forty-one participants "
        "and one short description.</p></body>"
    )
    tiers.setattr(f, "_tier_direct", lambda *a: ({"html": short}, "", a[0]))
    tiers.setattr(f, "_tier_tls", lambda u: ({}, "empty", u))
    result = f.fetch_and_extract("https://source.example")
    assert result["ok"] and result["quality"] == "thin"
    tiers.setattr(f, "fetch_and_extract", lambda *a, **kw: result)
    row = server._extract_once("https://source.example", 3000, fresh=True)
    assert row["quality"] == "thin" and row["content"].strip()


def test_limiting_reason_identifies_backoff_policy():
    class Registry:
        def verify(self, _):
            return {"namespace": "a", "scopes": ["web"]}

    class Gate:
        def acquire(self, _):
            raise AccessError("rate_limited", 429, 17)

    async def run():
        messages = []

        async def send(m):
            messages.append(m)

        async def unused(*a):
            pytest.fail("must not call backend")

        await AccessMiddleware(unused, registry=Registry(), admission=Gate())(
            {"type": "http", "path": "/search", "headers": []}, unused, send
        )
        payload = json.loads(messages[1]["body"])
        assert payload["limiter"] == "request_rate" and payload["retry_kind"] == "window"
        assert dict(messages[0]["headers"])[b"retry-after"] == b"17"

    asyncio.run(run())


def test_document_text_is_not_mistaken_for_an_interstitial(tiers):
    tiers.setattr(
        f,
        "_tier_direct",
        lambda *a: (
            {"text": "Verification required", "structured": True, "content_type": "pdf"},
            "",
            a[0],
        ),
    )
    result = f.fetch_and_extract("https://source.example/policy.pdf")
    assert result["ok"] and result["text"] == "Verification required"


def test_detected_challenge_gets_one_browser_attempt_after_soft_budget(tiers):
    import time

    def direct(*a):
        time.sleep(0.02)
        return {}, "challenge_detected", a[0]

    tiers.setattr(f, "_tier_direct", direct)
    tiers.setattr(f, "_tier_headed", lambda u: ({"html": ARTICLE}, "", u))
    result = f.fetch_and_extract("https://source.example", page_budget=0.001)
    assert result["ok"] and result["tier"] == "headed"


def test_failed_challenge_workflow_exposes_pixels_without_repeating_ladder():
    from dethrottled.workflow import guidance

    result = guidance(
        {
            "quality": "failed",
            "url": "https://source.example",
            "acquisition_attempts": [{"tier": "headed", "outcome": "challenge"}],
        }
    )
    actions = result["next_actions"]
    assert not any(a["tool"] == "fetch" for a in actions)
    assert any(a["tool"] == "drive" and a["arguments"]["screenshot"] == "always" for a in actions)


def test_skipped_headed_tier_is_not_reported_as_attempted(tiers):
    tiers.setattr(f, "_tier_direct", lambda *a: ({}, "http_429", a[0]))
    tiers.setattr(f, "_tier_tls", lambda u: ({}, "tls_http_429", u))
    tiers.setattr(f, "_tier_headed", lambda u: pytest.fail("not a detected challenge"))
    result = f.fetch_and_extract("https://source.example")
    assert result["tier"] == "tls"
    assert [a["tier"] for a in result["acquisition_attempts"]] == ["direct", "tls"]


def test_old_cached_thin_text_is_marked_without_refetch(tiers):
    class Cache:
        def get(self, *a):
            return {
                "ok": True,
                "text": "A real short source announcement.",
                "chars": 33,
                "reason": "thin, best available: direct:thin/33",
                "tier": "direct",
            }

        def put(self, *a, **kw):
            pytest.fail("must not refetch")

    tiers.setattr(f, "_tier_direct", lambda *a: pytest.fail("must use valid cache"))
    result = f.fetch_and_extract("https://source.example", cache=Cache())
    assert result["quality"] == "thin" and result["cached"]
    assert result["acquisition_attempts"] == [{"tier": "cache", "outcome": "hit", "reason": ""}]


def test_renderer_reported_bot_block_can_reach_browser(tiers):
    tiers.setattr(f, "_tier_direct", lambda *a: ({}, "http_406", a[0]))
    tiers.setattr(
        f,
        "_tier_tls",
        lambda u: ({}, "Blocked by anti-bot protection: Structural: minimal_text", u),
    )
    tiers.setattr(f, "_tier_headed", lambda u: ({"html": ARTICLE}, "", u))
    assert f.fetch_and_extract("https://source.example")["tier"] == "headed"


def test_browser_failure_preserves_actionable_reason(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "ok": False,
                "steps": [
                    {"ok": False, "action": "goto", "reason": "navigation_outside_allowed_hosts"}
                ],
            }

    monkeypatch.setenv("DETHROTTLED_BROWSER_SEARCH_URL", "http://browser")
    monkeypatch.setattr(f.requests, "post", lambda *a, **kw: Response())
    payload, reason, _ = f._tier_headed("https://source.example")
    assert not payload and reason == "headed_step_failed:goto:navigation_outside_allowed_hosts"


def test_headed_waiters_keep_their_chance_to_read(monkeypatch):
    import time
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setenv("DETHROTTLED_BROWSER_SEARCH_URL", "http://browser")

    def read(url, backend):
        time.sleep(0.15)
        return {"html": ARTICLE, "browser_recovery": {}}, "", url

    monkeypatch.setattr(f, "_headed_read", read)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(f._tier_headed, ["https://source.example"] * 6))
    assert all(payload.get("html") == ARTICLE and not reason for payload, reason, _ in results)


def test_header_challenge_and_loading_are_polled_separately(monkeypatch):
    calls = []
    replies = iter(
        [
            {
                "ok": True,
                "session": {"restored_from_checkpoint": True},
                "steps": [
                    {
                        "action": "goto",
                        "data": {"status": 403, "challenge_headers": {"cf-mitigated": "challenge"}},
                    },
                    {
                        "action": "html",
                        "data": "<html><body></body></html>",
                        "document_ready_state": "loading",
                    },
                ],
            },
            {
                "ok": True,
                "steps": [
                    {"action": "html", "data": "<html></html>", "document_ready_state": "loading"}
                ],
            },
            {
                "ok": True,
                "steps": [
                    {"action": "html", "data": ARTICLE, "document_ready_state": "interactive"}
                ],
            },
            {"ok": True, "steps": [{"action": "checkpoint", "data": True}]},
        ]
    )

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return next(replies)

    def post(*args, **kw):
        calls.append(kw["json"])
        return Response()

    monkeypatch.setenv("DETHROTTLED_BROWSER_SEARCH_URL", "http://browser")
    monkeypatch.setattr(f.requests, "post", post)
    payload, reason, _ = f._tier_headed("https://source.example")
    assert not reason and payload["html"] == ARTICLE
    recovery = payload["browser_recovery"]
    assert recovery["challenge_polls"] == 1 and recovery["loading_polls"] == 1
    assert recovery["restored_from_checkpoint"]
    assert calls[0]["navigation_wait"] == "commit"


def test_headed_queue_timeout_is_named_without_attempting_navigation(monkeypatch):
    from dethrottled.admission import FairQueue

    queue = FairQueue(capacity=1)
    monkeypatch.setattr(f, "_HEADED_QUEUE", queue)
    monkeypatch.setenv("DETHROTTLED_BROWSER_SEARCH_URL", "http://browser")
    monkeypatch.setenv("DETHROTTLED_HEADED_QUEUE_SECONDS", "0")
    monkeypatch.setattr(f, "_headed_read", lambda *a: pytest.fail("slot not acquired"))
    with queue.slot("other"):
        payload, reason, _ = f._tier_headed("https://source.example")
    assert not payload and reason == "headed_queue_timeout"


@pytest.mark.parametrize(
    "text",
    [
        "We must verify your session before you can proceed. Need help? Contact support.",
        "Show us your human side... We can't tell if you're a human or a bot.",
    ],
)
def test_live_observed_interstitials_are_not_thin_evidence(text):
    assert classify("<html><body>" + text + "</body></html>") == "generic"
    assert not classify("<article>An analysis of the message: " + text + "</article>")


@pytest.mark.parametrize("pending", [True, False])
def test_early_or_clipped_html_never_claims_complete_source(tiers, pending):
    payload = {
        "html": ARTICLE,
        "clipped": not pending,
        "browser_recovery": {"document_ready_state": "loading" if pending else "complete"},
    }
    tiers.setattr(f, "_tier_headed", lambda u: (payload, "", u))
    result = f.fetch_and_extract("https://source.example")
    assert result["ok"] and result["extraction"]["partial"]
    assert result["truncated"]
    reason = "browser_document_loading" if pending else "html_capture_limit"
    assert reason in result["warnings"]


@pytest.mark.parametrize("allowed", [True, False])
def test_partial_browser_snapshot_has_a_justified_followup(allowed):
    from dethrottled.workflow import guidance

    result = guidance(
        {
            "url": "https://source.example",
            "quality": "ok",
            "extraction": {"partial": True, "partial_reason": "browser_document_loading"},
        },
        rendered_allowed=allowed,
    )
    drives = [a for a in result["next_actions"] if a["tool"] == "drive"]
    assert bool(drives) is allowed
    if allowed:
        assert drives[0]["arguments"]["steps"][0]["action"] == "text"
        assert not result["source_complete"]


def test_script_only_shell_reaches_browser_without_an_agent_knowing_the_flag(tiers):
    tiers.setattr(
        f,
        "_tier_direct",
        lambda *a: (
            {
                "html": (
                    '<html><body><div id="root"></div><script src="/app.js"></script></body></html>'
                )
            },
            "",
            a[0],
        ),
    )
    tiers.setattr(f, "_tier_tls", lambda u: ({}, "empty", u))
    tiers.setattr(f, "_tier_headed", lambda u: ({"html": ARTICLE}, "", u))
    result = f.fetch_and_extract("https://source.example")
    assert result["ok"] and result["tier"] == "headed"


def test_complete_visible_text_preserves_html_cap_without_repeating_recovery(tiers):
    payload = {
        "html": ARTICLE, "clipped": True,
        "text": "Retained visible comment evidence. " * 60,
        "content_type": "html",
        "extraction": {"method": "browser_visible_text", "partial": False,
                       "html_capture_partial": True},
        "browser_recovery": {"document_ready_state": "interactive"},
    }
    tiers.setattr(f, "_tier_headed", lambda u: (payload, "", u))
    result = f.fetch_and_extract("https://source.example")
    assert result["ok"] and not result["extraction"]["partial"]
    assert result["extraction"]["html_capture_partial"]
    assert "html_capture_limit" not in result.get("warnings", [])
    assert result["content_assessment"]["completeness"] == "unknown"
