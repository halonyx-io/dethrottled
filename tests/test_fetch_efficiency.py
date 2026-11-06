"""Preserve evidence/order while avoiding batch stalls and unusable cache hits."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from dethrottled import fetch, server
from dethrottled.cache import Cache, CacheView


def test_batch_reuses_a_free_slot_before_slow_first_url_finishes():
    release = threading.Event()
    fifth_started = threading.Event()

    def read(index):
        if index == 0:
            assert release.wait(5)
        if index == 4:
            fifth_started.set()
        return {"url": str(index), "content": f"fact-{index}", "warnings": [str(index)]}

    with ThreadPoolExecutor(max_workers=1) as caller:
        future = caller.submit(server._read_batch, list(range(8)), read)
        try:
            assert fifth_started.wait(2), "idle slots wait for an unrelated slow URL"
        finally:
            release.set()
        rows = future.result(timeout=3)
    assert [r["content"] for r in rows] == [f"fact-{i}" for i in range(8)]
    assert [r["warnings"] for r in rows] == [[str(i)] for i in range(8)]


def test_batch_keeps_four_active_reads_and_original_order():
    import time

    active = peak = 0
    lock = threading.Lock()
    first_readers = threading.Barrier(4)

    def read(index):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            if index < 4:
                first_readers.wait(timeout=3)
            time.sleep(0.01 * (1 + index % 3))
            return {"content": str(index), "quality": "thin" if index == 5 else "ok"}
        finally:
            with lock:
                active -= 1

    rows = server._read_batch(list(range(12)), read)
    assert peak == 4
    assert [r["content"] for r in rows] == [str(i) for i in range(12)]
    assert rows[5]["quality"] == "thin"
    assert server._read_batch([], read) == []


@pytest.mark.parametrize("final", [
    "https://fixture.example/new/location/", "https://other.example/new/location/",
])
def test_relative_links_use_final_acquired_url(monkeypatch, tmp_path, final):
    monkeypatch.setenv("DETHROTTLED_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_queue_corpus", lambda *a, **kw: None)
    monkeypatch.setattr(fetch, "ENABLE_TLS", False)
    monkeypatch.setattr(fetch, "_tier_direct", lambda *a: (
        {"html": '<html><a href="next.html">Next fact</a></html>'}, "", final))
    row = TestClient(server.app).post("/fetch", json={
        "urls": ["https://fixture.example/old/"], "format": "links",
        "render": "never", "recovery": "manual",
    }).json()[0]
    assert f"[Next fact]({final}next.html)" in row["content"]
    assert row["url"] == "https://fixture.example/old/"
    assert row["final_url"] == final


@pytest.mark.parametrize("value", [
    None, [], "wrong shape", 7,
    {"schema_version": 3, "text": 7},
    {"schema_version": 3, "text": "cached", "acquisition": []},
    {"schema_version": 3, "text": "cached", "extraction": {"pages": [None]}},
])
def test_unusable_extraction_cache_is_a_miss(tmp_path, value):
    cache = Cache(tmp_path / "cache.sqlite")
    try:
        cache.put("extract", "url", value=value)
        assert CacheView(cache).get("extract", "url") is None
    finally:
        cache.close()


@pytest.mark.parametrize("value", [None, {}, "wrong shape", [None], [{"url": 123}]])
def test_unusable_search_cache_is_a_miss(tmp_path, value):
    cache = Cache(tmp_path / "cache.sqlite")
    try:
        cache.put("search", "query", value=value)
        assert CacheView(cache).get("search", "query") is None
    finally:
        cache.close()


def test_empty_search_cache_remains_a_valid_empty_hit(tmp_path):
    cache = Cache(tmp_path / "cache.sqlite")
    try:
        cache.put("search", "query", value=[])
        assert CacheView(cache).get("search", "query") == []
    finally:
        cache.close()


def test_corrupt_json_is_counted_as_miss_not_hit(tmp_path):
    cache = Cache(tmp_path / "cache.sqlite")
    try:
        cache.put("search", "query", value=[])
        with cache._lock, cache._db:
            cache._db.execute("UPDATE entries SET value='{' WHERE key=?",
                              (cache.key("search", "query"),))
        assert cache.get("search", "query") is None
        assert cache.stats()["hits"] == 0
        assert cache.stats()["misses"] == 1
    finally:
        cache.close()


def test_bad_extraction_cache_falls_through_to_readable_evidence(monkeypatch, tmp_path):
    cache = Cache(tmp_path / "cache.sqlite")
    url = "https://fixture.example/report"
    cache.put("extract", url, value=["not an extraction"])
    monkeypatch.setenv("DETHROTTLED_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "cache", lambda: cache)
    monkeypatch.setattr(server, "_queue_corpus", lambda *a, **kw: None)
    monkeypatch.setattr(fetch, "ENABLE_TLS", False)
    html = "<html><article><p>Verified retained fact is 7314. </p>" * 50 + "</article></html>"
    monkeypatch.setattr(fetch, "_tier_direct", lambda *a: ({"html": html}, "", url))
    try:
        response = TestClient(server.app).post("/fetch", json={
            "urls": [url], "render": "never", "recovery": "manual",
        })
        assert response.status_code == 200
        row = response.json()[0]
        assert row["quality"] == "ok" and "7314" in row["content"]
        assert not row["cached"]
    finally:
        cache.close()
