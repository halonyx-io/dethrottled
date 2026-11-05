"""Bounded, restartable local-only migration of retained public documents."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from . import paths
from .corpus_v2 import CorpusV2


def backfill(store, evidence_path, *, limit=32, trust_legacy_public=False):
    """Never re-fetch, and never infer public visibility from a legacy v1 row."""
    path = Path(evidence_path)
    if not path.exists():
        return {"scanned": 0, "accepted": 0, "missing_store": True}
    with store.lock:
        cursor = store.db.execute(
            "SELECT value FROM metadata WHERE key='migration_cursor'"
        ).fetchone()
    after = int(cursor[0]) if cursor else 0
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute("ATTACH DATABASE ? AS progress", (store.path.resolve().as_uri() + "?mode=ro",))
        rows = db.execute(
            "SELECT rowid,* FROM documents WHERE id NOT IN "
            "(SELECT document_id FROM progress.migration_seen) ORDER BY rowid LIMIT ?",
            (max(1, min(limit, 256)),),
        ).fetchall()
        newer = {
            row["id"]
            for row in rows
            if db.execute(
                "SELECT 1 FROM documents WHERE url=? AND expires>? AND "
                "(json_extract(metadata,'$.corpus_visibility')='public' OR ?) "
                "AND NOT coalesce(json_extract(metadata,'$.private'),0) "
                "AND NOT coalesce(json_extract(metadata,'$.authenticated'),0) LIMIT 1",
                (row["url"], row["expires"], int(trust_legacy_public)),
            ).fetchone()
        }
    finally:
        db.close()
    counts = {
        "scanned": 0,
        "accepted": 0,
        "expired": 0,
        "unknown_visibility": 0,
        "private": 0,
        "partial": 0,
        "invalid": 0,
        "obsolete": 0,
        "cursor": after,
    }
    import time

    for row in rows:
        metadata = json.loads(row["metadata"])
        if row["expires"] <= time.time():
            counts["expired"] += 1
        elif metadata.get("private") or metadata.get("authenticated"):
            counts["private"] += 1
        elif metadata.get("corpus_visibility") != "public" and not trust_legacy_public:
            counts["unknown_visibility"] += 1
        elif row["id"] in newer:
            counts["obsolete"] += 1
        else:
            metadata["corpus_visibility"] = "public"
            metadata["migration"] = "retained-document"
            metadata["document_id"] = row["id"]
            metadata["_document_namespace"] = row["namespace"]
            try:
                result = store.enqueue(row["url"], metadata.get("title", ""), row["text"], metadata)
            except ValueError:
                counts["invalid"] += 1
            else:
                if not result["accepted"]:
                    if result.get("retryable"):
                        counts["blocked"] = result["reason"]
                        break
                    counts["invalid"] += 1
                else:
                    counts["accepted"] += 1
                    counts["partial"] += bool(metadata.get("source_partial"))
        counts["cursor"] = row["rowid"]
        counts["scanned"] += 1
        with store.lock, store.db:
            store.db.execute(
                "INSERT OR REPLACE INTO migration_seen VALUES(?,?)",
                (row["id"], max(time.time(), row["expires"]) + 7 * 86400),
            )
            store.db.execute(
                "INSERT OR REPLACE INTO metadata VALUES('migration_cursor',?)",
                (str(counts["cursor"]),),
            )
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=32)
    parser.add_argument(
        "--trust-legacy-public",
        action="store_true",
        help="operator assertion: ALL selected legacy documents are public",
    )
    parser.add_argument("--reset-cursor", action="store_true")
    parser.add_argument("--drain", action="store_true", help="index currently queued work and exit")
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="requeue up to --limit active sources from retained full text",
    )
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()
    store = CorpusV2()
    if args.reset_cursor:
        with store.lock, store.db:
            store.db.execute("DELETE FROM metadata WHERE key='migration_cursor'")
            store.db.execute("DELETE FROM migration_seen")
            store.db.execute("DELETE FROM metadata WHERE key IN ('reindex_cursor','retry_cursor')")
    report = backfill(
        store,
        paths.data_dir() / "evidence.sqlite",
        limit=args.limit,
        trust_legacy_public=args.trust_legacy_public,
    )
    report["requeued"] = (
        store.reindex(limit=args.limit, failed_only=args.retry_failed)
        if args.reindex or args.retry_failed
        else 0
    )
    if args.drain:
        while store.run_one():
            pass
    print(json.dumps({"migration": report, "status": store.status()}))


if __name__ == "__main__":
    main()
