"""Optional semantic search cache: exact words are not the only way to ask.

This is deliberately separate from the evidence corpus. It stores only a small
query vector and the result menu for that query's filter context; it never
returns corpus passages and never changes the search query sent upstream. The
default is off because a false cache hit would silently answer a different
question.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
import time
from pathlib import Path

DEFAULT_THRESHOLD = float(os.getenv("DETHROTTLED_SEMANTIC_CACHE_THRESHOLD", "0.55"))
DEFAULT_TTL = float(os.getenv("DETHROTTLED_SEMANTIC_CACHE_TTL", str(6 * 3600)))


def configured():
    value = os.getenv("DETHROTTLED_SEMANTIC_CACHE", "").strip()
    if value.lower() in {"", "0", "false", "no", "off"}:
        return ""
    return value if value not in {"1", "true", "yes", "on"} else "default"


def _embed(text: str):
    from .corpus import embed
    return embed([text], query=True)[0]


def _cosine(left, right) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    lnorm = math.sqrt(sum(a * a for a in left))
    rnorm = math.sqrt(sum(b * b for b in right))
    return dot / max(lnorm * rnorm, 1e-9)


class SemanticCache:
    def __init__(self, path, *, threshold=DEFAULT_THRESHOLD, ttl=DEFAULT_TTL):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.threshold, self.ttl = threshold, ttl
        self._db = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS semantic_queries (
                    key TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    context TEXT NOT NULL,
                    vector TEXT NOT NULL,
                    value TEXT NOT NULL,
                    ts REAL NOT NULL
                )""")
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS semantic_context ON semantic_queries(context, ts)")
            self._db.commit()

    @staticmethod
    def key(context: str) -> str:
        return hashlib.blake2b(context.encode("utf-8"), digest_size=16).hexdigest()

    def get(self, query: str, context: str):
        with self._lock:
            rows = self._db.execute(
                "SELECT query, vector, value, ts FROM semantic_queries WHERE context=?",
                (self.key(context),),
            ).fetchall()
        if not rows:
            return None
        try:
            vector = _embed(query)
        except Exception:
            return None
        now = time.time()
        best = None
        for _stored_query, raw_vector, value, ts in rows:
            if self.ttl >= 0 and now - ts > self.ttl:
                continue
            try:
                similarity = _cosine(vector, json.loads(raw_vector))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if similarity >= self.threshold and (best is None or similarity > best[0]):
                best = (similarity, value, ts)
        if best is None:
            return None
        return {"value": json.loads(best[1]), "similarity": round(best[0], 4),
                "age_seconds": round(now - best[2], 2)}

    def put(self, query: str, context: str, value) -> None:
        try:
            vector = _embed(query)
        except Exception:
            return
        key = hashlib.blake2b(
            (self.key(context) + "\0" + query).encode("utf-8"), digest_size=16
        ).hexdigest()
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO semantic_queries "
                "(key, query, context, vector, value, ts) VALUES (?,?,?,?,?,?)",
                (key, query, self.key(context), json.dumps(vector), json.dumps(value), time.time()),
            )
            self._db.commit()

    def close(self):
        with self._lock:
            self._db.close()


_SHARED = None
_SHARED_LOCK = threading.Lock()


def shared():
    global _SHARED
    mode = configured()
    if not mode:
        return None
    with _SHARED_LOCK:
        if _SHARED is None:
            from . import paths
            path = (paths.data_dir() / "semantic-cache.sqlite"
                    if mode == "default" else mode)
            try:
                _SHARED = SemanticCache(path)
            except (OSError, sqlite3.Error):
                return None
        return _SHARED
