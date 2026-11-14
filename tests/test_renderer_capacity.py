"""The renderer being busy is ours to report, briefly, and never to cache.

On 14 Nov two DNB admission refusals (memory pressure) rested rendering for
every site for 10 minutes, JavaScript pages came back as shells with no
warning, and those shells were cached. These tests pin the replacement rules:
a named, retryable admission refusal gets one retry and then a short pause
without a strike; any read that needed the renderer and could not have it says
so and is not cached.
"""
from types import MappingProxyType

import pytest
from test_fetch_internals import ARTICLE, SHELL, tier

from dethrottled import fetch as f


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(f, "_throttle", lambda domain: None)
    monkeypatch.setattr(f, "CRAWL4AI_URL", "http://renderer.invalid")
    monkeypatch.setattr(f.time, "sleep", lambda seconds: None)
    monkeypatch.setenv("DETHROTTLED_DNB", "0")
    f._tier_rest.clear()
    yield
    f._tier_rest.clear()


class Refused:
    status_code = 503
    headers = MappingProxyType({"Retry-After": "1"})

    def __init__(self, code="render_memory_pressure"):
        self.code = code

    def json(self):
        return {"detail": {"code": self.code, "retryable": True, "retry_after_seconds": 1}}


class Rendered:
    status_code = 200
    headers = MappingProxyType({})

    def json(self):
        return {"results": [{"success": True, "html": ARTICLE, "status_code": 200}]}


def replies(monkeypatch, *responses):
    queue = list(responses)
    calls = []

    def post(*args, **kwargs):
        calls.append(args[0])
        return queue.pop(0)
    monkeypatch.setattr(f.requests, "post", post)
    return calls


def test_a_busy_renderer_is_retried_once_and_then_works(monkeypatch):
    calls = replies(monkeypatch, Refused(), Rendered())
    payload, reason, _ = f._crawl4ai_via_crawl("https://example.org/")
    assert reason == "" and payload
    assert len(calls) == 2


def test_a_still_busy_renderer_is_named_busy_not_down(monkeypatch):
    replies(monkeypatch, Refused(), Refused("render_queue_full"))
    _, reason, _ = f._crawl4ai_via_crawl("https://example.org/")
    assert reason == "crawl4ai_busy:render_queue_full"
    assert f._service_refusal("crawl4ai", reason) is False


def test_an_unnamed_503_still_counts_as_the_service_refusing(monkeypatch):
    class Plain:
        status_code = 503
        headers = MappingProxyType({})

        def json(self):
            raise ValueError("not json")
    calls = replies(monkeypatch, Plain())
    _, reason, _ = f._crawl4ai_via_crawl("https://example.org/")
    assert reason == "crawl4ai_http_503" and len(calls) == 1
    assert f._service_refusal("crawl4ai", reason) is True


def test_busy_pauses_briefly_without_a_strike():
    f.tier_busy("crawl4ai", "crawl4ai_busy:render_memory_pressure")
    state = f.tier_rest_state()["crawl4ai"]
    assert state["strikes"] == 0
    assert 0 < state["resting_for"] <= f.RENDER_BUSY_REST
    # A real refusal afterwards still starts the normal cooldown at one strike.
    f.tier_refused("crawl4ai", "crawl4ai_ConnectionError")
    assert f.tier_rest_state()["crawl4ai"]["strikes"] == 1


def test_a_read_that_needed_the_busy_renderer_warns_and_is_not_cached(monkeypatch):
    monkeypatch.setattr(f, "_tier_direct", tier(html=SHELL))
    monkeypatch.setattr(f, "_tier_tls", tier(html=SHELL))
    busy = tier(reason="crawl4ai_busy:render_memory_pressure")
    monkeypatch.setattr(f, "_tier_crawl4ai", busy)
    first = f.fetch_and_extract("https://example.com/app", max_chars=5000)
    warning = " ".join(first.get("warnings", []))
    assert "renderer_unavailable:render_memory_pressure" in warning
    assert f.tier_rest_state()["crawl4ai"]["strikes"] == 0

    # Once the renderer is back, the same URL is rendered rather than served
    # from a cached shell.
    f._tier_rest.clear()
    monkeypatch.setattr(f, "_tier_crawl4ai", tier(html=ARTICLE))
    second = f.fetch_and_extract("https://example.com/app", max_chars=5000)
    assert second["ok"] and second["tier"] == "crawl4ai"
    assert not second.get("cached")
    assert not any("renderer_unavailable" in w for w in second.get("warnings", []))


def test_a_skipped_resting_renderer_is_reported(monkeypatch):
    f.tier_refused("crawl4ai", "crawl4ai_ConnectionError")
    monkeypatch.setattr(f, "_tier_direct", tier(html=SHELL))
    monkeypatch.setattr(f, "_tier_tls", tier(html=SHELL))
    monkeypatch.setattr(f, "_tier_crawl4ai",
                        lambda *a, **k: pytest.fail("resting renderer was asked"))
    result = f.fetch_and_extract("https://example.com/resting", max_chars=5000)
    assert any(w.startswith("renderer_unavailable:resting:crawl4ai_ConnectionError")
               for w in result.get("warnings", []))
    assert result.get("renderer_unavailable")


def test_a_page_read_without_the_renderer_carries_no_warning(monkeypatch):
    """A rested renderer must not taint pages that never needed it."""
    f.tier_refused("crawl4ai", "crawl4ai_ConnectionError")
    monkeypatch.setattr(f, "_tier_direct", tier(html=ARTICLE))
    result = f.fetch_and_extract("https://example.com/static", max_chars=5000)
    assert result["tier"] == "direct"
    assert not any("renderer_unavailable" in w for w in result.get("warnings", []))
