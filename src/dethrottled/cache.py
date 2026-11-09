#!/usr/bin/env python3
"""SQLite cache for the free stack.

The free stack has no quota to protect, but it does have manners and a clock.
Every cached hit is a page we do not re-request from someone else's server and
a second we do not spend, so caching is both the polite thing and the fast
thing. Search results expire quickly; fetched article bodies barely change, so
they are kept far longer.

One file, no daemon, trivially deletable — the whole lab is meant to be
removable with `rm -rf`.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

NEWS_SEARCH_TTL = 30 * 60      # news moves faster than a general search menu

# The cache is a convenience, not an archive. TTL expiry only turns a read
# into a miss; without maintenance the old rows and their pages stay on disk
# forever. Keep a bounded footprint and clean expired rows periodically, the
# same way the corpus has its own prune.
CACHE_MAX_BYTES = int(os.getenv("DETHROTTLED_CACHE_MAX_BYTES", str(512 * 1024**2)))
CACHE_MAINTENANCE_EVERY = int(os.getenv("DETHROTTLED_CACHE_MAINTENANCE_EVERY", "200"))
CACHE_EVICT_TARGET = 0.90

DEFAULT_TTL = {
    "search": 6 * 3600,        # a search result set goes stale fast
    # The fetcher stores bodies under "extract". This table said "fetch", so
    # every body fell through to the unnamed hourly default and 742 of the 762
    # in the cache were already dead -- meaning almost every page was refetched
    # almost every time, at nearly seven seconds each. Both spellings are here
    # now; the intent was always twenty-one days.
    "extract": 21 * 24 * 3600,
    "fetch": 21 * 24 * 3600,   # an article body essentially never changes
}


class Cache:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Fetches run four at a time now, and a sqlite connection refuses to
        # be used from a thread other than the one that created it. WAL plus a
        # single lock is ample here: writes are small and rare, and the
        # alternative -- a connection per thread -- is four writers racing for
        # one file.
        self._db = sqlite3.connect(str(self.path), timeout=30,
                                   check_same_thread=False)
        self._lock = threading.Lock()
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                key   TEXT PRIMARY KEY,
                kind  TEXT NOT NULL,
                value TEXT NOT NULL,
                ts    REAL NOT NULL
            )
        """)
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_kind_ts ON entries(kind, ts)")
        self._db.commit()
        self.hits = 0
        self.misses = 0
        self.max_bytes = CACHE_MAX_BYTES
        self.writes = 0
        self.maintenance = {
            "expired": 0,
            "evicted": 0,
            "bytes": self.disk_bytes(),
            "max_bytes": self.max_bytes,
            "last_run": 0.0,
        }

    @staticmethod
    def key(kind: str, *parts) -> str:
        raw = "|".join(str(p) for p in parts)
        digest = hashlib.blake2b(raw.encode("utf-8"), digest_size=16)
        return "%s:%s" % (kind, digest.hexdigest())

    def get(self, kind: str, *parts, ttl: float | None = None, with_meta: bool = False, validator=None):
        ttl = DEFAULT_TTL.get(kind, 3600) if ttl is None else ttl
        key = self.key(kind, *parts)
        with self._lock:
            row = self._db.execute(
                "SELECT value, ts FROM entries WHERE key=?", (key,)).fetchone()
        if not row:
            self.misses += 1
            return None
        value, ts = row
        if ttl >= 0 and (time.time() - ts) > ttl:
            self.misses += 1
            return None
        try:
            decoded = json.loads(value)
        except (json.JSONDecodeError, RecursionError):
            self.misses += 1
            return None
        if validator is not None and not validator(decoded):
            self.misses += 1
            return None
        self.hits += 1
        return (decoded, ts) if with_meta else decoded

    def put(self, kind: str, *parts, value) -> None:
        key = self.key(kind, *parts)
        # The commit belongs inside the lock: it is part of the write, not a
        # separate thing that happens afterwards.
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO entries (key, kind, value, ts) "
                "VALUES (?,?,?,?)",
                (key, kind, json.dumps(value, ensure_ascii=False), time.time()),
            )
            self._db.commit()
            self.writes += 1
            if CACHE_MAINTENANCE_EVERY > 0 and self.writes % CACHE_MAINTENANCE_EVERY == 0:
                self._maintain_locked()

    def disk_bytes(self) -> int:
        """Database plus WAL, which is where the page bodies actually sit."""
        total = 0
        for path in (self.path, Path(str(self.path) + "-wal")):
            try:
                total += path.stat().st_size
            except OSError:
                pass
        return total

    def _checkpoint(self) -> None:
        try:
            cursor = self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            cursor.close()
        except sqlite3.Error:
            pass

    def _maintain_locked(self) -> None:
        """Delete expired rows, then enforce the size ceiling.

        Called under the write lock. Failure here must never turn a successful
        cache write into a request error: the cache is disposable.
        """
        now = time.time()
        expired = 0
        try:
            for kind, ttl in DEFAULT_TTL.items():
                if ttl < 0:
                    continue
                component = self._db.execute(
                    "DELETE FROM entries WHERE kind=? AND ts < ?", (kind, now - ttl)
                )
                expired += component.rowcount
                component.close()
            # Unknown kinds are still disposable; use the longest known TTL.
            longest = max((ttl for ttl in DEFAULT_TTL.values() if ttl >= 0), default=86400)
            component = self._db.execute(
                "DELETE FROM entries WHERE kind NOT IN (%s) AND ts < ?"
                % ",".join("?" for _ in DEFAULT_TTL),
                (*DEFAULT_TTL.keys(), now - longest),
            )
            expired += component.rowcount
            component.close()
            self._db.commit()
            self._checkpoint()
            evicted = 0
            if self.max_bytes > 0:
                target = max(1, int(self.max_bytes * CACHE_EVICT_TARGET))
                # The file does not shrink until VACUUM, so looping on file
                # size would delete every row on the first pass. Choose rows by
                # their stored payload, then compact once and re-check.
                for _attempt in range(3):
                    if self.disk_bytes() <= target:
                        break
                    rows = self._db.execute(
                        "SELECT key, length(value) FROM entries ORDER BY ts ASC"
                    ).fetchall()
                    if not rows:
                        break
                    payload = sum(size or 0 for _key, size in rows)
                    if payload <= target:
                        break
                    remaining = payload
                    doomed = []
                    for key, size in rows:
                        if remaining <= target:
                            break
                        doomed.append(key)
                        remaining -= size or 0
                    for start in range(0, len(doomed), 500):
                        batch = doomed[start:start + 500]
                        placeholders = ",".join("?" for _ in batch)
                        component = self._db.execute(
                            "DELETE FROM entries WHERE key IN (%s)" % placeholders, batch
                        )
                        evicted += component.rowcount
                        component.close()
                    self._db.commit()
                    try:
                        cursor = self._db.execute("VACUUM")
                        cursor.close()
                        self._db.commit()
                    except sqlite3.Error:
                        pass
                    self._checkpoint()
            self.maintenance = {
                "expired": expired,
                "evicted": evicted,
                "bytes": self.disk_bytes(),
                "max_bytes": self.max_bytes,
                "last_run": now,
            }
        except sqlite3.Error as exc:
            self.maintenance = {
                **self.maintenance,
                "error": type(exc).__name__,
                "bytes": self.disk_bytes(),
                "last_run": now,
            }

    def maintain(self) -> dict:
        """Run expiry and size enforcement now; useful for startup and tests."""
        with self._lock:
            self._maintain_locked()
            return dict(self.maintenance)

    def stats(self) -> dict:
        with self._lock:
            rows = self._db.execute(
                "SELECT kind, COUNT(*) FROM entries GROUP BY kind").fetchall()
            stored = {kind: count for kind, count in rows}
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
            "stored": stored,
            "bytes": self.disk_bytes(),
            "max_bytes": self.max_bytes,
            "maintenance": dict(self.maintenance),
            "path": str(self.path),
        }

    def purge(self, older_than_days: float = 30) -> int:
        cutoff = time.time() - older_than_days * 86400
        with self._lock:
            cursor = self._db.execute("DELETE FROM entries WHERE ts < ?", (cutoff,))
            self._db.commit()
        return cursor.rowcount

    def close(self):
        try:
            self._db.close()
        except Exception:
            pass


def valid_extract(value) -> bool:
    """Shape check for the stored extract row, used before counting a cache hit."""
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 3
        or not isinstance(value.get("text"), str)
    ):
        return False
    if any(
        not isinstance(value.get(field, {}), dict)
        for field in ("acquisition", "extraction", "content_assessment")
    ):
        return False
    pages = value.get("extraction", {}).get("pages", [])
    return isinstance(pages, list) and all(isinstance(page, dict) for page in pages)


class CacheView:
    """Request-local cache policy; never mutate the shared cache's behavior."""

    def __init__(self, cache, *, mode="use", max_age=None):
        self.cache, self.mode, self.max_age = cache, mode, max_age

    @staticmethod
    def _valid(kind, value):
        if kind == "extract":
            return valid_extract(value)
        if kind == "search" and (
                not isinstance(value, list) or any(
                    not isinstance(row, dict) or not isinstance(row.get("url", ""), str)
                    for row in value)):
            return False
        return True

    def get(self, kind, *parts, ttl=None, validator=None):
        if self.mode != "use":
            return None
        age = DEFAULT_TTL.get(kind, 3600) if ttl is None else ttl
        if self.max_age is not None:
            age = min(age, self.max_age)
        def accepted(value):
            return self._valid(kind, value) and (validator(value) if validator else True)
        hit = self.cache.get(kind, *parts, ttl=age, with_meta=True,
                             validator=accepted)
        if hit is None:
            return None
        value, retrieved = hit
        from datetime import datetime, timezone
        metadata = {"cached": True, "cache_age_seconds": round(time.time() - retrieved, 3),
                    "retrieved_at": datetime.fromtimestamp(retrieved, timezone.utc).isoformat(),
                    "cache_expires_at": datetime.fromtimestamp(
                        retrieved + age, timezone.utc).isoformat()}
        if isinstance(value, dict):
            value.update(metadata)
        elif isinstance(value, list):
            value = [dict(row, **metadata) if isinstance(row, dict) else row for row in value]
        return value

    def put(self, kind, *parts, value):
        if self.mode != "bypass":
            self.cache.put(kind, *parts, value=value)
