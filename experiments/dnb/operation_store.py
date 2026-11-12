"""Durable drive operation journal for the DNB worker.

The browser service keeps its mutation journal in memory. That is enough while
the process lives, but a restart forgets whether a mutation completed. This store
closes that window without inventing replayable outcomes:

- ``running`` is written before the drive is attempted.
- ``completed`` stores the response only after the drive returns successfully.
- ``unknown`` is written after any failure, including disconnect and timeout.

A retry sees ``running`` as in-progress, ``unknown`` as non-replayable, and
``completed`` as a safe replay when the payload fingerprint matches. A changed
payload under the same operation id is a conflict. Storage errors fail closed.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing

from session_owners import StoreUnavailable, owner_digest

COMPLETED_TTL = 24 * 60 * 60
UNKNOWN_TTL = 7 * 24 * 60 * 60
MAX_ROWS = 8192


class OperationConflict(Exception):
    """The same operation id was used with a different payload."""


class OperationState:
    RUNNING = "running"
    COMPLETED = "completed"
    UNKNOWN = "unknown"


class Operation:
    def __init__(self, state, fingerprints, result):
        self.state = state
        self.fingerprints = fingerprints
        self.result = result


class OperationStore:
    def __init__(self, path, *, max_rows=MAX_ROWS):
        self.path = str(path)
        self.max_rows = max_rows
        self.lock = threading.Lock()
        try:
            self.connection = sqlite3.connect(
                self.path, timeout=2.0, check_same_thread=False
            )
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=NORMAL")
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS operations (
                    owner TEXT NOT NULL,
                    session TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    fingerprints TEXT NOT NULL,
                    result TEXT,
                    created REAL NOT NULL,
                    updated REAL NOT NULL,
                    PRIMARY KEY(owner, session, operation_id)
                );
                CREATE INDEX IF NOT EXISTS operation_updated ON operations(updated);
                """
            )
            # DNB starts one worker per state directory. Any previous running
            # rows belong to the old worker and cannot report a final outcome.
            self.connection.execute(
                "UPDATE operations SET state=? WHERE state=?",
                (OperationState.UNKNOWN, OperationState.RUNNING),
            )
            self.connection.commit()
        except sqlite3.Error as exc:
            raise StoreUnavailable("operation store unavailable") from exc

    def _prune(self, now):
        self.connection.execute(
            "DELETE FROM operations WHERE (state='completed' AND updated<?) "
            "OR (state!='completed' AND updated<?)",
            (now - COMPLETED_TTL, now - UNKNOWN_TTL),
        )

    def begin(self, owner, session, operation_id, fingerprints):
        """Insert ``running`` or return the existing row.

        Raises OperationConflict when an existing row has a different payload.
        """
        digest = owner_digest(owner)
        encoded = json.dumps(list(fingerprints))
        now = time.time()
        try:
            with self.lock, self.connection, closing(self.connection.cursor()) as cursor:
                cursor.execute("BEGIN IMMEDIATE")
                self._prune(now)
                row = cursor.execute(
                    "SELECT state, fingerprints, result FROM operations "
                    "WHERE owner=? AND session=? AND operation_id=?",
                    (digest, session, operation_id),
                ).fetchone()
                if row is not None:
                    stored = json.loads(row[1])
                    if not any(item in stored for item in fingerprints):
                        raise OperationConflict("operation id payload conflict")
                    return Operation(row[0], stored, row[2])
                rows = cursor.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
                if rows >= self.max_rows:
                    # Losing an unexpired entry could allow a mutation to run twice.
                    raise StoreUnavailable("operation journal full")
                cursor.execute(
                    "INSERT INTO operations VALUES(?,?,?,?,?,?,?,?)",
                    (digest, session, operation_id, OperationState.RUNNING,
                     encoded, None, now, now),
                )
                return None
        except (sqlite3.Error, ValueError, TypeError) as exc:
            raise StoreUnavailable("operation store unavailable") from exc

    def complete(self, owner, session, operation_id, result):
        try:
            evidence = json.dumps(result)
            # Match the browser journal's evidence limit across restarts.
            if len(evidence) > 1_000_000:
                evidence = None
            with self.lock, self.connection:
                self.connection.execute(
                    "UPDATE operations SET state=?, result=?, updated=? "
                    "WHERE owner=? AND session=? AND operation_id=?",
                    (OperationState.COMPLETED, evidence, time.time(),
                     owner_digest(owner), session, operation_id),
                )
        except (sqlite3.Error, TypeError, ValueError) as exc:
            raise StoreUnavailable("operation store unavailable") from exc

    def mark_unknown(self, owner, session, operation_id):
        try:
            with self.lock, self.connection:
                self.connection.execute(
                    "UPDATE operations SET state=?, updated=? "
                    "WHERE owner=? AND session=? AND operation_id=?",
                    (OperationState.UNKNOWN, time.time(), owner_digest(owner),
                     session, operation_id),
                )
        except sqlite3.Error as exc:
            raise StoreUnavailable("operation store unavailable") from exc

    def release_session(self, owner, session):
        try:
            with self.lock, self.connection:
                self.connection.execute(
                    "DELETE FROM operations WHERE owner=? AND session=?",
                    (owner_digest(owner), session),
                )
        except sqlite3.Error as exc:
            raise StoreUnavailable("operation store unavailable") from exc

    def count(self):
        try:
            with self.lock:
                return self.connection.execute(
                    "SELECT COUNT(*) FROM operations"
                ).fetchone()[0]
        except sqlite3.Error as exc:
            raise StoreUnavailable("operation store unavailable") from exc

    def close(self):
        try:
            self.connection.close()
        except sqlite3.Error:
            pass
