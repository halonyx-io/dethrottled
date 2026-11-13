"""One identity rule, and duplicates merged rather than discarded.

`dedupe` decides "same page" for search rows, research sources and corpus
hits. These tests pin both directions: what must collapse, and what must stay
apart (a wrong merge silently loses a source).
"""
import pytest

from dethrottled import consensus, dedupe
from dethrottled import search as fs

FILLER = " ".join(f"Sentence {i} explains how the journal records each change." for i in range(20))


@pytest.mark.parametrize("a,b", [
    ("http://example.com/a", "https://example.com/a"),
    ("https://example.com:443/a", "https://example.com/a"),
    ("https://www.example.com/docs/index.html", "https://example.com/docs"),
    ("https://example.com/story/amp", "https://example.com/story"),
    ("https://example.com/p?b=2&a=1", "https://example.com/p?a=1&b=2"),
    ("https://m.example.com/a/?utm_source=x#top", "https://example.com/a"),
])
def test_same_page_has_one_key(a, b):
    assert dedupe.url_key(a) == dedupe.url_key(b)


@pytest.mark.parametrize("a,b", [
    ("https://example.com/a", "https://example.com/b"),
    ("https://example.com/p?id=7", "https://example.com/p?id=8"),
    ("https://example.com/A", "https://example.com/a"),
    ("https://example.com:8443/a", "https://example.com/a"),
    ("https://a.example.com/x", "https://b.example.com/x"),
])
def test_different_pages_keep_different_keys(a, b):
    assert dedupe.url_key(a) != dedupe.url_key(b)


def test_repeated_query_values_keep_their_order():
    assert dedupe.url_key("https://e.com/a?id=7&id=8") != dedupe.url_key("https://e.com/a?id=8&id=7")


@pytest.mark.parametrize("value", ["", "not a url", "mailto:a@b.c", "https://[bad"])
def test_rubbish_is_returned_unchanged(value):
    assert dedupe.url_key(value) == value


def test_declared_canonical_is_trusted_only_on_the_same_site():
    same = {"url": "https://news.example.co.uk/story?id=1",
            "page_metadata": {"canonical": "/story/canonical"}}
    assert dedupe.declared_key(same) == "https://news.example.co.uk/story/canonical"
    other = {"url": "https://mirror.example/story",
             "page_metadata": {"canonical": "https://origin.example/story"}}
    assert dedupe.declared_key(other) is None


def test_provider_date_fills_an_undated_survivor():
    survivor = {"url": "https://example.com/a", "snippet": "No date here.", "engine": "ddg"}
    duplicate = {"url": "https://www.example.com/a", "publishedDate": "2026-11-01T10:00:00Z",
                 "engine": "searxng"}
    dedupe.merge_into(survivor, duplicate)
    assert survivor["publishedDate"] == "2026-11-01T10:00:00Z"
    assert survivor["date_source"] == "structured"
    assert survivor["duplicates"] == [{"url": "https://www.example.com/a", "provider": "searxng",
                                       "reason": "same_url"}]


def test_snippet_date_is_merged_but_never_promoted():
    from dethrottled import signals
    survivor = {"url": "https://example.com/a", "snippet": "Undated."}
    duplicate = {"url": "https://example.com/a", "snippet": "8 Oct 2025 — Release notes."}
    dedupe.merge_into(survivor, duplicate)
    assert survivor["date_source"] == "snippet"
    fields = signals.search_date_fields(survivor)
    assert fields["published_at"] is None
    assert fields["date_hint"]["value"] == "8 Oct 2025"
    assert "duplicates" not in survivor          # same address: provenance, not a duplicate


def test_survivor_provider_date_wins_and_a_contradiction_is_reported():
    survivor = {"url": "https://example.com/a", "publishedDate": "2026-11-01"}
    duplicate = {"url": "https://example.com/a", "snippet": "Mar 14, 2010 — Python 3.14"}
    dedupe.merge_into(survivor, duplicate)
    assert survivor["publishedDate"] == "2026-11-01"
    assert survivor["date_hint_rejected"]["reason"] == "conflicts_with_provider_date"


def test_merge_fills_an_empty_snippet_and_unions_provenance():
    survivor = {"url": "https://e.com/a", "snippet": "", "discovery": [{"provider": "web"}]}
    dedupe.merge_into(survivor, {"url": "https://e.com/a", "snippet": "Useful text.",
                                 "discovery": [{"provider": "searxng"}]})
    assert survivor["snippet"] == "Useful text."
    assert survivor["discovery"] == [{"provider": "web"}, {"provider": "searxng"}]
    dedupe.merge_into(survivor, {"url": "https://e.com/a", "snippet": "Other text."})
    assert survivor["snippet"] == "Useful text."


def test_duplicates_list_is_bounded():
    survivor = {"url": "https://e.com/a"}
    for i in range(20):
        dedupe.merge_into(survivor, {"url": f"https://e.com/a?utm_source={i}"})
    assert len(survivor["duplicates"]) == dedupe.DUPLICATES_CAP


def test_content_identity_needs_enough_text():
    short = dedupe.text_fingerprint("Allocation is 7341 tonnes.")
    assert short == {"digest": "", "shingles": set()}
    same_short = dedupe.text_fingerprint("Allocation is 7341 tonnes.")
    assert dedupe.content_match(short, same_short) is None
    long_a = dedupe.text_fingerprint(FILLER)
    shouted = dedupe.text_fingerprint(FILLER.upper() + "!")
    assert dedupe.content_match(long_a, shouted) == "same_text"
    edited = FILLER.replace("Sentence 19", "Paragraph nineteen")
    assert dedupe.content_match(long_a, dedupe.text_fingerprint(edited)) == "near_text"
    other = " ".join(f"Row {i} lists a different measured value for wind." for i in range(20))
    assert dedupe.content_match(long_a, dedupe.text_fingerprint(other)) is None


def test_collapse_by_content_keeps_order_and_counts():
    rows = [{"url": "https://a.example/r", "content": FILLER},
            {"url": "https://b.example/other", "content": FILLER.replace("journal", "ledger") * 2},
            {"url": "https://c.example/mirror", "content": FILLER},
            {"url": "http://a.example/r/", "content": "Anything"}]
    counts = {}
    out = dedupe.collapse(rows, by="content", counts=counts)
    assert [r["url"] for r in out] == ["https://a.example/r", "https://b.example/other"]
    assert counts == {"same_text": 1, "same_url": 1}
    assert {d["url"] for d in out[0]["duplicates"]} == {"https://c.example/mirror",
                                                       "http://a.example/r/"}
    assert "duplicates" not in rows[0]           # inputs are not modified


def test_search_merges_a_dated_supplement_into_the_primary_row(monkeypatch):
    primary = [{"url": "https://example.com/release", "title": "Release", "snippet": "Notes.",
                "engine": "web-ddg-lite"}]
    supplement = [{"url": "https://www.example.com/release/", "title": "Release",
                   "snippet": "Notes.", "publishedDate": "2026-10-07", "engine": "yandex"}]
    monkeypatch.setattr(fs, "web_search", lambda *a, **k: primary)
    monkeypatch.setattr(fs, "searxng", lambda *a, **k: supplement)
    monkeypatch.setattr(fs, "SEARXNG_URL", "http://searxng")
    rows, meta = fs.search("release notes", engines="web,yandex")
    assert len(rows) == 1
    assert rows[0]["url"] == "https://example.com/release"
    assert rows[0]["publishedDate"] == "2026-10-07"
    assert meta["deduplication"] == {"same_url": 1}


def test_query_variants_merge_dates_and_respect_query_identity():
    out = consensus.merge_variants([
        [{"url": "https://e.com/p?id=1", "discovery": [{"provider": "web"}]}],
        [{"url": "https://e.com/p?id=2", "discovery": [{"provider": "web"}]},
         {"url": "http://e.com/p?id=1", "publishedDate": "2026-11-02",
          "discovery": [{"provider": "searxng"}]}],
    ])
    assert [r["url"] for r in out] == ["https://e.com/p?id=1", "https://e.com/p?id=2"]
    assert out[0]["publishedDate"] == "2026-11-02"
    assert out[0]["query_variants"] == [0, 1]


def test_reputable_sweep_does_not_add_a_canonical_duplicate(monkeypatch):
    primary = [{"url": "https://www.reuters.com/a?utm_source=x", "title": "A", "snippet": "s",
                "engine": "web-ddg-lite"}]
    monkeypatch.setattr(fs, "web_search", lambda *a, **k: primary)
    monkeypatch.setattr(fs, "reputable_sweep", lambda *a, **k: [
        {"url": "https://reuters.com/a", "title": "A", "snippet": "s", "engine": "sweep"}])
    rows, meta = fs.search("a", engines="web", prefer_domains=["apnews.com"])
    assert [r["url"] for r in rows] == ["https://www.reuters.com/a?utm_source=x"]
    assert meta["per_source"].get("reputable-sweep") == 0
