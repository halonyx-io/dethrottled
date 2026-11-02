"""Regressions reproduced during the live end-to-end evaluation."""

import importlib.util
import time

import pytest
from fastapi.testclient import TestClient

from dethrottled import fetch, rank, search, server
from dethrottled.cache import Cache, CacheView
from dethrottled.content import constrained, decode_html, page_details, passage_excerpt


def test_html_charset_does_not_inherit_requests_latin1_default():
    text = '<html><meta charset="UTF-8"><body>Häring — Café 中文字符测试</body></html>'
    assert decode_html(text.encode(), "text/html") == text
    latin = "<html><body>café</body></html>"
    assert decode_html(latin.encode("windows-1252"), "text/html; charset=windows-1252") == latin


def test_refresh_replaces_cached_content_and_bypass_does_not(tmp_path):
    store = Cache(tmp_path / "cache.sqlite")
    store.put("extract", "url", value={"text": "old", "schema_version": 3})
    refresh = CacheView(store, mode="refresh")
    assert refresh.get("extract", "url") is None
    refresh.put("extract", "url", value={"text": "new", "schema_version": 3})
    hit = CacheView(store).get("extract", "url")
    assert hit["text"] == "new" and hit["cached"] is True
    assert hit["retrieved_at"] and hit["cache_age_seconds"] >= 0
    bypass = CacheView(store, mode="bypass")
    bypass.put("extract", "url", value={"text": "must not persist", "schema_version": 3})
    assert CacheView(store).get("extract", "url")["text"] == "new"
    assert CacheView(store, max_age=0).get("extract", "url") is None


@pytest.mark.parametrize("host,allowed", [
    ("docs.python.org", True), ("sub.docs.python.org", True),
    ("docs.python.org.attacker.invalid", False), ("news.example.org", False),
])
def test_site_constraint_matches_host_boundaries(host, allowed):
    assert constrained("site:docs.python.org sqlite3", {"url": "https://" + host}) is allowed


def test_site_constraints_survive_corpus_merge(monkeypatch):
    monkeypatch.setattr(server.fs, "search", lambda *a, **k: ([
        {"url": "https://docs.python.org/a", "title": "sqlite3"}], {}))
    monkeypatch.setattr(server.ranker, "apply", lambda rows, *a, **k: (
        [*rows, {"url": "https://unrelated.example/a", "title": "sqlite3"}], []))
    rows = TestClient(server.app).post("/search", json={
        "query": "site:docs.python.org sqlite3", "corpus": 1}).json()
    assert [r["url"] for r in rows] == ["https://docs.python.org/a"]


def test_empty_search_keeps_attempt_diagnostics(monkeypatch):
    monkeypatch.setattr(server.fs, "search", lambda *a, **k: (
        [], {"per_source": {"web": "challenge"}, "elapsed_ms": 17}))
    data = TestClient(server.app).post("/v2/search", json={"query": "missing"}).json()
    assert data["results"] == [] and data["attempts"][0]["status"] == "challenge"
    assert data["elapsed_ms"] == 17


@pytest.mark.parametrize("path,body", [
    ("/fetch", {"urls": []}),
    ("/fetch", {"urls": ["https://example.org"] * 11}),
    ("/fetch", {"urls": ["https://example.org"], "format": "typo"}),
    ("/fetch", {"urls": ["https://example.org"], "render": "typo"}),
    ("/fetch", {"urls": ["https://example.org"], "render_delay": 100}),
    ("/search", {"query": "x", "limit": 0}),
    ("/search", {"query": "x", "recency": -1}),
    ("/search", {"query": "x", "engines": "imaginary"}),
    ("/search", {"query": "x", "profile": "imaginary"}),
    ("/search", {"query": "   "}),
])
def test_invalid_controls_are_rejected_before_work(path, body):
    assert TestClient(server.app).post(path, json=body).status_code == 422


def test_ranking_reads_snippets_and_exposes_scores():
    rows = [{"title": "Other topic", "snippet": "gardening"},
            {"title": "Reference", "snippet": "sqlite3 autocommit transaction control"}]
    result = rank.rank_rows(rows, "sqlite3 autocommit")
    assert result[0]["title"] == "Reference" and result[0]["score"] > 0
    assert result[0]["upstream_rank"] == 2
    unicode_rows = [{"title": "weather"}, {"title": "数据库事务管理"}]
    assert rank.rank_rows(unicode_rows, "数据库事务管理")[0]["title"] == "数据库事务管理"


def test_passage_selection_precedes_output_clipping():
    text = ("A general introduction to the library. " * 250 +
            "\nAutocommit controls sqlite3 transactions. " * 12)
    selected, evidence = passage_excerpt(text, "sqlite3 autocommit transactions", 900)
    assert "Autocommit" in selected and len(selected) <= 900
    assert evidence[0]["offset"] > 2500
    assert evidence[0]["offset_in"] == "full_extraction"


@pytest.mark.skipif(importlib.util.find_spec("selectolax") is None, reason="HTML extra")
def test_short_and_raw_reads_do_not_require_a_long_article(monkeypatch):
    html = "<html><body><h1>Meeting</h1><p>Begins at 09:30.</p></body></html>"
    monkeypatch.setattr(fetch, "_tier_direct", lambda *a: ({"html": html}, "", a[0]))
    monkeypatch.setattr(fetch, "ENABLE_TLS", False)
    monkeypatch.setattr(fetch, "ENABLE_JINA", False)
    result = fetch.fetch_and_extract("https://example.org/meeting", allow_render=False,
                                     keep_html=True, format="html")
    assert result["ok"] and result["html"] == html
    assert "09:30" in result["text"]


@pytest.mark.skipif(importlib.util.find_spec("selectolax") is None, reason="HTML extra")
def test_image_timetable_is_exposed_as_incomplete_content():
    data = page_details('<html><body><h1>Schedule</h1><img src="/timetable.jpg" '
                        'alt="Passenger ferry schedule"></body></html>', "https://example.org/")
    assert data["content_status"] == "image_content"
    assert data["assets"][0]["url"] == "https://example.org/timetable.jpg"
    assert data["warnings"]


def test_output_representation_is_not_the_corpus_body(monkeypatch):
    indexed = []
    monkeypatch.setattr(server, "index_fetched", lambda rows: indexed.extend(rows))
    monkeypatch.setattr(server.fetcher, "fetch_and_extract", lambda url, **kw: {
        "ok": True, "text": "Canonical prose", "html": "<html>" + "x" * 1000 + "</html>",
        "cached": False, "tier": "direct", "extractor": "short", "url": url})
    row = TestClient(server.app).post("/fetch", json={
        "urls": ["https://example.org/"], "format": "html", "max_chars": 100}).json()[0]
    assert len(row["content"]) == len(row["html"]) == 100 and row["truncated"]
    assert "_index_text" not in row
    assert indexed[0][1]["content"] == "Canonical prose"


def test_render_wait_is_request_local(monkeypatch):
    calls = []

    class Response:
        status_code = 200

        def json(self):
            return {"results": [{"success": True, "markdown": "Ready article " * 100}]}

    monkeypatch.setattr(fetch.requests, "post", lambda *a, **kw: (
        calls.append(kw["json"]) or Response()))
    monkeypatch.setattr(fetch, "CRAWL4AI_URL", "https://renderer.invalid")
    monkeypatch.setattr(fetch, "ENABLE_JINA", False)
    monkeypatch.setattr(fetch, "_tier_direct", lambda *a: ({}, "missing", a[0]))
    monkeypatch.setattr(fetch, "ENABLE_TLS", False)
    monkeypatch.setattr(fetch, "tier_resting", lambda tier: False)
    fetch.fetch_and_extract("https://example.org/a", wait_for="#ready article", render_delay=0.7)
    fetch.fetch_and_extract("https://example.org/b")
    assert calls[0]["crawler_config"]["params"]["wait_for"] == "css:#ready article"
    assert "wait_for" not in calls[1]["crawler_config"]["params"]


def test_public_reads_reject_private_redirects_before_following(monkeypatch):
    from dethrottled import research
    called = []
    monkeypatch.setattr(research, "public_url", lambda url: "example.org" in url)

    class Redirect:
        status_code = 302
        @property
        def headers(self):
            return {"Location": "http://localhost/secret"}

    def get(url, **kwargs):
        called.append(url)
        return Redirect()

    token = fetch._READ_OPTIONS.set({"public_only": True})
    try:
        with pytest.raises(ValueError, match="public_target_required"):
            fetch._get_with_policy(get, "https://example.org/")
    finally:
        fetch._READ_OPTIONS.reset(token)
    assert called == ["https://example.org/"]


def test_source_profile_avoids_news_for_web_queries(monkeypatch):
    calls = []
    monkeypatch.setattr(search, "web_search", lambda *a, **k: [
        {"url": "https://example.org/docs", "title": "Useful reference"}])
    monkeypatch.setattr(search, "bing_news", lambda *a, **k: calls.append("news") or [])
    monkeypatch.setattr(search, "searxng", lambda *a, **k: calls.append("searxng") or [])
    rows, meta = search.search("a question", profile="web")
    assert rows and not calls and meta["sources"] == ["web"]


def test_opaque_identifier_corpus_does_not_return_semantic_near_misses(tmp_path):
    from dethrottled.corpus import Corpus
    corpus = Corpus(tmp_path / "corpus.sqlite")
    corpus._db.execute("INSERT INTO passages VALUES(?,?,?,?,?,?,?)", (
        "one", "https://example.org/", "Unrelated", "A different document entirely",
        "minilm", b"", time.time()))
    corpus._db.commit()
    assert corpus.search("dethrottled-nonexistent-7f291cd3c8") == []


def test_fts_stays_consistent_when_a_document_is_replaced(tmp_path):
    from dethrottled.corpus import Corpus
    corpus = Corpus(tmp_path / "corpus.sqlite")
    if not corpus._fts:
        pytest.skip("SQLite without FTS5")
    for text in ["oldword", "newword"]:
        corpus._db.execute("INSERT OR REPLACE INTO passages VALUES(?,?,?,?,?,?,?)", (
            "same", "https://example.org/", "Doc", text, "minilm", b"", time.time()))
        corpus._db.commit()
    assert not corpus.search("oldword", mode="lexical")
    assert corpus.search("newword", mode="lexical")[0]["text"] == "newword"


def test_passage_ranking_preserves_central_terms_beyond_a_generic_intro():
    intro = "Python sqlite3 control transactions reference introduction. " * 160
    answer = "Set autocommit to False for Python sqlite3 transaction control. " * 20
    text = intro + answer + " Unrelated appendices. " * 200
    selected, evidence = passage_excerpt(
        text, "How does Python sqlite3 autocommit control transactions?", 2500)
    assert "Set autocommit to False" in selected
    assert evidence[0]["offset"] > len(intro) - 1000
    for item in evidence:
        assert text[item["offset"]:item["offset"] + len(item["excerpt"])] == item["excerpt"]
        assert all(term in item["excerpt"].casefold() for term in item["matched_terms"])


def test_specialists_append_only_with_room_after_primary(monkeypatch):
    monkeypatch.setattr(search, "web_search", lambda *a, **k: [
        {"url": f"https://web.example/{i}", "title": f"Web source {i}",
         "engine": "web-ddg-lite"} for i in range(10)])
    monkeypatch.setattr(search, "searxng", lambda *a, **k: [
        {"url": "https://specialist.example/paper", "title": "Academic evidence",
         "engine": "crossref"}])
    rows, _ = search.search("academic evidence", max_items=3, profile="academic")
    assert len(rows) == 3 and all(row["engine"] == "web-ddg-lite" for row in rows)
    menu, _ = search.search("academic evidence", max_items=16, profile="academic")
    assert len(menu) == 11
    assert [r["engine"] for r in menu[:10]] == ["web-ddg-lite"] * 10
    assert menu[-1]["engine"] == "crossref"
