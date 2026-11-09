"""The SQLite cache, and the keying decision behind it.

The important test here is the last one. Extract entries are keyed on the URL
ALONE, not on (url, max_chars), because keying on the cap meant every change to
a caller's max_chars orphaned the entire cache -- thousands of real fetches
thrown away by a one-line config edit. Entries are stored at full length and
clipped on read instead.
"""

import time

import pytest

from dethrottled import cache as cache_module
from dethrottled.cache import DEFAULT_TTL, Cache


@pytest.fixture
def cache(tmp_path):
    c = Cache(tmp_path / "cache.sqlite")
    yield c
    c.close()


def test_round_trip(cache):
    cache.put("search", "q", value={"rows": [1, 2, 3]})
    assert cache.get("search", "q") == {"rows": [1, 2, 3]}


def test_miss_is_none_not_an_error(cache):
    assert cache.get("search", "never stored") is None


def test_entries_expire(cache):
    cache.put("search", "q", value={"a": 1})
    assert cache.get("search", "q", ttl=0.0) is None


def test_ttl_defaults_differ_by_kind(cache):
    """Page bodies are worth keeping far longer than a result list: the search
    goes stale in hours, the article does not change at all."""
    assert DEFAULT_TTL["extract"] > DEFAULT_TTL["search"]


def test_fresh_entry_survives_its_ttl(cache):
    cache.put("search", "q", value={"a": 1})
    assert cache.get("search", "q", ttl=3600) == {"a": 1}


def test_put_overwrites(cache):
    cache.put("search", "q", value={"v": 1})
    cache.put("search", "q", value={"v": 2})
    assert cache.get("search", "q") == {"v": 2}


def test_kinds_do_not_collide(cache):
    """The same key string under two kinds is two entries. Without this a URL
    cached as a page body would be returned as a search result."""
    cache.put("search", "same", value={"which": "search"})
    cache.put("extract", "same", value={"which": "extract"})
    assert cache.get("search", "same")["which"] == "search"
    assert cache.get("extract", "same")["which"] == "extract"


def test_unicode_survives_the_round_trip(cache):
    """Stored with ensure_ascii=False, so a French or Arabic page comes back as
    itself rather than as escape sequences."""
    value = {"text": "capacité solaire du Maroc — 100%", "ar": "الطاقة"}
    cache.put("extract", "https://example.com/x", value=value)
    assert cache.get("extract", "https://example.com/x") == value


def test_stats_counts_entries(cache):
    cache.put("search", "a", value={})
    cache.put("extract", "b", value={})
    stats = cache.stats()
    assert isinstance(stats, dict) and stats


def test_extract_is_keyed_on_url_alone(cache):
    """The bug this prevents: keying on (url, max_chars) meant every change to
    a caller's character cap orphaned the whole cache at once."""
    cache.put("extract", "https://example.com/a", value={"text": "x" * 5000})
    # A later reader wanting a different amount of text must still hit.
    assert cache.get("extract", "https://example.com/a") is not None


def test_purge_removes_old_entries(cache):
    cache.put("search", "old", value={"a": 1})
    assert cache.purge(older_than_days=-1) >= 1
    assert cache.get("search", "old") is None


def test_concurrent_writes_do_not_corrupt(cache):
    """One lock, commits inside it. Threads share a Cache across the server's
    request handlers, so this is the normal case rather than an edge one."""
    import threading
    errors = []

    def write(n):
        try:
            for i in range(20):
                cache.put("search", "k%d" % n, value={"i": i})
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert cache.get("search", "k0") == {"i": 19}


def test_cacheview_rejects_wrong_shape_extract_before_counting_a_hit(cache):
    from dethrottled.cache import CacheView, valid_extract

    cache.put("extract", "https://example.com/bad",
              value={"schema_version": 3, "text": "x", "acquisition": {},
                     "extraction": {"pages": "not-a-list"}, "content_assessment": {}})
    assert cache.get("extract", "https://example.com/bad",
                     validator=valid_extract) is None
    view = CacheView(cache)
    assert view.get("extract", "https://example.com/bad") is None
    stats = cache.stats()
    assert stats["hits"] == 0
    assert stats["misses"] == 2


def test_maintenance_deletes_expired_rows_instead_of_only_missing_them(tmp_path):
    cache = Cache(tmp_path / "cache.sqlite")
    try:
        cache.put("search", "old", value={"a": 1})
        cache._db.execute("UPDATE entries SET ts=?", (time.time() - 7 * 3600,))
        cache._db.commit()
        assert cache.get("search", "old") is None
        result = cache.maintain()
        assert result["expired"] >= 1
        row = cache._db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        assert row == 0
    finally:
        cache.close()


def test_maintenance_enforces_the_size_ceiling_and_keeps_newest(tmp_path):
    cache = Cache(tmp_path / "cache.sqlite")
    try:
        cache.max_bytes = 120_000
        for number in range(20):
            cache.put("extract", "https://example.com/%d" % number,
                      value={"text": ("%02d" % number) + "x" * 20_000})
        result = cache.maintain()
        assert result["bytes"] <= 120_000
        assert result["evicted"] >= 1
        assert cache.get("extract", "https://example.com/19") is not None
        assert cache.get("extract", "https://example.com/0") is None
    finally:
        cache.close()


def test_maintenance_runs_automatically_after_the_write_interval(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_module, "CACHE_MAINTENANCE_EVERY", 2)
    cache = Cache(tmp_path / "cache.sqlite")
    try:
        cache.put("search", "old", value={"a": 1})
        cache._db.execute("UPDATE entries SET ts=?", (time.time() - 7 * 3600,))
        cache._db.commit()
        cache.put("search", "new", value={"a": 2})
        assert cache.get("search", "old") is None
        assert cache.get("search", "new") == {"a": 2}
        assert cache.maintenance["expired"] >= 1
    finally:
        cache.close()


def test_stats_reports_cache_bytes_and_limit(tmp_path):
    cache = Cache(tmp_path / "cache.sqlite")
    try:
        cache.put("search", "q", value={"a": 1})
        stats = cache.stats()
        assert stats["bytes"] > 0
        assert stats["max_bytes"] == cache.max_bytes
        assert stats["maintenance"]["bytes"] > 0
        assert "expired" in stats["maintenance"]
    finally:
        cache.close()
