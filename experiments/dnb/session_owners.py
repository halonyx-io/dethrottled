"""Persisted owner binding for DNB drive sessions and their checkpoints.

The browser service keys sessions and checkpoints by session id. A known session
id alone must not let another verified owner open someone else's cookie jar, so
the worker records the first owner for each session and rejects a different
owner. Only a SHA-256 digest of the owner namespace is stored.

Storage failures fail closed: a drive request with a verified identity is refused
rather than silently skipping the binding.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from contextlib import closing


class OwnerMismatch(Exception):
    """The session id already belongs to a different verified owner."""


class StoreUnavailable(Exception):
    """The owner binding could not be read or written."""


def owner_digest(owner: str) -> str:
    return hashlib.sha256(owner.encode()).hexdigest()


class SessionOwners:
    def __init__(self, path):
        self.path = str(path)
        self.lock = threading.Lock()
        try:
            self.connection = sqlite3.connect(
                self.path, timeout=2.0, check_same_thread=False
            )
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=NORMAL")
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS session_owners (
                    session TEXT PRIMARY KEY,
                    owner_sha256 TEXT NOT NULL,
                    created REAL NOT NULL,
                    last_seen REAL NOT NULL
                );
                """
            )
            self.connection.commit()
        except sqlite3.Error as exc:
            raise StoreUnavailable("owner store unavailable") from exc

    def claim(self, session: str, owner: str) -> bool:
        """Bind ``session`` to ``owner``. True when newly bound, False when renewed.

        Raises OwnerMismatch when another owner already holds the session and
        StoreUnavailable on any storage error.
        """
        digest = owner_digest(owner)
        now = time.time()
        try:
            with self.lock, closing(self.connection.cursor()) as cursor:
                cursor.execute("BEGIN IMMEDIATE")
                row = cursor.execute(
                    "SELECT owner_sha256 FROM session_owners WHERE session=?",
                    (session,),
                ).fetchone()
                if row is None:
                    cursor.execute(
                        "INSERT INTO session_owners VALUES(?,?,?,?)",
                        (session, digest, now, now),
                    )
                    self.connection.commit()
                    return True
                if row[0] != digest:
                    self.connection.rollback()
                    raise OwnerMismatch("session owner mismatch")
                cursor.execute(
                    "UPDATE session_owners SET last_seen=? WHERE session=?",
                    (now, session),
                )
                self.connection.commit()
                return False
        except OwnerMismatch:
            raise
        except sqlite3.Error as exc:
            raise StoreUnavailable("owner store unavailable") from exc

    def release(self, session: str) -> None:
        try:
            with self.lock:
                self.connection.execute(
                    "DELETE FROM session_owners WHERE session=?", (session,)
                )
                self.connection.commit()
        except sqlite3.Error as exc:
            raise StoreUnavailable("owner store unavailable") from exc

    def owner_of(self, session: str) -> str | None:
        try:
            with self.lock:
                row = self.connection.execute(
                    "SELECT owner_sha256 FROM session_owners WHERE session=?",
                    (session,),
                ).fetchone()
                return row[0] if row else None
        except sqlite3.Error as exc:
            raise StoreUnavailable("owner store unavailable") from exc

    def count(self) -> int:
        try:
            with self.lock:
                return self.connection.execute(
                    "SELECT COUNT(*) FROM session_owners"
                ).fetchone()[0]
        except sqlite3.Error as exc:
            raise StoreUnavailable("owner store unavailable") from exc

    def close(self) -> None:
        try:
            self.connection.close()
        except sqlite3.Error:
            pass
