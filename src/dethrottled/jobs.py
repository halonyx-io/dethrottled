"""Durable, scoped progressive read jobs. Cancellation stops scheduling new work."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path


class JobError(ValueError):
    def __init__(self, reason, status=404):
        self.status = status
        super().__init__(reason)


class Jobs:
    def __init__(self, path, max_bytes=200_000_000):
        self.max_bytes = max_bytes
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="read-jobs")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, namespace TEXT NOT NULL, operation TEXT,
                fingerprint TEXT NOT NULL, status TEXT NOT NULL, total INTEGER NOT NULL,
                created REAL NOT NULL, expires REAL NOT NULL,
                UNIQUE(namespace,operation));
            CREATE TABLE IF NOT EXISTS results (
                job TEXT NOT NULL, position INTEGER NOT NULL, source_index INTEGER NOT NULL,
                value TEXT NOT NULL, PRIMARY KEY(job,position));
        """)
        self.db.execute("UPDATE jobs SET status='interrupted' WHERE status IN ('queued','running')")
        self.db.commit()

    def submit(self, namespace, payload, operation, read, workers):
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        now = time.time()
        with self.lock, self.db:
            self.db.execute(
                "DELETE FROM results WHERE job IN (SELECT id FROM jobs WHERE expires<?)", (now,)
            )
            self.db.execute("DELETE FROM jobs WHERE expires<?", (now,))
            if operation:
                previous = self.db.execute(
                    "SELECT id,fingerprint FROM jobs WHERE namespace=? AND operation=?",
                    (namespace, operation),
                ).fetchone()
                if previous:
                    if previous[1] != fingerprint:
                        raise JobError("operation_id_payload_conflict", 409)
                    return previous[0]
            active = self.db.execute(
                "SELECT namespace FROM jobs WHERE status IN ('queued','running')"
            ).fetchall()
            if len(active) >= 4 or sum(row[0] == namespace for row in active) >= 2:
                raise JobError("read_jobs_busy", 429)
            identifier = "job_" + uuid.uuid4().hex
            self.db.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    namespace,
                    operation or None,
                    fingerprint,
                    "queued",
                    len(payload["urls"]),
                    now,
                    now + 86400,
                ),
            )
        self.pool.submit(self._run, identifier, payload["urls"], read, workers)
        return identifier

    def _active(self, identifier):
        with self.lock:
            row = self.db.execute("SELECT status FROM jobs WHERE id=?", (identifier,)).fetchone()
            return row is not None and row[0] in {"queued", "running"}

    def _run(self, identifier, urls, read, workers):
        pending, next_index = {}, 0
        try:
            with self.lock, self.db:
                self.db.execute(
                    "UPDATE jobs SET status='running' WHERE id=? AND status='queued'", (identifier,)
                )
            while self._active(identifier):
                while next_index < len(urls) and len(pending) < 4 and self._active(identifier):
                    index = next_index
                    pending[workers.submit(read, urls[index])] = index
                    next_index += 1
                if not pending:
                    break
                done, _ = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                for future in done:
                    index = pending.pop(future)
                    try:
                        row = future.result()
                    except Exception as exc:
                        row = {
                            "url": urls[index],
                            "quality": "failed",
                            "failure_reason": type(exc).__name__,
                            "content": "",
                        }
                    with self.lock, self.db:
                        if self._active(identifier):
                            position = self.db.execute(
                                "SELECT COUNT(*) FROM results WHERE job=?", (identifier,)
                            ).fetchone()[0]
                            self.db.execute(
                                "INSERT INTO results VALUES(?,?,?,?)",
                                (identifier, position, index, json.dumps(row)),
                            )
                            total = self.db.execute(
                                "SELECT COALESCE(SUM(length(CAST(value AS BLOB))),0) FROM results"
                            ).fetchone()[0]
                            if total > self.max_bytes:
                                old = self.db.execute(
                                    "SELECT id FROM jobs WHERE status NOT IN "
                                    "('queued','running') ORDER BY created"
                                ).fetchall()
                                for (old_id,) in old:
                                    size = self.db.execute(
                                        "SELECT COALESCE(SUM(length(CAST(value AS BLOB))),0) "
                                        "FROM results WHERE job=?",
                                        (old_id,),
                                    ).fetchone()[0]
                                    self.db.execute("DELETE FROM results WHERE job=?", (old_id,))
                                    self.db.execute("DELETE FROM jobs WHERE id=?", (old_id,))
                                    total -= size
                                    if total <= self.max_bytes:
                                        break
            with self.lock, self.db:
                self.db.execute(
                    "UPDATE jobs SET status='completed' WHERE id=? AND status='running'",
                    (identifier,),
                )
        except Exception:
            with self.lock, self.db:
                self.db.execute(
                    "UPDATE jobs SET status='failed' WHERE id=? AND status='running'", (identifier,)
                )
        finally:
            for future in pending:
                future.cancel()  # In-flight origin requests may still finish.

    def get(self, namespace, identifier, cursor=0, limit=10):
        with self.lock:
            row = self.db.execute(
                "SELECT status,total,expires FROM jobs WHERE namespace=? AND id=? AND expires>?",
                (namespace, identifier, time.time()),
            ).fetchone()
            if row is None:
                raise JobError("job_missing_or_expired")
            completed = self.db.execute(
                "SELECT COUNT(*) FROM results WHERE job=?", (identifier,)
            ).fetchone()[0]
            records = self.db.execute(
                "SELECT source_index,value FROM results WHERE job=? "
                "AND position>=? ORDER BY position LIMIT ?",
                (identifier, cursor, limit),
            ).fetchall()
        return {
            "job_id": identifier,
            "status": row[0],
            "total": row[1],
            "completed": completed,
            "expires_at": row[2],
            "results": [{"source_index": record[0], **json.loads(record[1])} for record in records],
            "next_cursor": cursor + len(records),
            "poll_after_ms": 1000 if row[0] in {"queued", "running"} else None,
            "cancellation": "cooperative; already running reads may finish",
        }

    def cancel(self, namespace, identifier):
        self.get(namespace, identifier)
        with self.lock, self.db:
            self.db.execute(
                "UPDATE jobs SET status='cancelled' WHERE id=? AND namespace=? "
                "AND status IN ('queued','running')",
                (identifier, namespace),
            )
        return self.get(namespace, identifier)
