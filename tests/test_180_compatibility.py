"""Confirmed 1.7.1 accounting and combined-read presentation gaps."""

from fastapi.testclient import TestClient

from dethrottled import server
from dethrottled.cache import Cache, CacheView


def test_rejected_decoded_cache_is_counted_as_miss(tmp_path):
    cache = Cache(tmp_path / "cache.db")
    try:
        cache.put("search", "bad", value={"not": "a result list"})
        assert CacheView(cache).get("search", "bad") is None
        assert cache.stats()["hits"] == 0
        assert cache.stats()["misses"] == 1
        cache.put("search", "empty", value=[])
        assert CacheView(cache).get("search", "empty") == []
        assert cache.stats()["hits"] == 1 and cache.stats()["misses"] == 1
    finally:
        cache.close()


def test_combined_read_concise_omits_pdf_blocks_but_keeps_evidence(monkeypatch):
    source = {
        "url": "https://fixture.example/rfc.pdf",
        "content": "known fact",
        "quality": "ok",
        "document": {"document_id": "retained-document", "chars": 400000},
        "extraction": {"pages": [{"page": 1, "text_layer_blocks": [{"text": "x" * 400000}]}]},
        "provenance": {"source": "https://fixture.example/rfc.pdf"},
    }
    monkeypatch.setattr(server, "_ranked", lambda body: ([{"url": source["url"]}], {}, 1))
    monkeypatch.setattr(server, "_extract_row", lambda *a, **k: source)
    monkeypatch.setattr(server, "_queue_corpus", lambda *a, **k: None)
    client = TestClient(server.app)
    detailed = client.post("/search-and-fetch", json={"query": "known fact", "max_chars": 30})
    compact = client.post(
        "/search-and-fetch",
        json={"query": "known fact", "max_chars": 30, "response_format": "concise"},
    )
    assert detailed.status_code == compact.status_code == 200
    row = compact.json()[0]
    assert len(compact.content) < len(detailed.content) / 20
    assert row["content"] == "known fact" and row["document"] == source["document"]
    assert row["provenance"] == source["provenance"]
    assert "text_layer_blocks" in detailed.json()[0]["extraction"]["pages"][0]
    assert "text_layer_blocks" not in row["extraction"]["pages"][0]
    assert len(source["extraction"]["pages"][0]["text_layer_blocks"][0]["text"]) == 400000
