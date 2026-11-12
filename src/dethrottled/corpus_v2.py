"""Normalized public corpus, durable jobs, atomic promotion and bounded retrieval.

Full extraction lives in Documents. SQLite stores lexical passages once and
versioned vectors separately. v1 files are never opened for writing here.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from . import paths
from .corpus_chunks import VERSION as CHUNKER_VERSION
from .corpus_config import integer
from .corpus_index import IndexWorker
from .evidence import Documents

SCHEMA = 2


def _bounded_completeness(value):
    """Keep diagnostic scalars, never structural samples or source text."""
    if not isinstance(value, dict):
        return {}
    result = {}
    for key in ("status", "assessment"):
        if isinstance(value.get(key), str):
            result[key] = value[key][:64]
    for key in ("sampled_anchors", "missing_samples"):
        item = value.get(key)
        if type(item) is int and 0 <= item <= 1_000_000:
            result[key] = item
    if isinstance(value.get("selection_changed"), bool):
        result["selection_changed"] = value["selection_changed"]
    compared = value.get("compared_extractors")
    if isinstance(compared, (list, tuple)):
        result["compared_extractors"] = [item[:64] for item in compared[:8]
                                         if isinstance(item, str)]
    return result


def canonical(url):
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username is not None:
        raise ValueError("public corpus requires an HTTP URL without credentials")
    secret_names = {
        "token",
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "password",
        "signature",
        "sig",
        "x-amz-signature",
        "x-amz-credential",
        "x-goog-signature",
        "credential",
    }
    if any(key.casefold() in secret_names for key, _ in parse_qsl(parts.query)):
        raise ValueError("credential-bearing URLs cannot enter the public corpus")
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, "")
    )


class CorpusV2(IndexWorker):
    model_name = "minilm"

    def __init__(self, path=None, *, documents=None, models=None):
        from .corpus import MultilingualCorpus

        self.path = Path(path or paths.data_dir() / "corpus-v2.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.documents = documents or Documents(paths.data_dir() / "evidence.sqlite")
        self.models = models or (
            ["minilm", MultilingualCorpus.model_name]
            if os.getenv("DETHROTTLED_MULTILINGUAL_CORPUS") == "1"
            else ["minilm"]
        )
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA auto_vacuum=INCREMENTAL")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_size_limit=16777216")
        self.db.execute("PRAGMA wal_autocheckpoint=512")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS sources(
            id TEXT PRIMARY KEY, url TEXT NOT NULL, digest TEXT NOT NULL,
            document_id TEXT NOT NULL, namespace TEXT NOT NULL,
            title TEXT NOT NULL, provenance TEXT NOT NULL,
            created REAL NOT NULL, touched REAL NOT NULL, active INTEGER NOT NULL DEFAULT 0,
            state TEXT NOT NULL, coverage TEXT NOT NULL,
            UNIQUE(url,digest));
          CREATE INDEX IF NOT EXISTS source_url ON sources(url,active);
          CREATE UNIQUE INDEX IF NOT EXISTS active_url ON sources(url) WHERE active=1;
          CREATE TABLE IF NOT EXISTS passages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            start INTEGER NOT NULL, end INTEGER NOT NULL, text TEXT NOT NULL,
            digest TEXT NOT NULL, heading TEXT NOT NULL, page INTEGER,
            UNIQUE(source_id,start));
          CREATE INDEX IF NOT EXISTS passage_digest ON passages(digest);
          CREATE TABLE IF NOT EXISTS embeddings(
            passage_id INTEGER NOT NULL REFERENCES passages(id) ON DELETE CASCADE,
            model TEXT NOT NULL, dimensions INTEGER NOT NULL, vector BLOB NOT NULL,
            revision TEXT NOT NULL,
            PRIMARY KEY(passage_id,model));
          CREATE INDEX IF NOT EXISTS embedding_model ON embeddings(model);
          CREATE TABLE IF NOT EXISTS index_jobs(
            source_id TEXT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
            state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            lease TEXT, expires REAL NOT NULL DEFAULT 0, available REAL NOT NULL DEFAULT 0,
            error TEXT, updated REAL NOT NULL);
          CREATE INDEX IF NOT EXISTS job_state ON index_jobs(state,available);
          CREATE TABLE IF NOT EXISTS public_documents(
            document_id TEXT PRIMARY KEY, namespace TEXT NOT NULL, expires REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS migration_seen(
            document_id TEXT PRIMARY KEY,expires REAL NOT NULL);
          CREATE VIRTUAL TABLE IF NOT EXISTS passage_fts USING fts5(
            text,heading,content='passages',content_rowid='id');
          CREATE TRIGGER IF NOT EXISTS passage_insert AFTER INSERT ON passages BEGIN
            INSERT INTO passage_fts(rowid,text,heading) VALUES(new.id,new.text,new.heading); END;
          CREATE TRIGGER IF NOT EXISTS passage_delete AFTER DELETE ON passages BEGIN
            INSERT INTO passage_fts(passage_fts,rowid,text,heading)
            VALUES('delete',old.id,old.text,old.heading); END;
        """)
        expected = {"schema": str(SCHEMA), "chunker": CHUNKER_VERSION}
        for key, value in expected.items():
            old = self.db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
            if old and old[0] != value:
                raise ValueError("unsupported corpus " + key + ": " + old[0])
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES(?,?)", (key, value))
        # Repair references written by 1.5.0 when an unchanged public source
        # was acquired in another caller namespace. The public registry already
        # records the verified namespace for each retained document ID.
        if not self.db.execute(
            "SELECT 1 FROM metadata WHERE key='document_namespace_repair'"
        ).fetchone():
            self.db.execute(
                "UPDATE sources SET namespace=(SELECT namespace FROM public_documents "
                "WHERE document_id=sources.document_id) WHERE EXISTS "
                "(SELECT 1 FROM public_documents WHERE document_id=sources.document_id "
                "AND namespace!=sources.namespace)"
            )
            self.db.execute("INSERT INTO metadata VALUES('document_namespace_repair','1')")
        self.db.commit()
        self.revisions = {
            model: (
                os.getenv("DETHROTTLED_MINILM_REVISION", "1110a243fdf4706b3f48f1d95db1a4f5529b4d41")
                if model == "minilm"
                else os.getenv(
                    "DETHROTTLED_E5_REVISION", "614241f622f53c4eeff9890bdc4f31cfecc418b3"
                )
            )
            for model in self.models
        }
        self.db.execute("INSERT OR IGNORE INTO metadata VALUES('generation','0')")
        self.db.commit()
        self.matrices = {}
        self.matrix_generation = None
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.worker = None
        self.last_prune = 0.0
        self.maintenance_pending = False

    def enqueue(self, url, title, text, metadata=None):
        """Durably admit public content; no tokenization or inference on this path."""
        metadata = dict(metadata or {})
        if (
            metadata.get("corpus_visibility") != "public"
            or metadata.get("authenticated")
            or metadata.get("private")
        ):
            return {"accepted": False, "reason": "public_provenance_required"}
        if metadata.get("quality") in {"failed", "thin"} or metadata.get("content_status") in {
            "navigation_only",
            "image_content",
        }:
            return {"accepted": False, "reason": "ineligible_content"}
        harvest_limit = integer("HARVEST_CHARS", 8_000_000)
        if len(text) > harvest_limit:
            return {
                "accepted": False,
                "reason": "harvest_limit",
                "source_chars": len(text),
                "limit_chars": harvest_limit,
            }
        existing_id = metadata.get("document_id")
        existing_namespace = metadata.get("_document_namespace")
        metadata = {
            key: value
            for key, value in metadata.items()
            if key
            in {
                "corpus_visibility",
                "tier",
                "retrieved_at",
                "origin_response",
                "final_url",
                "source_sha256",
                "source_partial",
                "warnings",
                "content_status",
                "migration",
                "quality",
                "content_assessment",
                "extraction",
                "acquisition",
            }
        }
        extraction = metadata.get("extraction", {})
        if extraction:
            metadata["extraction"] = {
                key: extraction[key]
                for key in ("partial", "method", "ocr_word_confidence", "warnings")
                if key in extraction
            }
            completeness = _bounded_completeness(extraction.get("completeness"))
            if completeness:
                metadata["extraction"]["completeness"] = completeness
            if extraction.get("pages"):
                metadata["extraction"]["pages"] = [
                    {key: page[key] for key in ("page", "method", "confidence") if key in page}
                    for page in extraction["pages"]
                ]
        url = canonical(url)
        if not text.strip():
            return {"accepted": False, "reason": "empty_text"}
        now = time.time()
        record = (
            self.documents.reference(existing_namespace, existing_id, text)
            if existing_id and existing_namespace
            else None
        )
        if record and canonical(record["url"]) == url:
            namespace = existing_namespace
        else:
            namespace = "corpus-public"
            record = self.documents.put(namespace, url, text, metadata)
        version = {
            key: metadata.get(key)
            for key in ("source_sha256", "source_partial", "quality", "extraction", "warnings")
        }
        digest = hashlib.sha256(
            (
                text
                + "\0"
                + title
                + "\0"
                + CHUNKER_VERSION
                + "\0"
                + json.dumps(version, sort_keys=True)
                + "\0"
                + "|".join(model + self.revisions[model] for model in self.models)
            ).encode()
        ).hexdigest()
        identifier = hashlib.sha256((url + "\0" + digest).encode()).hexdigest()
        coverage = {
            "harvested_chars": len(text),
            "retained_chars": len(text),
            "lexical_chars": 0,
            "embedded_passages": {},
            "chunker": CHUNKER_VERSION,
            "source_partial": bool(metadata.get("source_partial")),
            "warnings": metadata.get("warnings", []),
            "omissions": [],
        }
        with self.lock, self.db:
            count = self.db.execute(
                "SELECT count(*) FROM index_jobs WHERE state IN ('pending','running')"
            ).fetchone()[0]
            known = self.db.execute(
                "SELECT state FROM sources WHERE id=?", (identifier,)
            ).fetchone()
            if count >= integer("QUEUE", 256) and not known:
                return {"accepted": False, "reason": "queue_full", "retryable": True}
            self.db.execute(
                "INSERT INTO public_documents VALUES(?,?,?) "
                "ON CONFLICT(document_id) DO UPDATE SET expires=excluded.expires",
                (record["document_id"], namespace, record["document_expires_at"]),
            )
            self.db.execute(
                "INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,0,'pending',?) "
                "ON CONFLICT(id) DO UPDATE SET touched=excluded.touched,"
                "document_id=excluded.document_id,namespace=excluded.namespace,provenance=excluded.provenance",
                (
                    identifier,
                    url,
                    digest,
                    record["document_id"],
                    namespace,
                    title,
                    json.dumps(metadata),
                    now,
                    now,
                    json.dumps(coverage),
                ),
            )
            # Most recent acquisition wins, including an unchanged old version
            # being observed again while another version is pending.
            self.db.execute(
                "UPDATE sources SET state='superseded' WHERE url=? AND id!=? AND active=0",
                (url, identifier),
            )
            self.db.execute(
                "UPDATE index_jobs SET state='superseded',lease=NULL "
                "WHERE source_id IN (SELECT id FROM sources WHERE url=? AND id!=?) "
                "AND state IN ('pending','running')",
                (url, identifier),
            )
            if known and known[0] == "ready":
                self.db.execute("UPDATE sources SET active=0 WHERE url=?", (url,))
                self.db.execute("UPDATE sources SET active=1 WHERE id=?", (identifier,))
                return {"accepted": True, "unchanged": True, "source_id": identifier}
            self.db.execute("UPDATE sources SET state='pending' WHERE id=?", (identifier,))
            self.db.execute(
                "INSERT INTO index_jobs(source_id,state,updated) VALUES(?,'pending',?) "
                "ON CONFLICT(source_id) DO UPDATE SET "
                "state=CASE WHEN index_jobs.state='running' THEN 'running' ELSE 'pending' END,"
                "attempts=CASE WHEN index_jobs.state='failed' THEN 0 ELSE attempts END,"
                "available=0,updated=excluded.updated",
                (identifier, now),
            )
        self.wake.set()
        return {"accepted": True, "source_id": identifier, "unchanged": False}

    def add(self, url, title, text):
        # Explicit library insertion is an operator assertion of public visibility.
        report = self.enqueue(url, title, text, {"corpus_visibility": "public"})
        if report["accepted"]:
            self.start()
        return int(report["accepted"])

    def _claim(self):
        now, lease = time.time(), uuid.uuid4().hex
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute(
                "UPDATE index_jobs SET state='pending',lease=NULL "
                "WHERE state='running' AND expires<?",
                (now,),
            )
            if self.db.execute("SELECT 1 FROM index_jobs WHERE state='running'").fetchone():
                return None
            row = self.db.execute(
                "SELECT s.* FROM index_jobs j JOIN sources s ON s.id=j.source_id "
                "WHERE j.state='pending' AND j.available<=? "
                "ORDER BY j.updated LIMIT 1",
                (now,),
            ).fetchone()
            if row:
                self.db.execute(
                    "UPDATE index_jobs SET state='running',attempts=attempts+1,"
                    "lease=?,expires=?,updated=? WHERE source_id=?",
                    (lease, now + 120, now, row["id"]),
                )
                return dict(row), lease
        return None

    def _heartbeat(self, identifier, lease):
        with self.lock, self.db:
            changed = self.db.execute(
                "UPDATE index_jobs SET expires=? WHERE source_id=? AND lease=? AND state='running'",
                (time.time() + 120, identifier, lease),
            ).rowcount
        if not changed or self.stop_event.is_set():
            raise InterruptedError("index lease superseded or worker stopping")

    def start(self):
        with self.lock:
            if self.worker and self.worker.is_alive():
                return
            self.stop_event.clear()

            def work():
                while not self.stop_event.is_set():
                    try:
                        if self.maintenance_pending or time.time() - self.last_prune > integer(
                            "PRUNE_SECONDS", 3600
                        ):
                            self.prune()
                            self.last_prune = time.time()
                        if self.run_one():
                            self.prune()
                            continue
                    except (sqlite3.Error, OSError):
                        pass
                    self.wake.wait(1)
                    self.wake.clear()

            self.worker = threading.Thread(target=work, daemon=True, name="corpus-index")
            import atexit

            atexit.register(self.stop)
            self.worker.start()

    def stop(self):
        self.stop_event.set()
        self.wake.set()
        if self.worker:
            self.worker.join(timeout=30)

    def prune(self):
        """Remove at most 32 whole sources per transaction, off request paths."""
        cutoff = time.time() - integer("RETENTION_DAYS", 90) * 86400
        maximum = integer("MAX_PASSAGES", 50000)
        disk_cap = integer("DB_MIB", 512) * 1024**2
        removed = 0
        with self.lock, self.db:
            registry_removed = self.db.execute(
                "DELETE FROM public_documents WHERE document_id IN "
                "(SELECT document_id FROM public_documents WHERE expires<? LIMIT 256)",
                (time.time(),),
            ).rowcount
            migration_removed = self.db.execute(
                "DELETE FROM migration_seen WHERE document_id IN "
                "(SELECT document_id FROM migration_seen WHERE expires<? LIMIT 256)",
                (time.time(),),
            ).rowcount
            for _ in range(32):
                # Expired sources and seven-day failed/superseded diagnostics
                # share the same batch bound as resource-pressure pruning.
                oldest = self.db.execute(
                    "SELECT id FROM sources WHERE touched<? OR (active=0 AND state IN "
                    "('failed','superseded') AND touched<?) ORDER BY touched LIMIT 1",
                    (cutoff, time.time() - 7 * 86400),
                ).fetchone()
                if oldest:
                    self.db.execute("DELETE FROM sources WHERE id=?", (oldest[0],))
                    removed += 1
                    continue
                counts = self.db.execute(
                    "SELECT model,count(*) FROM embeddings GROUP BY model"
                ).fetchall()
                pages = self.db.execute("PRAGMA page_count").fetchone()[0]
                free = self.db.execute("PRAGMA freelist_count").fetchone()[0]
                size = (pages - free) * self.db.execute("PRAGMA page_size").fetchone()[0]
                if size <= disk_cap and all(row[1] <= maximum for row in counts):
                    break
                oldest = self.db.execute(
                    "SELECT id FROM sources WHERE active=1 ORDER BY touched LIMIT 1"
                ).fetchone()
                if not oldest:
                    break
                self.db.execute("DELETE FROM sources WHERE id=?", (oldest[0],))
                removed += 1
            self.maintenance_pending = (
                removed == 32 or registry_removed == 256 or migration_removed == 256
            )
            if removed:
                self.db.execute(
                    "UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='generation'"
                )
        with self.lock:
            self.db.execute("PRAGMA wal_checkpoint(PASSIVE)")
            self.db.execute("PRAGMA incremental_vacuum(256)")
        return removed

    def public_document(self, identifier):
        with self.lock:
            row = self.db.execute(
                "SELECT namespace FROM public_documents WHERE document_id=? AND expires>?",
                (identifier, time.time()),
            ).fetchone()
        return self.documents.get(row[0], identifier) if row else None

    def document_available(self, identifier):
        with self.lock:
            row = self.db.execute(
                "SELECT namespace FROM public_documents WHERE document_id=? AND expires>?",
                (identifier, time.time()),
            ).fetchone()
        return self.documents.available(row[0], identifier) if row else False

    def reindex(self, *, limit=32, failed_only=False):
        """Resume a bounded repair campaign without cancelling in-flight work."""
        key = "retry_cursor" if failed_only else "reindex_cursor"
        with self.lock, self.db:
            cursor = self.db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
            after = cursor[0] if cursor else ""
            condition = (
                "id IN (SELECT source_id FROM index_jobs WHERE state='failed')"
                if failed_only
                else "active=1"
            )
            rows = self.db.execute(
                "SELECT id FROM sources WHERE " + condition + " AND id>? ORDER BY id LIMIT ?",
                (after, max(1, min(limit, 256))),
            ).fetchall()
            queued = self.db.execute(
                "SELECT count(*) FROM index_jobs WHERE state IN ('pending','running')"
            ).fetchone()[0]
            added = 0
            for row in rows:
                job = self.db.execute(
                    "SELECT state FROM index_jobs WHERE source_id=?", (row[0],)
                ).fetchone()
                if not job or job[0] not in {"pending", "running"}:
                    if queued >= integer("QUEUE", 256):
                        break
                    self.db.execute(
                        "INSERT INTO index_jobs(source_id,state,updated) VALUES(?,'pending',?) "
                        "ON CONFLICT(source_id) DO UPDATE SET state='pending',attempts=0,"
                        "lease=NULL,available=0,updated=excluded.updated",
                        (row[0], time.time()),
                    )
                    queued += 1
                    added += 1
                self.db.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)", (key, row[0]))
        self.wake.set()
        return added

    def stats(self):
        with self.lock:
            rows = self.db.execute(
                "SELECT e.model,count(*),count(DISTINCT p.source_id) "
                "FROM embeddings e JOIN passages p ON p.id=e.passage_id "
                "JOIN sources s ON s.id=p.source_id WHERE s.active=1 "
                "GROUP BY e.model"
            ).fetchall()
        return {row[0]: {"passages": row[1], "pages": row[2]} for row in rows}

    def status(self):
        with self.lock:
            jobs = dict(self.db.execute("SELECT state,count(*) FROM index_jobs GROUP BY state"))
            sources = self.db.execute("SELECT count(*) FROM sources WHERE active=1").fetchone()[0]
            keys = ("harvested_chars", "retained_chars", "lexical_chars", "embedded_chars")
            totals = {
                key: self.db.execute(
                    "SELECT coalesce(sum(json_extract(coverage,?)),0) FROM sources WHERE active=1",
                    ("$." + key,),
                ).fetchone()[0]
                for key in keys
            }
            vector_bytes = sum(
                value[0].nbytes + value[1].nbytes for value in self.matrices.values()
            )
            refs = self.db.execute(
                "SELECT document_id,namespace,json_extract(coverage,'$.retained_chars') "
                "FROM sources WHERE active=1"
            ).fetchall()
            recent_errors = [
                dict(row)
                for row in self.db.execute(
                    "SELECT state,attempts,error,updated FROM index_jobs WHERE error IS NOT NULL "
                    "ORDER BY updated DESC LIMIT 5"
                )
            ]
        retained = [(row[2] or 0) for row in refs if self.documents.available(row[1], row[0])]
        disk = {
            suffix or "database": Path(str(self.path) + suffix).stat().st_size
            for suffix in ("", "-wal", "-shm")
            if Path(str(self.path) + suffix).exists()
        }
        return {
            "schema": SCHEMA,
            "chunker": CHUNKER_VERSION,
            "jobs": jobs,
            "active_sources": sources,
            "models": self.stats(),
            "disk_bytes": disk,
            "disk_soft_target_exceeded": sum(disk.values()) > integer("DB_MIB", 512) * 1024**2,
            "retained_documents": {
                "available": len(retained),
                "unavailable": len(refs) - len(retained),
                "current_chars": sum(retained),
            },
            "coverage_is_indexing_snapshot": True,
            "coverage_chars": totals,
            "recent_job_errors": recent_errors,
            "maintenance": {"pending": self.maintenance_pending,
                            "source_batch": 32, "registry_batch": 256},
            "resident_vector_bytes": vector_bytes,
            "scan_block_rows": 1024,
            "limits": {
                "passages_per_model": integer("MAX_PASSAGES", 50000),
                "vector_budget_bytes": integer("VECTOR_MIB", 256) * 1024**2,
                "retention_days": integer("RETENTION_DAYS", 90),
                "database_soft_bytes": integer("DB_MIB", 512) * 1024**2,
                "harvest_chars_per_source": integer("HARVEST_CHARS", 8_000_000),
                "lexical_chars_per_source": integer("LEXICAL_CHARS", 2_000_000),
            },
            "model_revisions": self.revisions,
            "retention_note": "full-document expiry is independent; passages retain offsets",
        }

    def _records(self, identifiers):
        if not identifiers:
            return {}
        placeholders = ",".join("?" for _ in identifiers)
        with self.lock:
            rows = self.db.execute(
                "SELECT p.*,s.url,s.title,s.document_id,s.namespace,s.coverage,s.provenance,"
                "s.touched FROM passages p JOIN sources s ON s.id=p.source_id "
                "WHERE s.active=1 AND s.touched>=? AND p.id IN (" + placeholders + ")",
                [time.time() - integer("RETENTION_DAYS", 90) * 86400, *identifiers],
            ).fetchall()
        out = {}
        for row in rows:
            item = dict(row)
            item["corpus_expires_at"] = item["touched"] + integer("RETENTION_DAYS", 90) * 86400
            item["coverage"] = json.loads(item["coverage"])
            item["provenance"] = json.loads(item["provenance"])
            item.pop("namespace")
            item.pop("digest")
            out[item["id"]] = item
        return out

    def search(self, query, *, limit=10, per_url=2, floor=None, domains=None, mode="auto",
               support="standard"):
        from .corpus_query import search

        return search(
            self, query, limit=limit, per_url=per_url, floor=floor, domains=domains, mode=mode,
            support=support,
        )
