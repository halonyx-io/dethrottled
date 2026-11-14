"""Prototype boundaries and deterministic extraction; run inside its image."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import dnb_service as dnb
import pytest
from fastapi import HTTPException
from pydantic import ValidationError


def body(**params):
    return dnb.CrawlRequest(
        urls=["https://example.org/"], crawler_config={"type": "CrawlerRunConfig", "params": params}
    )


@pytest.mark.parametrize(
    "params",
    [
        {"js_code": "alert(1)"},
        {"page_timeout": True},
        {"page_timeout": 60000},
        {"delay_before_return_html": float("nan")},
        {"wait_for": "js:alert(1)"},
        {"cache_mode": "enabled"},
        {"check_robots_txt": True},
    ],
)
def test_unsupported_or_unbounded_options_fail(params):
    with pytest.raises(HTTPException) as error:
        dnb.options(body(**params))
    assert error.value.status_code == 422


def test_batch_is_deliberately_not_supported():
    with pytest.raises(ValidationError):
        dnb.CrawlRequest(urls=["https://a.test", "https://b.test"])


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://u:p@example.org",
        "http://example.org:999999",
        "javascript:alert(1)",
    ],
)
def test_url_boundary(url):
    assert not dnb.valid_url(url)


def test_crawl_uses_upstream_extraction_and_relative_link_resolution():
    text = '<html><head><base href="https://example.org/papers/"></head><body><article>'
    text += "<h1>Complete evidence</h1><p>First marker quartz-782</p>"
    text += "<p>Substantial evidence about browsers and content.</p>" * 40
    text += '<a href="appendix">Appendix</a><p>Final marker jade-382</p></article></body></html>'
    result = dnb.extract("https://example.org", text)
    md = result["markdown"]["raw_markdown"]
    assert result["success"] and "quartz-782" in md and "jade-382" in md
    assert "https://example.org/papers/appendix" in md


def test_nonpublic_target_rejected_before_context_creation(monkeypatch):
    monkeypatch.setattr(dnb, "ALLOW_INTERNAL", False)
    monkeypatch.setattr(dnb.browser, "_public_network_target", AsyncMock(return_value=False))
    create = AsyncMock()
    monkeypatch.setattr(dnb, "create_state", create)
    with pytest.raises(HTTPException) as error:
        asyncio.run(dnb.crawl(body()))
    assert error.value.status_code == 403
    create.assert_not_awaited()


def test_failed_navigation_closes_context_and_releases_admission(monkeypatch):
    monkeypatch.setattr(dnb, "ALLOW_INTERNAL", True)
    semaphore = asyncio.Semaphore(1)
    monkeypatch.setattr(dnb, "RENDER_SLOTS", semaphore)
    page = SimpleNamespace(on=lambda *args: None)
    monkeypatch.setattr(
        dnb.browser, "_navigate", AsyncMock(side_effect=TimeoutError("navigation timeout"))
    )
    context = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(
        dnb, "create_state", AsyncMock(return_value={"page": page, "context": context})
    )
    dnb.app.state.browser = object()
    with pytest.raises(HTTPException) as error:
        asyncio.run(dnb.crawl(body()))
    assert error.value.status_code == 504
    assert error.value.detail["code"] == "browser_timeout"
    assert error.value.detail["retryable"] is False
    context.close.assert_awaited_once()
    assert semaphore._value == 1


def test_blank_render_is_not_usable_content():
    result = dnb.extract("https://example.org", "<html><body><script>1+1</script></body></html>")
    assert not result["success"]


def test_unknown_browser_config_is_not_silently_ignored():
    request = dnb.CrawlRequest(
        urls=["https://example.org"],
        browser_config={"type": "BrowserConfig", "params": {"user_agent": "unverified"}},
    )
    with pytest.raises(HTTPException):
        dnb.options(request)


@pytest.mark.parametrize("params", [
    {"url": "http://["},
    {"steps": [{"action": "goto", "url": "http://["}]},
])
def test_malformed_drive_url_leaves_no_admission_or_journal_entry(monkeypatch, params):
    monkeypatch.setattr(dnb, "DRIVE_INFLIGHT", 0)
    monkeypatch.setattr(dnb, "principal", lambda _: {"sub": "test-owner"})
    journal = SimpleNamespace(begin=lambda *_: pytest.fail("invalid URL entered journal"))
    monkeypatch.setattr(dnb, "OPERATION_STORE", journal)
    monkeypatch.setattr(dnb, "SESSION_OWNERS", SimpleNamespace(claim=lambda *_: None))
    body = dnb.browser.DriveRequest(session="fixture", operation_id="test", **params)
    with pytest.raises(HTTPException) as error:
        asyncio.run(dnb.bounded_drive(body, None))
    assert error.value.status_code == 422
    assert dnb.DRIVE_INFLIGHT == 0


class _ScrollPage:
    def __init__(self, states):
        self.states, self.scrolls = iter(states), 0

    async def evaluate(self, script):
        if script.startswith("window."):
            self.scrolls += 1
            return None
        return next(self.states)


def _state(height, text=1000, share=0.0):
    return {"height": height, "text": text, "article_share": share}


def test_infinite_scroll_settles_until_the_page_stops_growing(monkeypatch):
    import time as _time
    monkeypatch.setattr(dnb, "SCROLL_PAUSE", 0)
    page = _ScrollPage([_state(1000), _state(2000, 2000), _state(3000, 3000), _state(3000, 3000)])
    asyncio.run(dnb._settle_infinite_scroll(page, _time.monotonic() + 60))
    assert page.scrolls == 3   # grew, grew, stopped


def test_infinite_scroll_respects_the_render_deadline(monkeypatch):
    import time as _time
    page = _ScrollPage([_state(1000)] * 5)
    asyncio.run(dnb._settle_infinite_scroll(page, _time.monotonic()))
    assert page.scrolls == 0


def test_single_article_pages_are_not_scrolled(monkeypatch):
    import time as _time
    monkeypatch.setattr(dnb, "SCROLL_PAUSE", 0)
    page = _ScrollPage([_state(5000, 40000, 0.9)] + [_state(9000, 50000)] * 5)
    asyncio.run(dnb._settle_infinite_scroll(page, _time.monotonic() + 60))
    assert page.scrolls == 0


def test_endless_feeds_stop_at_the_added_text_cap(monkeypatch):
    import time as _time
    monkeypatch.setattr(dnb, "SCROLL_PAUSE", 0)
    monkeypatch.setattr(dnb, "SCROLL_MAX_ADDED_CHARS", 1000)
    page = _ScrollPage([_state(1000 * i, 600 * i) for i in range(1, 20)])
    asyncio.run(dnb._settle_infinite_scroll(page, _time.monotonic() + 60))
    assert page.scrolls == 2   # 600 -> 1200 -> 1800 chars: cap of 1000 added reached


def test_network_settle_is_bounded_and_tolerates_timeouts(monkeypatch):
    import time as _time
    waited = []

    class Page:
        async def wait_for_load_state(self, state, timeout):
            waited.append((state, timeout))
            raise TimeoutError("still busy")

    asyncio.run(dnb._settle_network(Page(), _time.monotonic() + 60))
    assert waited == [("networkidle", dnb.NETWORK_SETTLE_SECONDS * 1000)]
    waited.clear()
    asyncio.run(dnb._settle_network(Page(), _time.monotonic()))
    assert waited == []


class _SettlePage:
    """networkidle never arrives; visible text follows a scripted timeline."""

    def __init__(self, lengths):
        self.lengths, self.polls = list(lengths), 0

    async def wait_for_load_state(self, state, timeout):
        await asyncio.sleep(timeout / 1000)
        raise TimeoutError("analytics never go quiet")

    async def evaluate(self, script):
        self.polls += 1
        return self.lengths[min(self.polls - 1, len(self.lengths) - 1)]


def test_settle_ends_once_substantial_text_stops_changing(monkeypatch):
    import time as _time

    import service
    monkeypatch.setattr(service, "SETTLE_POLL_SECONDS", 0.01)
    monkeypatch.setattr(service, "SETTLE_STABLE_SECONDS", 0.03)
    page = _SettlePage([0, 0, 1706, 1887] + [1887] * 200)
    started = _time.monotonic()
    assert asyncio.run(service.settle_quiet(page, 3)) == "text_stable"
    assert _time.monotonic() - started < 1


def test_settle_keeps_waiting_while_text_is_below_the_floor(monkeypatch):
    import service
    monkeypatch.setattr(service, "SETTLE_POLL_SECONDS", 0.01)
    monkeypatch.setattr(service, "SETTLE_STABLE_SECONDS", 0.03)
    page = _SettlePage([106] * 1000)                 # a loading shell: stable but tiny
    assert asyncio.run(service.settle_quiet(page, 0.3)) == "budget"
    assert page.polls > 5


def test_settle_reports_network_idle_when_it_arrives_first():
    import service

    class Quiet(_SettlePage):
        async def wait_for_load_state(self, state, timeout):
            return None

    assert asyncio.run(service.settle_quiet(Quiet([0]), 3)) == "network_idle"


def test_scrolling_stops_when_a_round_adds_height_but_no_text(monkeypatch):
    import time as _time
    monkeypatch.setattr(dnb, "SCROLL_PAUSE", 0)
    page = _ScrollPage([_state(1000, 2000), _state(3000, 2050), _state(5000, 9000)])
    asyncio.run(dnb._settle_infinite_scroll(page, _time.monotonic() + 60))
    assert page.scrolls == 1      # lazy images grew the page, not the text


def test_intraword_emphasis_is_unwrapped_but_word_emphasis_kept():
    import html_extract
    fix = html_extract._unwrap_intraword_emphasis
    assert fix("<p>for <em>ser</em>ializing and <em>de</em>serializing</p>") == (
        "<p>for serializing and deserializing</p>")
    assert fix('<p>a <em class="x">un</em>wrap</p>') == "<p>a unwrap</p>"
    kept = "<p>This is <em>very</em> important, <strong>really</strong>.</p>"
    assert fix(kept) == kept


# ── automatic read sessions do not keep pages open ──────────────────────────
# 14 Nov: six idle shop pages from automatic reads held 0.5-0.6 GB each for up
# to 30 minutes, the worker reached 94% of its limit and refused renders.

def _session(service, idle, locked=False):
    lock = asyncio.Lock()
    closed = []
    context = SimpleNamespace(close=AsyncMock(side_effect=lambda: closed.append(True)))
    state = {"context": context, "lock": lock, "last_used": time.monotonic() - idle}
    return state, closed, lock if locked else None


def test_idle_read_sessions_close_early_and_named_ones_keep_their_ttl(monkeypatch):
    import service
    monkeypatch.setattr(service, "READ_SESSION_IDLE", 300)
    monkeypatch.setattr(service, "DRIVE_SESSION_TTL", 1800)
    read, read_closed, _ = _session(service, idle=400)
    fresh, fresh_closed, _ = _session(service, idle=10)
    named, named_closed, _ = _session(service, idle=600)
    monkeypatch.setattr(service, "DRIVE_SESSIONS", {
        "auto-reader-" + "a" * 32: read, "auto-reader-" + "b" * 32: fresh, "workflow": named})

    closed = asyncio.run(service._close_idle_sessions(
        lambda sid, idle: idle > service._session_idle_limit(sid)))

    assert closed == 1 and read_closed and not fresh_closed and not named_closed
    assert set(service.DRIVE_SESSIONS) == {"auto-reader-" + "b" * 32, "workflow"}


def test_memory_reclaim_takes_only_idle_unlocked_read_sessions(monkeypatch):
    import service
    idle, idle_closed, _ = _session(service, idle=30)
    busy, busy_closed, busy_lock = _session(service, idle=30, locked=True)
    named, named_closed, _ = _session(service, idle=3000)
    monkeypatch.setattr(service, "DRIVE_SESSIONS", {
        "auto-reader-" + "a" * 32: idle, "auto-reader-" + "b" * 32: busy, "workflow": named})

    async def run():
        await busy_lock.acquire()
        return await service.reclaim_idle_read_sessions()

    assert asyncio.run(run()) == 1
    assert idle_closed and not busy_closed and not named_closed


def test_render_admission_reclaims_before_refusing(monkeypatch):
    pressure = iter([True, False])
    monkeypatch.setattr(dnb, "memory_pressure", lambda: next(pressure))
    monkeypatch.setattr(dnb.browser, "reclaim_idle_read_sessions", AsyncMock(return_value=2))
    assert asyncio.run(dnb.reclaim_for_render()) is True
    assert dnb.COUNTS["reclaimed_read_sessions"] >= 2


def test_render_admission_refuses_when_nothing_can_be_reclaimed(monkeypatch):
    monkeypatch.setattr(dnb, "memory_pressure", lambda: True)
    monkeypatch.setattr(dnb.browser, "reclaim_idle_read_sessions", AsyncMock(return_value=0))
    assert asyncio.run(dnb.reclaim_for_render()) is False


def test_parking_is_a_separate_flag_from_closing():
    import service
    request = service.DriveRequest(session="auto-reader-" + "a" * 32, park_session=True,
                                   steps=[{"action": "checkpoint"}])
    assert request.park_session and not request.close_session
