"""Tier cooldown: rest what is shared, never rest what is per-host.

This file exists because getting it wrong was measured and expensive. When the
cooldown was applied to every tier, a single 403 from one site rested the
`direct` tier globally: every later page in the run skipped it, the renderer
was handed 30 pages it had no business rendering, and end-to-end extraction
fell from 87% to 67%.

The distinction is the whole safety of the mechanism, so it is pinned here.
"""
import pytest

from dethrottled import fetch as f


@pytest.fixture(autouse=True)
def clean():
    """Cooldown state is process-global; tests must not leak into each other."""
    f._tier_rest.clear()
    yield
    f._tier_rest.clear()


# ── the distinction ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("tier", ["direct", "tls"])
def test_per_host_tiers_are_never_rested(tier):
    """`direct` and `tls` are not services, they are "make an HTTP request".
    A refusal from one host says nothing about the next one."""
    for _ in range(5):
        f.tier_refused(tier, "http_403")
    assert f.tier_resting(tier) is False
    assert tier not in f.tier_rest_state()


@pytest.mark.parametrize("tier", ["crawl4ai"])
def test_shared_service_tiers_do_rest(tier):
    """A shared renderer's refusal warrants a cooldown before another request."""
    f.tier_refused(tier, "%s_http_429" % tier)
    assert f.tier_resting(tier) is True
    assert tier in f.tier_rest_state()


# ── the mechanism ────────────────────────────────────────────────────────────

def test_backoff_doubles_with_consecutive_refusals():
    f.tier_refused("crawl4ai", "crawl4ai_http_429")
    first = f.tier_rest_state()["crawl4ai"]["resting_for"]
    f.tier_refused("crawl4ai", "crawl4ai_http_429")
    second = f.tier_rest_state()["crawl4ai"]["resting_for"]
    assert second > first * 1.5


def test_backoff_is_capped():
    """A permanently dead tier settles at the cap rather than growing without
    bound and effectively never being retried again."""
    for _ in range(20):
        f.tier_refused("crawl4ai", "crawl4ai_http_429")
    assert f.tier_rest_state()["crawl4ai"]["resting_for"] <= f.TIER_COOLDOWN_MAX


def test_success_clears_the_record_entirely():
    """A brief wobble must cost one cooldown, not a permanent handicap."""
    f.tier_refused("crawl4ai", "crawl4ai_http_429")
    f.tier_answered("crawl4ai")
    assert f.tier_resting("crawl4ai") is False
    f.tier_refused("crawl4ai", "crawl4ai_http_429")
    # Back to a first-strike cooldown, not a third-strike one.
    assert f.tier_rest_state()["crawl4ai"]["strikes"] == 1


def test_rest_state_only_reports_what_is_still_resting():
    f.tier_refused("crawl4ai", "crawl4ai_http_429")
    f._tier_rest["crawl4ai"]["until"] = 0        # expire it
    assert "crawl4ai" not in f.tier_rest_state()


# ── what counts as a refusal ─────────────────────────────────────────────────

@pytest.mark.parametrize("reason", [
    "crawl4ai_http_429", "crawl4ai_http_403", "crawl4ai_http_503",
    "crawl4ai_Timeout", "crawl4ai_ConnectionError",
])
def test_refusals_are_recognised(reason):
    assert f._is_refusal(reason) is True


@pytest.mark.parametrize("reason", [
    "", "crawl4ai_http_404", "crawl4ai_http_500", "crawl4ai_empty",
    "robots_disallow", "pdf_no_text_layer",
])
def test_page_level_failures_are_not_refusals(reason):
    """A 404 is about the page. Resting a tier because one URL does not exist
    would take the tier down for reasons that have nothing to do with it."""
    assert f._is_refusal(reason) is False


def test_a_target_sites_failure_does_not_rest_the_renderer():
    """One site's 403 or slow page says nothing about the next site."""
    from dethrottled import fetch as f
    for reason in ("crawl4ai_target_http_403", "crawl4ai_target_http_429",
                   "crawl4ai_Page.goto: Timeout 20000ms exceeded.", "crawl4ai_http_504",
                   "crawl4ai_http_403"):
        assert f._service_refusal("crawl4ai", reason) is False, reason
    for reason in ("crawl4ai_http_429", "crawl4ai_http_503", "crawl4ai_ConnectionError",
                   "crawl4ai_ReadTimeout"):
        assert f._service_refusal("crawl4ai", reason) is True, reason
    assert f._service_refusal("direct", "http_429") is True


def test_dnb_target_status_is_named_as_the_targets(monkeypatch):
    from dethrottled import fetch as f

    class Response:
        status_code = 200

        def json(self):
            return {"results": [{"success": False, "error_message": "http_403"}]}

    monkeypatch.setattr(f.requests, "post", lambda *a, **k: Response())
    monkeypatch.setattr(f, "CRAWL4AI_URL", "http://dnb")
    monkeypatch.setenv("DETHROTTLED_DNB", "0")
    assert f._crawl4ai_via_crawl("https://example.org/")[1] == "crawl4ai_target_http_403"
