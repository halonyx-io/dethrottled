"""The render tier after Crawl4AI (1.9.0): whole-page text, 401/403 escalation, old names."""
import pytest
from test_fetch_internals import ARTICLE

from dethrottled import extract
from dethrottled import fetch as f
from dethrottled import waymarks as w


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(f, "_throttle", lambda domain: None)
    monkeypatch.setattr(f, "RENDER_URL", "http://renderer.invalid")
    monkeypatch.setattr(f, "TLS_HEDGE_SECONDS", 0)
    f._tier_rest.clear()


def test_rendered_text_keeps_controls_and_the_whole_page():
    html = ("<html><body><nav>Docs Blog</nav><main><p>An article paragraph.</p></main>"
            "<button>GET /pet/findByStatus Finds pets by status</button>"
            "<script>var hidden = 'not text';</script></body></html>")
    text = extract.rendered_text(html)
    assert "Finds pets by status" in text      # Swagger keeps operations in buttons
    assert "An article paragraph." in text and "Docs Blog" in text
    assert "not text" not in text
    assert extract.rendered_text("") == ""
    # Crawl4AI's markdown split these words ("_ser_ ializing"); 1.8 unwrapped
    # the tags first. Whole-page text keeps them whole by itself.
    assert extract.rendered_text("<p>for <em>ser</em>ializing, <b>very</b> clear</p>") == (
        "for serializing, very clear")


def test_a_long_rendered_article_keeps_its_first_and_last_markers():
    page = ('<html><head><base href="https://example.org/papers/"></head><body><article>'
            "<h1>Complete evidence</h1><p>First marker quartz-782</p>"
            + "<p>Substantial evidence about browsers and content.</p>" * 40
            + '<a href="appendix">Appendix</a><p>Final marker jade-382</p></article></body></html>')
    result, reason, _ = f._render_payload({"html": page}, "https://example.org")
    assert not reason and "quartz-782" in result["text"] and "jade-382" in result["text"]


def test_a_blank_render_is_not_content():
    result, reason, _ = f._render_payload(
        {"html": "<html><body><script>1+1</script></body></html>"}, "https://example.org")
    assert result == {} and reason == "render_empty"


def test_rendered_payload_uses_page_text_not_a_supplied_markdown():
    page = "<html><body><h1>Title</h1><p>" + "Rendered evidence. " * 30 + "</p></body></html>"
    result, reason, _ = f._render_payload({"html": page, "markdown": "stale " * 100}, "https://x.example")
    assert not reason and "Rendered evidence." in result["text"] and "stale" not in result["text"]


@pytest.mark.parametrize("status", [401, 403])
def test_a_render_refusal_escalates_to_the_headed_browser(monkeypatch, status):
    monkeypatch.setenv("DETHROTTLED_BROWSER_SEARCH_URL", "http://browser.invalid")
    order = []

    def step(name, out):
        def run(url, *a, **k):
            order.append(name)
            return out(url)
        return run
    monkeypatch.setattr(f, "_tier_direct", step("direct", lambda u: ({}, "http_404", u)))
    monkeypatch.setattr(f, "_tier_tls", step("tls", lambda u: ({}, "tls_http_404", u)))
    monkeypatch.setattr(f, "_tier_render",
                        step("render", lambda u: ({}, "render_target_http_%d" % status, u)))
    monkeypatch.setattr(f, "_tier_headed", step("headed", lambda u: ({"html": ARTICLE}, "", u)))
    result = f.fetch_and_extract("https://markets.example.com/live", max_chars=5000)
    assert order[-2:] == ["render", "headed"] and result["tier"].startswith("headed")


def test_a_render_404_does_not_wake_the_headed_browser(monkeypatch):
    monkeypatch.setenv("DETHROTTLED_BROWSER_SEARCH_URL", "http://browser.invalid")
    monkeypatch.setattr(f, "_tier_direct", lambda u, *a, **k: ({}, "http_404", u))
    monkeypatch.setattr(f, "_tier_tls", lambda u: ({}, "tls_http_404", u))
    monkeypatch.setattr(f, "_tier_render", lambda u: ({}, "render_target_http_404", u))
    monkeypatch.setattr(f, "_tier_headed", lambda u: pytest.fail("a missing page needs no browser"))
    assert not f.fetch_and_extract("https://gone.example.com/x", max_chars=5000)["ok"]


def test_old_setting_names_still_work(monkeypatch):
    monkeypatch.delenv("DETHROTTLED_RENDER_TIMEOUT", raising=False)
    monkeypatch.setenv("DETHROTTLED_CRAWL4AI_TIMEOUT", "40")
    assert f._setting("DETHROTTLED_RENDER_TIMEOUT", "DETHROTTLED_CRAWL4AI_TIMEOUT", "25") == "40"
    monkeypatch.setenv("DETHROTTLED_RENDER_TIMEOUT", "30")
    assert f._setting("DETHROTTLED_RENDER_TIMEOUT", "DETHROTTLED_CRAWL4AI_TIMEOUT", "25") == "30"


def test_waymarks_saved_before_190_are_read_under_the_new_step_name():
    state = {"k": {"tiers": {"crawl4ai": {"streak": 3}}, "won": {"crawl4ai": 1.0, "tls": 2.0}}}
    w._rename_legacy_steps(state)
    assert state["k"]["tiers"] == {"render": {"streak": 3}}
    assert state["k"]["won"] == {"render": 1.0, "tls": 2.0}
    assert "render" in w.LADDER and "crawl4ai" not in w.LADDER


def test_render_is_the_restable_tier():
    assert "render" in f._RESTABLE_TIERS
