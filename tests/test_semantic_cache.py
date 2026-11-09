"""Semantic cache precision is configurable and context-scoped."""

import time

from dethrottled import semantic_cache


def test_semantic_cache_hits_paraphrase_and_rejects_other_topics(tmp_path, monkeypatch):
    vectors = {
        "python asyncio": [1.0, 0.0, 0.0],
        "python async": [0.99, 0.10, 0.0],
        "database tuning": [0.0, 1.0, 0.0],
    }
    monkeypatch.setattr(semantic_cache, "_embed", lambda text: vectors[text])
    cache = semantic_cache.SemanticCache(tmp_path / "semantic.sqlite", threshold=0.90)
    try:
        cache.put("python asyncio", "ctx", {"rows": [{"url": "https://a"}]})
        hit = cache.get("python async", "ctx")
        assert hit and hit["similarity"] >= 0.90
        assert hit["value"]["rows"][0]["url"] == "https://a"
        assert cache.get("database tuning", "ctx") is None
        assert cache.get("python async", "other-context") is None
    finally:
        cache.close()


def test_semantic_cache_respects_ttl(tmp_path, monkeypatch):
    monkeypatch.setattr(semantic_cache, "_embed", lambda text: [1.0, 0.0])
    cache = semantic_cache.SemanticCache(tmp_path / "semantic.sqlite", ttl=1)
    try:
        cache.put("query", "ctx", {"rows": []})
        assert cache.get("query", "ctx") is not None
        with cache._lock:
            cache._db.execute("UPDATE semantic_queries SET ts=?", (time.time() - 10,))
            cache._db.commit()
        assert cache.get("query", "ctx") is None
    finally:
        cache.close()


def test_semantic_cache_is_off_by_default(monkeypatch):
    monkeypatch.delenv("DETHROTTLED_SEMANTIC_CACHE", raising=False)
    assert semantic_cache.configured() == ""
    assert semantic_cache.shared() is None
