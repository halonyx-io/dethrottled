"""Durable, scoped progressive read jobs. Cancellation stops scheduling new work."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, wait
from pathlib import Path

from .concurrency import ContextExecutor as ThreadPoolExecutor


class JobError(ValueError):
    def __init__(self, reason, status=404):
        self.status = status
        super().__init__(reason)


class Jobs:
    def __init__(self, path, max_bytes=200_000_000, *, bulk=False):
        self.max_bytes = max_bytes
        self.bulk = bulk
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.RLock()
        self.executions = {}
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
            CREATE TABLE IF NOT EXISTS job_payloads (
                job TEXT PRIMARY KEY, payload TEXT NOT NULL);
        """)
        self.db.execute("UPDATE jobs SET status='interrupted' WHERE status IN ('queued','running')")
        self.db.commit()

    def _check_capacity(self, namespace):
        if self.bulk:
            keys = tuple(self.executions)
            active = self.db.execute(
                "SELECT namespace FROM jobs WHERE id IN (" + ",".join("?" for _ in keys) + ")",
                keys,
            ).fetchall() if keys else []
        else:
            active = self.db.execute(
                "SELECT namespace FROM jobs WHERE status IN ('queued','running')"
            ).fetchall()
        if len(active) >= 4 or sum(row[0] == namespace for row in active) >= 2:
            raise JobError("read_jobs_busy", 429)

    def submit(self, namespace, payload, operation, read, workers):
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        now = time.time()
        with self.lock, self.db:
            expired = "expires<?"
            if self.bulk:
                expired += " AND status NOT IN ('queued','running')"
            self.db.execute(
                f"DELETE FROM results WHERE job IN (SELECT id FROM jobs WHERE {expired})", (now,)
            )
            self.db.execute(
                f"DELETE FROM job_payloads WHERE job IN (SELECT id FROM jobs WHERE {expired})",
                (now,),
            )
            self.db.execute(f"DELETE FROM jobs WHERE {expired}", (now,))
            if operation:
                previous = self.db.execute(
                    "SELECT id,fingerprint FROM jobs WHERE namespace=? AND operation=?",
                    (namespace, operation),
                ).fetchone()
                if previous:
                    if previous[1] != fingerprint:
                        raise JobError("operation_id_payload_conflict", 409)
                    return previous[0]
            self._check_capacity(namespace)
            identifier = "job_" + uuid.uuid4().hex
            self.db.execute(
                "INSERT INTO jobs "
                "(id,namespace,operation,fingerprint,status,total,created,expires) "
                "VALUES(?,?,?,?,?,?,?,?)",
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
            self.db.execute("INSERT INTO job_payloads VALUES(?,?)",
                            (identifier, json.dumps(payload)))
            execution = self.executions[identifier] = uuid.uuid4().hex
        self.pool.submit(self._run, identifier, payload["urls"], read, workers, execution)
        return identifier

    def _active(self, identifier, execution=None):
        with self.lock:
            if execution is not None and self.executions.get(identifier) != execution:
                return False
            row = self.db.execute("SELECT status FROM jobs WHERE id=?", (identifier,)).fetchone()
            return row is not None and row[0] in {"queued", "running"}

    def _unfinished(self, urls, finished):
        if not self.bulk:
            return ((url, [index]) for index, url in enumerate(urls) if index not in finished)
        groups = {}
        for index, url in enumerate(urls):
            if index not in finished:
                groups.setdefault(url, []).append(index)
        return iter(groups.items())

    def payload(self, namespace, identifier):
        with self.lock:
            row = self.db.execute(
                "SELECT payload FROM jobs JOIN job_payloads ON jobs.id=job_payloads.job "
                "WHERE id=? AND namespace=? AND "
                "(expires>? OR status IN ('queued','running'))",
                (identifier, namespace, time.time()),
            ).fetchone()
        if row is None:
            raise JobError("job_missing_or_expired")
        return json.loads(row[0])

    def resume(self, namespace, identifier, reader_factory, workers):
        """Explicitly restart unfinished reads; completed source positions survive."""
        self.get(namespace, identifier)
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT jobs.status,job_payloads.payload FROM jobs LEFT JOIN job_payloads "
                "ON jobs.id=job_payloads.job WHERE jobs.id=? AND namespace=?",
                (identifier, namespace),
            ).fetchone()
            if row[0] not in {"interrupted", "failed", "cancelled"}:
                raise JobError("job_not_resumable", 409)
            if not row[1]:
                raise JobError("legacy_job_payload_unavailable", 409)
            if self.bulk and identifier in self.executions:
                raise JobError("job_draining", 429)
            self._check_capacity(namespace)
            payload = json.loads(row[1])
            read = reader_factory(payload)
            self.db.execute("UPDATE jobs SET status='queued' WHERE id=?", (identifier,))
            execution = self.executions[identifier] = uuid.uuid4().hex
        self.pool.submit(self._run, identifier, payload["urls"], read, workers, execution)
        return self.get(namespace, identifier)

    def _run(self, identifier, urls, read, workers, execution):
        pending = {}
        try:
            with self.lock, self.db:
                if not self._active(identifier, execution):
                    return
                finished = {r[0] for r in self.db.execute(
                    "SELECT source_index FROM results WHERE job=?", (identifier,))}
                self.db.execute(
                    "UPDATE jobs SET status='running' WHERE id=? AND status='queued'", (identifier,)
                )
            remaining = self._unfinished(urls, finished)
            concurrency = 1 if self.bulk else 4
            while self._active(identifier, execution):
                while len(pending) < concurrency and self._active(identifier, execution):
                    source = next(remaining, None)
                    if source is None:
                        break
                    url, indices = source
                    pending[workers.submit(read, url)] = (url, indices)
                if not pending:
                    break
                done, _ = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                for future in done:
                    url, indices = pending.pop(future)
                    try:
                        row = future.result()
                    except Exception as exc:
                        row = {
                            "url": url,
                            "quality": "failed",
                            "failure_reason": type(exc).__name__,
                            "content": "",
                        }
                        if self.bulk:
                            from .dpr import evidence
                            row = evidence(url, row)
                    with self.lock, self.db:
                        if self._active(identifier, execution):
                            position = self.db.execute(
                                "SELECT COUNT(*) FROM results WHERE job=?", (identifier,)
                            ).fetchone()[0]
                            encoded = json.dumps(row, ensure_ascii=not self.bulk)
                            self.db.executemany(
                                "INSERT INTO results VALUES(?,?,?,?)",
                                ((identifier, position + offset, index, encoded)
                                 for offset, index in enumerate(indices)),
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
                                    self.db.execute(
                                        "DELETE FROM job_payloads WHERE job=?", (old_id,))
                                    self.db.execute("DELETE FROM jobs WHERE id=?", (old_id,))
                                    total -= size
                                    if total <= self.max_bytes:
                                        break
            with self.lock, self.db:
                if self._active(identifier, execution):
                    self.db.execute(
                        "UPDATE jobs SET status='completed' WHERE id=? AND status='running'",
                        (identifier,),
                    )
                    if self.bulk:
                        self.db.execute("UPDATE jobs SET expires=? WHERE id=?",
                                        (time.time() + 86400, identifier))
        except Exception:
            with self.lock, self.db:
                if self._active(identifier, execution):
                    self.db.execute(
                        "UPDATE jobs SET status='failed' WHERE id=? AND status='running'",
                        (identifier,),
                    )
        finally:
            for future in pending:
                future.cancel()  # In-flight origin requests may still finish.
            if self.bulk and pending:
                wait(pending)
            with self.lock:
                if self.executions.get(identifier) == execution:
                    self.executions.pop(identifier)

    def get(self, namespace, identifier, cursor=0, limit=10):
        with self.lock:
            available = "expires>?"
            if self.bulk:
                available = "(expires>? OR status IN ('queued','running'))"
            row = self.db.execute(
                "SELECT status,total,expires,EXISTS(SELECT 1 FROM job_payloads WHERE job=jobs.id) "
                f"FROM jobs WHERE namespace=? AND id=? AND {available}",
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
            "resume_available": bool(row[3]) and row[0] in {"interrupted", "failed", "cancelled"},
            "workflow": {"next_actions": [
                {"tool": "resume_fetch_job", "endpoint": "/jobs/resume",
                 "arguments": {"job_id": identifier},
                 "reason": "Resume unfinished sources; completed rows stay available."}
            ] if row[3] and row[0] in {"interrupted", "failed", "cancelled"} else []},
        }

    def cancel(self, namespace, identifier):
        self.get(namespace, identifier)
        with self.lock, self.db:
            cancelled = self.db.execute(
                "UPDATE jobs SET status='cancelled' WHERE id=? AND namespace=? "
                "AND status IN ('queued','running')",
                (identifier, namespace),
            )
            if self.bulk and cancelled.rowcount:
                self.db.execute("UPDATE jobs SET expires=? WHERE id=?",
                                (time.time() + 86400, identifier))
        return self.get(namespace, identifier)
