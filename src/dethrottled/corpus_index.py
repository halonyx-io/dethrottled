"""Single-worker preparation and transactional source-version promotion."""

from __future__ import annotations

import hashlib
import json
import time

from .corpus_chunks import chunks, distributed, representative
from .corpus_config import integer
from .corpus_jobs import inference


class IndexWorker:
    def _token_chunks(self, items):
        """Split lexical blocks until EVERY model admits their complete text."""
        from .corpus import _model

        tokenizers = []
        for model in self.models:
            name = "minilm" if model == "minilm" else "e5"
            from .corpus import MODELS

            root = MODELS / ("emb-minilm" if name == "minilm" else "emb-e5")
            if not all(
                (root / filename).is_file() for filename in ("model.onnx", "tokenizer.json")
            ):
                raise FileNotFoundError("embedding weights unavailable: " + name)
            # Existing tokenizers are read-only here. Their overflow records
            # reveal truncation without cloning E5's large vocabulary or
            # mutating settings used by concurrent live queries.
            tokenizers.append((_model(name)["tok"], "" if name == "minilm" else "passage: "))
        result, pending = [], list(reversed(items))
        while pending:
            item = pending.pop()
            if all(not tok.encode(prefix + item.text).overflowing for tok, prefix in tokenizers):
                result.append(item)
                continue
            # Unicode character splitting preserves offsets even for scripts
            # where a single word exceeds a tokenizer's window.
            middle = len(item.text) // 2
            if middle == 0:
                raise ValueError("token limit cannot admit a single character")
            from .corpus_chunks import Chunk

            halves = []
            for offset, raw in ((0, item.text[:middle]), (middle, item.text[middle:])):
                halves.append(
                    Chunk(
                        item.start + offset,
                        item.start + offset + len(raw),
                        raw,
                        item.heading,
                        item.page,
                        hashlib.sha256(raw.encode()).hexdigest(),
                    )
                )
            pending.extend(reversed(halves))
        return result

    def _prepare(self, source, lease):
        from .corpus import _pack, embed

        identifier = source["id"]
        record = self.documents.get(source["namespace"], source["document_id"])
        if record is None:
            raise FileNotFoundError("retained_document_missing_or_expired")
        text = record["text"]
        all_chunks = list(chunks(text))
        cap = integer("LEXICAL_CHARS", 2_000_000)
        # Every character has been examined. Overlarge sources get distributed
        # lexical windows, with exact covered ranges recorded below.
        lexical = distributed(all_chunks, max(1, cap // 900)) if len(text) > cap else all_chunks
        semantic_available = True
        try:
            lexical = self._token_chunks(lexical)
        except (ImportError, FileNotFoundError):
            semantic_available = False
        budget = (
            integer("LONG_PASSAGES", 96) if len(text) > 40_000 else integer("PAGE_PASSAGES", 32)
        )
        selected = representative(lexical, budget) if semantic_available else []
        vectors = []
        for model in self.models:
            for start in range(0, len(selected), 8):
                self._heartbeat(identifier, lease)
                batch = selected[start : start + 8]
                found = {}
                with self.lock:
                    for item in batch:
                        row = self.db.execute(
                            "SELECT e.vector FROM embeddings e "
                            "JOIN passages p ON p.id=e.passage_id "
                            "WHERE p.digest=? AND e.model=? AND e.revision=? LIMIT 1",
                            (item.digest, model, self.revisions[model]),
                        ).fetchone()
                        if row:
                            found[item.digest] = row[0]
                missing = [item for item in batch if item.digest not in found]
                if missing:
                    with inference(background=True):
                        encoded = embed(
                            [item.text for item in missing],
                            batch=8,
                            model_name="minilm" if model == "minilm" else "e5",
                        )
                    if len(encoded) != len(missing):
                        raise ValueError("embedding batch length mismatch")
                    found.update(
                        (item.digest, _pack(vector)) for item, vector in zip(missing, encoded)
                    )
                vectors.extend(
                    (item.start, model, len(found[item.digest]) // 4, found[item.digest])
                    for item in batch
                )
        coverage = json.loads(source["coverage"])
        coverage.update(
            lexical_chars=sum(item.end - item.start for item in lexical),
            lexical_passages=len(lexical),
            embedded_passages={model: len(selected) for model in self.models},
            embedded_chars=sum(item.end - item.start for item in selected),
            lexical_ranges=[[item.start, item.end] for item in lexical],
            embedded_ranges=[[item.start, item.end] for item in selected],
            document_expires_at=record["document_expires_at"],
        )
        coverage["model_revisions"] = self.revisions
        if not semantic_available:
            coverage["omissions"].append("semantic_dependencies_or_weights_unavailable")
        if coverage["lexical_chars"] < len(text):
            coverage["omissions"].append("lexical_budget")
        if coverage["embedded_chars"] < coverage["lexical_chars"]:
            coverage["omissions"].append("semantic_selection")
        return lexical, vectors, coverage

    def run_one(self):
        claimed = self._claim()
        if not claimed:
            return False
        source, lease = claimed
        try:
            lexical, vectors, coverage = self._prepare(source, lease)
            self._heartbeat(source["id"], lease)
            with self.lock, self.db:
                self.db.execute("BEGIN IMMEDIATE")
                valid = self.db.execute(
                    "SELECT 1 FROM index_jobs WHERE source_id=? "
                    "AND state='running' AND lease=? AND expires>?",
                    (source["id"], lease, time.time()),
                ).fetchone()
                if not valid:
                    raise InterruptedError("stale promotion rejected")
                # One transaction publishes complete lexical + all-model state.
                self.db.execute("DELETE FROM passages WHERE source_id=?", (source["id"],))
                passage_ids = {}
                for item in lexical:
                    cursor = self.db.execute(
                        "INSERT INTO passages(source_id,start,end,text,digest,"
                        "heading,page) VALUES(?,?,?,?,?,?,?)",
                        (
                            source["id"],
                            item.start,
                            item.end,
                            item.text,
                            item.digest,
                            item.heading,
                            item.page,
                        ),
                    )
                    passage_ids[item.start] = cursor.lastrowid
                self.db.executemany(
                    "INSERT INTO embeddings VALUES(?,?,?,?,?)",
                    [
                        (passage_ids[start], model, dims, vector, self.revisions[model])
                        for start, model, dims, vector in vectors
                    ],
                )
                self.db.execute(
                    "UPDATE sources SET active=0,state='superseded' WHERE url=? AND id!=?",
                    (source["url"], source["id"]),
                )
                self.db.execute(
                    "UPDATE sources SET active=1,state='ready',coverage=? WHERE id=?",
                    (json.dumps(coverage), source["id"]),
                )
                self.db.execute(
                    "UPDATE index_jobs SET state='completed',lease=NULL,error=NULL,"
                    "updated=? WHERE source_id=?",
                    (time.time(), source["id"]),
                )
                self.db.execute(
                    "UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='generation'"
                )
                # Obsolete vectors disappear only after replacements are ready.
                self.db.execute(
                    "DELETE FROM sources WHERE url=? AND id!=? AND active=0 AND state='superseded'",
                    (source["url"], source["id"]),
                )
        except Exception as exc:
            with self.lock, self.db:
                row = self.db.execute(
                    "SELECT attempts FROM index_jobs WHERE source_id=? AND lease=?",
                    (source["id"], lease),
                ).fetchone()
                if row:
                    state = (
                        "failed" if row[0] >= 3 or isinstance(exc, FileNotFoundError) else "pending"
                    )
                    if isinstance(exc, InterruptedError):
                        state = "pending"
                        self.db.execute(
                            "UPDATE index_jobs SET attempts=max(0,attempts-1) WHERE source_id=?",
                            (source["id"],),
                        )
                    self.db.execute(
                        "UPDATE index_jobs SET state=?,lease=NULL,error=?,available=?,"
                        "updated=? WHERE source_id=? AND lease=?",
                        (
                            state,
                            type(exc).__name__ + ": " + str(exc)[:180],
                            time.time() + 2 ** row[0],
                            time.time(),
                            source["id"],
                            lease,
                        ),
                    )
                    self.db.execute(
                        "UPDATE sources SET state=? WHERE id=? AND active=0", (state, source["id"])
                    )
        return True
