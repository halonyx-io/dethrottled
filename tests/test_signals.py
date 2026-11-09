"""Source/page/date signals and token-oriented text helpers."""

from dethrottled import signals
from dethrottled.content import estimate_tokens, smart_truncate


def test_source_types_are_derived_from_known_hosts():
    assert signals.source_type("https://github.com/org/repo") == "repo"
    assert signals.source_type("https://arxiv.org/abs/1234.5678") == "paper"
    assert signals.source_type("https://docs.python.org/3/library/") == "docs"
    assert signals.source_type("https://stackoverflow.com/questions/1") == "forum"
    assert signals.source_type("https://en.wikipedia.org/wiki/HTTP") == "reference"
    assert signals.source_type("https://www.reuters.com/world/") == "news"
    assert signals.source_type("https://medium.com/@x/y") == "blog"
    assert signals.source_type("https://blog.example.com/post") == "blog"
    assert signals.source_type("https://random.example/a") == "other"


def test_page_type_describes_extraction_not_authority():
    assert signals.page_type({"content_type": "text/html", "content": "prose"}) == "article"
    assert signals.page_type({"content_type": "text/html",
                              "content_status": "navigation_only"}) == "list"
    assert signals.page_type({"content_type": "application/pdf", "content": "x"}) == "document"
    assert signals.page_type({"content_type": "text/html", "quality": "failed"}) == "unreadable"


def test_fetch_relevance_prefers_consensus_and_authoritative_types():
    assert signals.fetch_relevance(
        {"url": "https://github.com/a/b", "engines": ["ddg", "bing"]}) == "high"
    assert signals.fetch_relevance({"url": "https://random.example/a"}) == "medium"
    high = signals.fetch_relevance(
        {"url": "https://random.example/a", "score": 10.0}, max_score=10.0)
    low = signals.fetch_relevance(
        {"url": "https://random.example/a", "score": 0.1, "engines": ["ddg"]},
        max_score=10.0)
    assert high == "high" and low == "low"


def test_date_provenance_separates_structured_and_snippet_dates():
    structured = {"publishedDate": "2026-11-09T10:00:00Z"}
    assert signals.date_provenance(structured) == ("2026-11-09T10:00:00Z", "structured")
    snippet = {"snippet": "Published 9 November 2026 by the desk"}
    assert signals.date_provenance(snippet) == ("9 November 2026", "snippet")
    assert signals.date_provenance({"snippet": "no date here"}) == ("", "none")
    assert signals.age_days("2026-11-09") is not None


def test_annotate_dates_counts_and_sets_metadata():
    rows = [
        {"publishedDate": "2026-11-09"},
        {"snippet": "Updated 8 November 2026"},
        {"snippet": "undated"},
    ]
    out, dated = signals.annotate_dates(rows)
    assert dated == 2
    assert out[0]["date_source"] == "structured"
    assert out[1]["date_source"] == "snippet"
    assert out[1]["publishedDate"] == "8 November 2026"
    assert out[2]["date_source"] == "none"
    assert out[0]["published_age_days"] >= 0


def test_token_estimate_is_cjk_aware_and_smart_truncation_keeps_the_cap():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd" * 10) == 10
    assert estimate_tokens("模型") == 2
    text = "First paragraph.\n\nSecond paragraph with more words."
    clipped, changed = smart_truncate(text, 20)
    assert changed and len(clipped) <= 20 and clipped.endswith("…")
    assert smart_truncate("short", 20) == ("short", False)
