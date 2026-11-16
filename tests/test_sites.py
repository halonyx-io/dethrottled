"""Site routes (sites.py), block recognition and the www twin for browser reads.

Measured on live 1.8.10, 16 Nov 2026; see ~/web-bench/results/site-routes.
"""
import json
from types import SimpleNamespace

import pytest
from test_fetch_internals import ARTICLE, tier

from dethrottled import challenges, sites
from dethrottled import extract as extract_module
from dethrottled import fetch as f
from dethrottled.urls import host_family


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(f, "_throttle", lambda domain: None)
    monkeypatch.setattr(f, "CRAWL4AI_URL", "http://renderer.invalid")
    monkeypatch.setattr(f, "TLS_HEDGE_SECONDS", 0)
    monkeypatch.setattr(sites, "_se_backoff_until", 0.0)
    monkeypatch.setattr(sites, "_gh_api_until", 0.0)
    f._tier_rest.clear()


def reply(status=200, body=None, text=None, headers=None):
    return SimpleNamespace(status_code=status, headers=headers or {},
                           text=text if text is not None else json.dumps(body or {}),
                           json=lambda: body or {})


# ── pins ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url, step", [
    ("https://www.booking.com/hotel/gb/x.html", "headed"),
    ("https://openai.com/index/x/", "tls"),
    ("https://learn.microsoft.com/en-us/x", "crawl4ai"),
    ("https://www.microsoft.com/en-us/x", "tls"),
    ("https://en.wikipedia.org/wiki/X", None),
])
def test_pins_match_the_most_specific_host(url, step):
    assert sites.pinned_step(url) == step


def test_a_pinned_step_goes_first_and_the_ladder_still_follows(monkeypatch):
    order = []

    def step(name, payload):
        def run(url, *a, **k):
            order.append(name)
            return payload, "", url
        return run
    monkeypatch.setattr(f, "_tier_direct", step("direct", {"html": ARTICLE}))
    monkeypatch.setattr(f, "_tier_tls", step("tls", {}))
    result = f.fetch_and_extract("https://openai.com/index/a-post/", max_chars=5000)
    assert order == ["tls", "direct"] and result["tier"] == "direct"


# ── readers ────────────────────────────────────────────────────────────────

def test_stackexchange_reads_question_and_answers(monkeypatch):
    def get(url, params=None, **kwargs):
        if url.endswith("/questions/11227809"):
            return reply(body={"items": [{"title": "Why is a sorted array faster?",
                                          "body": "<p>Branch <code>prediction</code>?</p>",
                                          "score": 27000, "tags": ["java", "c++"],
                                          "creation_date": 1340805096, "answer_count": 25,
                                          "owner": {"display_name": "GManNickG"},
                                          "link": "https://stackoverflow.com/q/11227809"}],
                                  "quota_remaining": 298})
        return reply(body={"items": [{"body": "<p>You are a victim of branch prediction.</p>"
                                              "<pre><code>if (x)\n  y();</code></pre>",
                                      "score": 35000, "is_accepted": True,
                                      "owner": {"display_name": "Mysticial"},
                                      "creation_date": 1340805400}], "quota_remaining": 297})
    monkeypatch.setattr(sites.requests, "get", get)
    payload = sites.read_stackexchange(
        "https://stackoverflow.com/questions/11227809/why-is-processing-a-sorted-array-faster")
    text = payload["text"]
    assert payload["title"] == "Why is a sorted array faster?"
    assert "victim of branch prediction" in text and "if (x)\n  y();" in text
    assert "(accepted)" in text and "CC BY-SA" in text and "1 of 25 answers" in text
    assert payload["page_metadata"]["published"] == "2012-06-27"


def test_stackexchange_backoff_hands_over_to_the_ladder(monkeypatch):
    monkeypatch.setattr(sites.requests, "get", lambda url, params=None, **k: reply(
        400, body={"error_id": 502, "error_name": "throttle_violation"}))
    name, run = sites.reader_for("https://superuser.com/questions/1/x")
    payload, reason, _ = run()
    assert name == "stackexchange" and payload == {}
    assert reason == "api_stackexchange_unavailable:stackexchange_throttle_violation"


def test_unix_stackexchange_and_answer_links_are_recognised():
    unix = sites.reader_for("https://unix.stackexchange.com/questions/635016/x")
    assert unix[0] == "stackexchange"
    assert sites.reader_for("https://stackoverflow.com/a/11227902")[0] == "stackexchange"
    assert sites.reader_for("https://stackoverflow.com/users/1/x") is None


def test_pubmed_reads_the_abstract(monkeypatch):
    def get(url, params=None, **kwargs):
        if "efetch" in url:
            return reply(text="1. Methods Mol Biol. 2019. Molegro Virtual Docker for Docking. "
                              "Abstract text that is long enough to count as the abstract.")
        return reply(body={"result": {"31452104": {"title": "Molegro Virtual Docker",
                                                   "sortpubdate": "2019/09/26 00:00"}}})
    monkeypatch.setattr(sites.requests, "get", get)
    monkeypatch.setattr(sites, "_ncbi_next", 0.0)
    payload = sites.read_pubmed("https://pubmed.ncbi.nlm.nih.gov/31452104/")
    assert payload["title"] == "Molegro Virtual Docker"
    assert payload["page_metadata"]["published"] == "2019-09-26"


def test_github_repo_reads_readme_and_survives_api_quota(monkeypatch):
    def get(url, **kwargs):
        if url.startswith("https://api.github.com"):
            return reply(403, headers={"X-RateLimit-Reset": "9999999999"})
        if url.endswith("/HEAD/README.md"):
            return reply(text="# Requests\nHTTP for Humans.")
        return reply(404, text="")
    monkeypatch.setattr(sites.requests, "get", get)
    payload = sites.read_github("https://github.com/psf/requests")
    assert "HTTP for Humans" in payload["text"]
    assert payload["warnings"] == ["github_api_quota_exhausted; repository details omitted"]


def test_github_pages_that_are_not_repos_or_files_use_the_page():
    assert sites.reader_for("https://github.com/psf/requests/issues/1") is None
    assert sites.reader_for("https://github.com/features/actions") is None
    assert sites.reader_for("https://github.com/psf/requests/blob/main/src/requests/api.py")


def test_paper_metadata_is_marked_partial(monkeypatch):
    monkeypatch.setattr(sites.requests, "get", lambda url, params=None, **k: reply(body={
        "message": {"items": [{"title": ["Deep learning in neural networks"],
                               "author": [{"given": "J", "family": "Schmidhuber"}],
                               "issued": {"date-parts": [[2015, 1, 1]]},
                               "container-title": ["Neural Networks"], "DOI": "10.1016/x",
                               "abstract": "<jats:p>An overview.</jats:p>"}]}}))
    payload = sites.read_sciencedirect(
        "https://www.sciencedirect.com/science/article/pii/S0893608014002135")
    assert payload["content_status"] == "partial" and payload["source_partial"]
    assert payload["extraction"]["partial"] and "An overview." in payload["text"]


def test_a_failing_reader_falls_back_to_the_ladder(monkeypatch):
    monkeypatch.setattr(sites.requests, "get", lambda *a, **k: reply(500, body={}))
    monkeypatch.setattr(f, "_tier_direct", tier(html=ARTICLE))
    result = f.fetch_and_extract("https://www.npmjs.com/package/react", max_chars=5000)
    tiers = [a["tier"] for a in result["acquisition_attempts"]]
    assert result["ok"] and tiers[0] == "api:npm" and "direct" in tiers


def test_a_reader_result_is_used_with_its_title(monkeypatch):
    monkeypatch.setattr(sites, "read_npm", lambda url: sites._result(
        "# react 19\n" + "A JavaScript library for building user interfaces. " * 10,
        title="react 19", source="registry.npmjs.org", method="npm"))
    monkeypatch.setattr(f, "_tier_direct", lambda *a, **k: pytest.fail("ladder not needed"))
    result = f.fetch_and_extract("https://www.npmjs.com/package/react", max_chars=5000)
    assert result["tier"] == "api:npm" and result["title"] == "react 19"


# ── block recognition ──────────────────────────────────────────────────────

@pytest.mark.parametrize("page", [
    "About this page Our systems have detected unusual traffic from your computer network.",
    "Verifying your request... Please wait while we verify your session.",
    "Bloomberg Need help? We've detected unusual activity from your computer network",
    "Click the button below to continue shopping Conditions of Use",
    "SORRY Something went wrong on our end. Please go back and try again. eBay Inc.",
])
def test_block_pages_are_recognised(page):
    assert challenges.classify(page)


def test_a_long_article_about_unusual_traffic_is_not_a_block():
    article = ("Google says its systems have detected unusual traffic from your computer "
               "network when bots hammer search. " + "Long article text. " * 200)
    assert challenges.classify(article) == ""


def test_google_block_page_with_long_links_is_recognised():
    # The real page (16 Nov 2026) was 1,395 characters, most of them link targets.
    link = "(https://www.google.com/sorry/index?continue=" + "x" * 400 + ")"
    page = ("**About this page** Our systems have detected unusual traffic from your "
            "computer network. [Why did this happen?]" + link + " This page appears when "
            "Google automatically detects requests coming from your computer network. "
            "[Learn more](https://support.google.com/websearch/answer/86640) " * 3)
    assert len(page) > 1000
    assert challenges.classify(page) == "generic"


def test_script_only_interstitial_is_caught_from_extracted_text(monkeypatch):
    # Scholar's verify page is all script: the HTML check sees nothing, the
    # extracted text is the prompt.
    shell = "<html><body><script>%s</script></body></html>" % ("var a=1;" * 300)
    prompt = "Verifying your request... Please wait while we verify your session."
    for name in ("_tier_direct", "_tier_tls", "_tier_crawl4ai"):
        monkeypatch.setattr(f, name, tier(html=shell, text=prompt))
    monkeypatch.setattr(extract_module, "extract", lambda html, url=None, **k: {
        "ok": True, "text": prompt, "tier": "trafilatura", "title": "", "published": "",
        "chars": len(prompt)})
    result = f.fetch_and_extract("https://scholar.google.com/scholar?q=x", max_chars=5000)
    assert not result["ok"]
    assert "challenge_detected:generic" in result["reason"]


def test_google_search_failure_carries_advice(monkeypatch):
    blocked = "Our systems have detected unusual traffic from your computer network."
    for name in ("_tier_direct", "_tier_tls", "_tier_crawl4ai"):
        monkeypatch.setattr(f, name, tier(text=blocked))
    result = f.fetch_and_extract("https://www.google.com/search?q=python", max_chars=5000)
    assert not result["ok"]
    assert any("use the search tool" in w for w in result.get("warnings", []))


def test_thin_google_search_also_carries_advice(monkeypatch):
    stub = ("<html><body><p>If you're having trouble accessing Google Search, please "
            "click here, or send feedback.</p></body></html>")
    for name in ("_tier_direct", "_tier_tls", "_tier_crawl4ai"):
        monkeypatch.setattr(f, name, tier(html=stub))
    result = f.fetch_and_extract("https://www.google.com/search?q=python", max_chars=5000)
    if result["ok"]:
        assert result["quality"] != "ok"
    assert any("use the search tool" in w for w in result.get("warnings", []))


# ── www twin ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url, family", [
    ("https://reddit.com/r/x", ["reddit.com", "www.reddit.com"]),
    ("https://www.reddit.com/r/x", ["www.reddit.com", "reddit.com"]),
    ("https://localhost:8000/x", ["localhost"]),
    ("https://quotes.toscrape.com/js/", ["quotes.toscrape.com"]),
    ("https://bbc.co.uk/news", ["bbc.co.uk", "www.bbc.co.uk"]),
    ("https://www.bbc.co.uk/news", ["www.bbc.co.uk", "bbc.co.uk"]),
    ("http://10.0.0.1/x".replace("10.0.0.1", "192.0.2.10"), ["192.0.2.10"]),
])
def test_host_family(url, family):
    assert host_family(url) == family
