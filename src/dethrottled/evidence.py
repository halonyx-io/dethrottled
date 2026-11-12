"""Versioned, scoped extracted documents for focused reads and continuations."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path


class Documents:
    def __init__(self, path, *, ttl=604800, max_bytes=200_000_000):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.RLock()
        self.ttl, self.max_bytes = ttl, max_bytes
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY, namespace TEXT NOT NULL, url TEXT NOT NULL,
            digest TEXT NOT NULL, text TEXT NOT NULL, metadata TEXT NOT NULL, expires REAL NOT NULL,
            UNIQUE(namespace,url,digest))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY, namespace TEXT NOT NULL, filename TEXT NOT NULL,
            digest TEXT NOT NULL, data BLOB NOT NULL, expires REAL NOT NULL,
            UNIQUE(namespace,filename,digest))""")
        self.db.commit()

    def put(self, namespace, url, text, metadata):
        digest = hashlib.sha256(text.encode()).hexdigest()
        source_digest = (
            metadata.get("file_sha256")
            or metadata.get("source_sha256")
            or metadata.get("extraction", {}).get("source_sha256")
        )
        version_key = (
            hashlib.sha256((digest + "\0" + source_digest).encode()).hexdigest()
            if source_digest
            else digest
        )
        expires = time.time() + self.ttl
        metadata = {**metadata, "document_sha256": digest}
        with self.lock, self.db:
            self.db.execute("DELETE FROM documents WHERE expires<?", (time.time(),))
            self.db.execute(
                """INSERT INTO documents VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(namespace,url,digest) DO UPDATE SET
                metadata=excluded.metadata,expires=excluded.expires""",
                (
                    "doc_" + uuid.uuid4().hex,
                    namespace,
                    url,
                    version_key,
                    text,
                    json.dumps(metadata, ensure_ascii=False),
                    expires,
                ),
            )
            row = self.db.execute(
                "SELECT id FROM documents WHERE namespace=? AND url=? AND digest=?",
                (namespace, url, version_key),
            ).fetchone()
            total = self.db.execute(
                "SELECT COALESCE(SUM(length(CAST(text AS BLOB))+length(CAST(metadata AS BLOB))),0) "
                "FROM documents"
            ).fetchone()[0]
            if total > self.max_bytes:
                for identifier, size in self.db.execute(
                    "SELECT id,length(CAST(text AS BLOB))+length(CAST(metadata AS BLOB)) "
                    "FROM documents "
                    "WHERE id!=? ORDER BY expires",
                    (row[0],),
                ).fetchall():
                    self.db.execute("DELETE FROM documents WHERE id=?", (identifier,))
                    total -= size
                    if total <= self.max_bytes:
                        break
        return {
            "document_id": row[0],
            "document_sha256": digest,
            "document_chars": len(text),
            "document_expires_at": expires,
        }

    def reference(self, namespace, identifier, text):
        """Verify an existing canonical extraction without returning another text copy."""
        with self.lock:
            row = self.db.execute(
                "SELECT url,expires FROM documents WHERE namespace=? AND id=? "
                "AND expires>? AND text=?", (namespace, identifier, time.time(), text)
            ).fetchone()
        return ({"document_id": identifier, "url": row[0], "document_expires_at": row[1]}
                if row else None)

    def available(self, namespace, identifier):
        """Check a retained reference without materializing its full document."""
        with self.lock:
            return self.db.execute(
                "SELECT 1 FROM documents WHERE namespace=? AND id=? AND expires>?",
                (namespace, identifier, time.time()),
            ).fetchone() is not None

    def get(self, namespace, identifier):
        with self.lock:
            row = self.db.execute(
                "SELECT url,digest,text,metadata,expires FROM documents "
                "WHERE namespace=? AND id=? AND expires>?",
                (namespace, identifier, time.time()),
            ).fetchone()
        if row is None:
            return None
        return {
            "document_id": identifier,
            "url": row[0],
            "document_sha256": hashlib.sha256(row[2].encode()).hexdigest(),
            "text": row[2],
            "metadata": json.loads(row[3]),
            "document_expires_at": row[4],
        }

    def status(self, namespace, *, url=None, identifier=None):
        """Read scoped metadata without materializing retained document text."""
        with self.lock:
            if identifier is None:
                row = self.db.execute(
                    "SELECT id,url,digest,metadata,expires FROM documents "
                    "WHERE namespace=? AND url=? AND expires>? ORDER BY expires DESC LIMIT 1",
                    (namespace, url, time.time()),
                ).fetchone()
            else:
                row = self.db.execute(
                    "SELECT id,url,digest,metadata,expires FROM documents "
                    "WHERE namespace=? AND id=? AND expires>?",
                    (namespace, identifier, time.time()),
                ).fetchone()
        if row is None:
            return None
        doc_id, source, version, raw, expires = row
        metadata = json.loads(raw)
        return {
            "document_id": doc_id, "url": source, "document_expires_at": expires,
            "version_key": version, "document_sha256": metadata.get("document_sha256"),
            "retrieved_at": metadata.get("retrieved_at"),
            "published_at": metadata.get("published") or None,
            "last_modified": (metadata.get("origin_response") or {}).get("last_modified"),
            "quality": metadata.get("quality"), "tier": metadata.get("tier"),
            "source_partial": metadata.get("source_partial"),
        }

    def put_artifact(self, namespace, filename, data):
        digest = hashlib.sha256(data).hexdigest()
        with self.lock, self.db:
            self.db.execute("DELETE FROM artifacts WHERE expires<?", (time.time(),))
            self.db.execute(
                """INSERT INTO artifacts VALUES(?,?,?,?,?,?)
                ON CONFLICT(namespace,filename,digest) DO UPDATE SET expires=excluded.expires""",
                (
                    "file_" + uuid.uuid4().hex,
                    namespace,
                    filename,
                    digest,
                    data,
                    time.time() + self.ttl,
                ),
            )
            identifier = self.db.execute(
                "SELECT id FROM artifacts WHERE namespace=? AND filename=? AND digest=?",
                (namespace, filename, digest),
            ).fetchone()[0]
            total = self.db.execute(
                "SELECT COALESCE(SUM(length(data)),0) FROM artifacts"
            ).fetchone()[0]
            if total > self.max_bytes:
                for old, size in self.db.execute(
                    "SELECT id,length(data) FROM artifacts WHERE id!=? ORDER BY expires",
                    (identifier,),
                ).fetchall():
                    self.db.execute("DELETE FROM artifacts WHERE id=?", (old,))
                    total -= size
                    if total <= self.max_bytes:
                        break
        return identifier

    def get_artifact(self, namespace, identifier):
        with self.lock:
            row = self.db.execute(
                "SELECT filename,data,digest FROM artifacts WHERE namespace=? "
                "AND id=? AND expires>?",
                (namespace, identifier, time.time()),
            ).fetchone()
        return {"filename": row[0], "data": row[1], "file_sha256": row[2]} if row else None
