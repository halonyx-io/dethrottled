"""Research returns bounded, traceable evidence without generating an answer."""

import threading
import time

from fastapi.testclient import TestClient

from dethrottled import research as engine
from dethrottled import server


def test_query_expansion_is_bounded_and_deduplicated():
    assert engine.queries_for("How does X work?") == [
        "How does X work?", "How does X work official source"]
    assert engine.queries_for("Question", ["Question", "Facet A", "Facet A"]) == [
        "Question", "Facet A"]


def test_selection_deduplicates_and_rejects_local_targets(monkeypatch):
    monkeypatch.setattr(engine, "public_url",
                        lambda url: not url.startswith("http://127."))
    row = lambda url: {"url": url, "title": url, "snippet": ""}
    selected = engine.select_sources([
        [row("https://a.example/one"), row("http://127.0.0.1/admin")],
        [row("https://a.example/one"), row("https://b.example/two")],
    ], 4)
    assert [item["url"] for item in selected] == [
        "https://a.example/one", "https://b.example/two"]
    assert selected[0]["query_indexes"] == [0, 1]


def test_default_primary_source_probe_leads_bundle(monkeypatch):
    monkeypatch.setattr(engine, "public_url", lambda url: True)
    selected = engine.select_sources([
        [{"url": "https://forum.example/post"}],
        [{"url": "https://docs.example.org/guide"}],
    ], 2, official_first=True)
    assert selected[0]["url"] == "https://docs.example.org/guide"


def test_evidence_windows_points_back_into_source_text():
    text = "Unrelated introduction. " * 60 + "In 2025, Denmark had 5120 megawatts of solar capacity. "
    windows = engine.evidence_windows(text, "Denmark solar capacity 2025")
    assert windows
    assert "5120 megawatts" in windows[0]["excerpt"]
    assert text[windows[0]["offset"]:].startswith(windows[0]["excerpt"])


def test_content_fingerprint_collapses_mirrors_but_keeps_related_articles():
    release = ("Python 3.0 final was released on December 3rd 2008. "
               "The language changed dictionaries and strings. ") * 18
    mirror = "Download Python. " + release + "Archived release files."
    history = ("Python has a long history of language releases, community "
               "conferences and package management projects. ") * 18
    first = engine.content_shingles(release)
    assert engine.duplicate_source(engine.content_shingles(mirror),
                                   [("https://python.org/3", first)]) == "https://python.org/3"
    assert engine.duplicate_source(engine.content_shingles(history),
                                   [("https://python.org/3", first)]) is None
    assert engine.content_shingles("Short shared navigation text") == set()


def test_research_endpoint_returns_source_bundle(monkeypatch):
    monkeypatch.setattr(engine, "public_url", lambda url: True)
    monkeypatch.setattr(server, "index_fetched", lambda rows: 0)

    categories_seen = []

    def ranked(body):
        categories_seen.append(body.categories)
        return ([{"url": "https://example.org/report", "title": "Report",
                  "snippet": "Annual capacity", "publishedDate": None}],
                {"elapsed_ms": 2, "per_source": {"web-google": 1}}, 8)

    def extracted(url, max_chars, **kwargs):
        return {"url": url, "quality": "ok", "content":
                "Denmark solar capacity in 2025 was 5120 megawatts. ",
                "tier": "direct/trafilatura", "title": ""}

    monkeypatch.setattr(server, "_ranked", ranked)
    monkeypatch.setattr(server, "_extract_row", extracted)
    response = TestClient(server.app).post(
        "/research", json={"question": "Denmark solar capacity in 2025?"})
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["model_used"] is False
    assert body["summary"]["read"] == 1
    assert body["sources"][0]["id"] == "S1"
    assert body["sources"][0]["title"] == "Report"
    assert "5120" in body["sources"][0]["evidence"][0]["excerpt"]
    assert categories_seen == ["", ""]
    invalid = TestClient(server.app).post(
        "/research", json={"question": "Denmark solar capacity in 2025?",
                           "categories": "images"})
    assert invalid.status_code == 422


def test_research_replaces_failed_source(monkeypatch):
    monkeypatch.setattr(engine, "public_url", lambda url: True)
    monkeypatch.setattr(server, "index_fetched", lambda rows: 0)

    def ranked(body):
        return ([{"url": "https://bad.example/report", "title": "Bad report"},
                 {"url": "https://good.example/report", "title": "Good report"},
                 {"url": "https://other.example/report", "title": "Other report"}],
                {"elapsed_ms": 1, "per_source": {"web-google": 3}}, 8)

    def extracted(url, max_chars, **kwargs):
        if "bad.example" in url:
            return {"url": url, "quality": "failed", "content": "",
                    "failure_reason": "http_404"}
        return {"url": url, "quality": "ok",
                "content": "The report describes solar capacity in 2025.",
                "title": ""}

    monkeypatch.setattr(server, "_ranked", ranked)
    monkeypatch.setattr(server, "_extract_row", extracted)
    response = TestClient(server.app).post(
        "/research", json={"question": "solar capacity 2025?", "max_sources": 2,
                           "queries": ["a custom facet"]})
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["selected"] == 2
    assert body["summary"]["attempted"] == 3
    assert [row["id"] for row in body["sources"]] == ["S1", "S2"]
    assert body["skipped"][0]["reason"] == "http_404"


def test_research_replaces_duplicate_source(monkeypatch):
    monkeypatch.setattr(engine, "public_url", lambda url: True)
    monkeypatch.setattr(server, "index_fetched", lambda rows: 0)
    urls = ["https://a.example/report", "https://b.example/mirror",
            "https://c.example/other"]
    common = ("The annual solar report measured new installations in Denmark "
              "and presented historical capacity tables. ") * 15
    other = ("A separate government survey covered wind generation and grid "
             "capacity in northern Europe. ") * 15

    def ranked(body):
        return ([{"url": url, "title": url} for url in urls],
                {"elapsed_ms": 1, "per_source": {}}, 8)

    def extracted(url, max_chars, **kwargs):
        return {"url": url, "quality": "ok", "content":
                other if url == urls[2] else common, "title": ""}

    monkeypatch.setattr(server, "_ranked", ranked)
    monkeypatch.setattr(server, "_extract_row", extracted)
    response = TestClient(server.app).post(
        "/research", json={"question": "Denmark energy capacity?",
                           "max_sources": 2, "queries": ["facet"]})
    assert response.status_code == 200
    body = response.json()
    assert [row["url"] for row in body["sources"]] == [urls[0], urls[2]]
    assert body["summary"]["attempted"] == 3
    assert body["skipped"] == [{"url": urls[1], "reason": "duplicate_content",
                                "duplicate_of": urls[0]}]


def test_research_searches_are_bounded_and_ordered(monkeypatch):
    monkeypatch.setattr(engine, "public_url", lambda url: True)
    monkeypatch.setattr(server, "index_fetched", lambda rows: 0)
    lock = threading.Lock()
    active = peak = 0

    def ranked(body):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.025)
        with lock:
            active -= 1
        return ([], {"elapsed_ms": 25, "per_source": {}}, 8)

    monkeypatch.setattr(server, "_ranked", ranked)
    response = TestClient(server.app).post(
        "/research", json={"question": "First", "queries": ["Second", "Third", "Fourth"]})
    assert response.status_code == 200
    assert [row["query"] for row in response.json()["queries"]] == [
        "First", "Second", "Third", "Fourth"]
    assert peak == 2
