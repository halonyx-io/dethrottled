"""Semantic search over everything already fetched.

The cache became a corpus without anyone building one. Every page fetched is
kept for twenty-one days, so hundreds of real documents in several languages
are already on disk -- and the only way to find anything in them was to fetch
it again.

This indexes them. Pages are split into passages, each passage is embedded, and
a query is answered by cosine similarity over the lot.

No vector database. A few thousand passages at 384 dimensions is a matrix of a
few megabytes and a single numpy dot product; an index would be machinery with
nothing to do. Past roughly a hundred thousand passages that stops being true
and something like pgvector or FAISS earns its place -- but the interface below
need not change when it does, so that is a problem for whoever gets there.

MiniLM remains the English index. An optional, separately versioned multilingual
E5 index adds cross-language retrieval. Each model has its own relevance floor;
reciprocal-rank fusion combines retained hits without comparing cosine scales.
See docs/MEASURED-IMPROVEMENTS.md for the small calibration and holdout results.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

from . import paths as _paths
from .dedupe import normalized_digest, url_key

MODELS = _paths.model_dir()

ENGLISH_MODEL = str(MODELS / "emb-minilm")


# Preserve the existing candidate floor. Its original small calibration did
# not establish general answerability: later multilingual/negative tests found
# above-floor irrelevant matches. V2 additionally checks retrieval support and
# exposes warned broad candidates; neither a score nor agreement proves an answer.
FLOOR = float(os.environ.get("DETHROTTLED_CORPUS_FLOOR", "0.22"))

# Much longer than the fetch cache's 21 days, on purpose: outliving that cache
# is the point of the corpus, because a page worth retrieving next month is
# precisely the one the cache will have dropped. But "forever" is not a policy.
RETENTION_DAYS = int(os.environ.get("DETHROTTLED_CORPUS_RETENTION_DAYS", "90"))

# 50,000, not 200,000.
#
# The cap is really a memory budget wearing a different unit. Every passage is
# a 384-dimension float32 vector, and searching means holding all of them in
# one matrix:
#
#     passages   matrix RAM   disk   rebuild   search
#       20,000        31 MB   42 MB     99ms    1.0ms
#       50,000        77 MB  105 MB    236ms    2.5ms
#      100,000       154 MB  210 MB    504ms    8.4ms
#      200,000       307 MB  419 MB   1009ms   13.8ms
#
# 200,000 asks for 307MB of resident memory before Python, the ONNX runtime and
# the embedding model has taken its share, which is most of a 2GB Pi. The
# search was never the problem -- it is 14ms even at the top of that table --
# the resident matrix is. 50,000 passages is about 12,000 pages, holds in
# 77MB, and rebuilds in a quarter of a second.
#
# Raise it if you have the memory; nothing here breaks at a larger number.
MAX_PASSAGES = int(os.environ.get("DETHROTTLED_CORPUS_MAX_PASSAGES", "50000"))

CHUNK_CHARS = int(os.environ.get("DETHROTTLED_CORPUS_CHUNK", "1200"))
CHUNK_OVERLAP = int(os.environ.get("DETHROTTLED_CORPUS_OVERLAP", "200"))

_LOADED = {}
_LOCK = threading.Lock()


def _model(name="minilm"):
    """Load the model once per process. Returns tokenizer, session and inputs."""
    with _LOCK:
        if name not in _LOADED:
            import numpy
            from tokenizers import Tokenizer

            from ._quiet import load as _load_onnxruntime
            onnxruntime = _load_onnxruntime()
            options = onnxruntime.SessionOptions()
            # Bound CPU contention on shared hosts; operators may override.
            # A value of 0 lets ONNX Runtime size the pool to the host.
            options.intra_op_num_threads = int(
                os.environ.get("DETHROTTLED_EMBED_THREADS", "4"))
            # Quiets this session's own logging. The GPU-discovery warning is
            # NOT this -- it fires during import, before any session exists,
            # which is why setting it here never suppressed it. See _quiet.py.
            options.log_severity_level = 3
            session = onnxruntime.InferenceSession(
                (ENGLISH_MODEL if name == "minilm" else str(MODELS / "emb-e5")) + "/model.onnx",
                options,
                providers=["CPUExecutionProvider"])
            tokenizer = Tokenizer.from_file((ENGLISH_MODEL if name == "minilm"
                                             else str(MODELS / "emb-e5")) + "/tokenizer.json")
            tokenizer.no_padding()
            tokenizer.no_truncation()
            tokenizer.enable_truncation(max_length=256 if name == "minilm" else 512)
            tokenizer.enable_padding(pad_id=0 if name == "minilm" else 1,
                                     pad_token="[PAD]" if name == "minilm" else "<pad>",
                                     pad_type_id=0)
            _LOADED[name] = {
                "np": numpy,
                "tok": tokenizer,
                "sess": session,
                "inputs": {i.name for i in session.get_inputs()},
            }
    return _LOADED[name]


def embed(texts: list, *, batch: int = 32, model_name="minilm", query=False) -> list:
    """Unit-normalised vectors, mean-pooled over the tokens that are real.

    Pooling ignores padding: averaging over pad tokens dilutes a short passage
    towards whatever the padding embeds to, which is a slow way to make every
    document look alike.
    """
    if not texts:
        return []
    model = _model(model_name)
    if model_name != "minilm":
        texts = [("query: " if query else "passage: ") + text for text in texts]
    np = model["np"]

    out = []
    for start in range(0, len(texts), batch):
        chunk = list(texts[start:start + batch])
        encoded = model["tok"].encode_batch(chunk)
        arrays = {
            "input_ids": np.asarray([row.ids for row in encoded], dtype=np.int64),
            "attention_mask": np.asarray(
                [row.attention_mask for row in encoded], dtype=np.int64),
            "token_type_ids": np.asarray(
                [row.type_ids for row in encoded], dtype=np.int64),
        }
        feed = {k: v for k, v in arrays.items() if k in model["inputs"]}

        hidden = model["sess"].run(None, feed)[0]
        mask = arrays["attention_mask"][..., None].astype(np.float32)
        pooled = (hidden * mask).sum(1) / np.maximum(mask.sum(1), 1e-9)
        pooled /= np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-9)
        out.extend(pooled.tolist())
    return out


def passages(text: str, title: str = "") -> list:
    """Split a page into overlapping passages.

    Overlapping because the sentence that answers a question has no obligation
    to sit tidily inside one window, and a fact split across a boundary is a
    fact neither passage can be retrieved for.

    The title rides on every passage: a paragraph three screens into an article
    rarely names its own subject.
    """
    text = " ".join((text or "").split())
    if not text:
        return []
    head = ("%s. " % title.strip()) if title.strip() else ""
    step = max(CHUNK_CHARS - CHUNK_OVERLAP, 200)
    return [head + text[i:i + CHUNK_CHARS]
            for i in range(0, len(text), step)
            if len(text[i:i + CHUNK_CHARS]) > 120]


def _pack(vector) -> bytes:
    """A vector as raw float32.

    1,536 bytes against roughly 4,600 characters of JSON for the same 384
    numbers -- and no parsing back into floats on the way out.
    """
    import numpy as np
    return np.asarray(vector, dtype="float32").tobytes()


def _unpack(blob):
    """Read either form. Rows written as JSON before this change still load."""
    import numpy as np
    if isinstance(blob, (bytes, bytearray, memoryview)):
        return np.frombuffer(blob, dtype="float32")
    return np.asarray(json.loads(blob), dtype="float32")


class Corpus:
    """Passages and their vectors, in one sqlite file beside the page cache."""

    def __init__(self, path=None):
        self.path = Path(path or (_paths.data_dir() / "corpus.sqlite"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), timeout=30,
                                   check_same_thread=False)
        self._lock = threading.Lock()
        self._cached = None            # (matrix, meta), dropped when rows change
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA recursive_triggers=ON")
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS passages (
                    id     TEXT PRIMARY KEY,
                    url    TEXT NOT NULL,
                    title  TEXT,
                    text   TEXT NOT NULL,
                    model  TEXT NOT NULL,
                    vec    BLOB NOT NULL,
                    ts     REAL NOT NULL
                )""")
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_url ON passages(url)")
            self._db.commit()
            self._fts = False
            try:
                exists = self._db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='passages_fts'").fetchone()
                self._db.executescript("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
                        title, text, content='passages', content_rowid='rowid');
                    CREATE TRIGGER IF NOT EXISTS passages_ai AFTER INSERT ON passages BEGIN
                        INSERT INTO passages_fts(rowid,title,text)
                            VALUES(new.rowid,new.title,new.text);
                    END;
                    CREATE TRIGGER IF NOT EXISTS passages_ad AFTER DELETE ON passages BEGIN
                        INSERT INTO passages_fts(passages_fts,rowid,title,text)
                            VALUES('delete',old.rowid,old.title,old.text);
                    END;
                    CREATE TRIGGER IF NOT EXISTS passages_au AFTER UPDATE ON passages BEGIN
                        INSERT INTO passages_fts(passages_fts,rowid,title,text)
                            VALUES('delete',old.rowid,old.title,old.text);
                        INSERT INTO passages_fts(rowid,title,text)
                            VALUES(new.rowid,new.title,new.text);
                    END;
                """)
                if not exists:
                    self._db.execute("INSERT INTO passages_fts(passages_fts) VALUES('rebuild')")
                    self._db.commit()
                self._fts = True
            except sqlite3.OperationalError:
                pass  # SQLite builds without FTS retain semantic/exact retrieval.
            self._data_version = self._db.execute(
                "PRAGMA data_version").fetchone()[0]

    # Kept as a column and a constant rather than removed outright: the schema
    # already separates indexes by model, so adding a second one back later
    # needs no migration and no rewrite of what is already stored.
    model_name = "minilm"
    floor = FLOOR

    def _embed(self, texts, *, query=False):
        return embed(texts)

    def add(self, url: str, title: str, text: str) -> int:
        """Index one page. Returns how many passages were added or refreshed."""
        chunks = passages(text, title)
        ids = [hashlib.blake2b(("%s|%s|%d" % (url, self.model_name, i))
                               .encode("utf-8"), digest_size=12).hexdigest()
               for i in range(len(chunks))]
        with self._lock:
            known = dict(self._db.execute(
                "SELECT id, text FROM passages WHERE url=? AND model=?",
                (url, self.model_name)).fetchall())
            changed = [(i, c) for i, c in zip(ids, chunks)
                       if known.get(i) != c]
            stale = set(known) - set(ids)
            if not changed and not stale and not known:
                return 0
            # A URL's identity is stable, but its content is not. The old
            # code skipped every existing passage ID even when the page had
            # changed, so refreshed reports remained stale for 180 days.
            # Hold this instance's lock through embedding so concurrent
            # refreshes of the same URL cannot commit out of order.
            vectors = self._embed([c for _, c in changed]) if changed else []
            now = time.time()
            if stale:
                self._db.executemany(
                    "DELETE FROM passages WHERE id=?",
                    [(i,) for i in stale])
            if changed:
                self._db.executemany(
                    "INSERT OR REPLACE INTO passages "
                    "(id, url, title, text, model, vec, ts) VALUES (?,?,?,?,?,?,?)",
                    [(i, url, title, c, self.model_name, _pack(v), now)
                     for (i, c), v in zip(changed, vectors)])
            # Revisited unchanged pages remain current for retention without
            # paying another embedding inference.
            self._db.execute(
                "UPDATE passages SET ts=? WHERE url=? AND model=?",
                (now, url, self.model_name))
            self._db.commit()
            # Pure appends can extend the matrix cheaply. Replacements and
            # deletions change existing positions, so force one rebuild.
            replaced = any(i in known for i, _ in changed)
            if stale or replaced:
                self._cached = None
            elif changed and self._cached is not None:
                import numpy as np
                old_matrix, old_meta = self._cached
                added = np.asarray(vectors, dtype="float32")
                self._cached = (np.vstack([old_matrix, added]),
                                old_meta + [{"url": url, "title": title,
                                             "text": c} for _, c in changed])
        return len(changed)

    def matrix(self):
        """Every vector for this model, as one array. Built once, then reused.

        Cached because it was being rebuilt on every search: 0.30s at 2,790
        passages and a projected 2.1s at twenty thousand, spent re-reading rows
        that had not changed. Dropped whenever passages are added.
        """
        import numpy as np
        with self._lock:
            # The API reuses this instance, but CLI jobs can write the same
            # SQLite file through another connection. SQLite's data_version
            # changes on those external commits, so they invalidate our
            # resident matrix without a full table scan on every request.
            version = self._db.execute("PRAGMA data_version").fetchone()[0]
            if version != self._data_version:
                self._cached = None
                self._data_version = version
            if self._cached is not None:
                return self._cached
            rows = self._db.execute(
                "SELECT url, title, text, vec FROM passages WHERE model=?",
                (self.model_name,)).fetchall()
            if not rows:
                return None, []
            meta = [{"url": r[0], "title": r[1], "text": r[2]} for r in rows]
            self._cached = (np.asarray([_unpack(r[3]) for r in rows],
                                       dtype="float32"), meta)
            return self._cached

    def prune(self) -> int:
        """Drop passages past the age limit, then past the cap. Oldest first.

        Scoped to THIS model. It used to count and delete across the whole
        table, which was right when one index existed and wrong the moment a
        second appeared: the cap is sized in passages-per-index -- 200,000 is
        about 20,000 pages -- and counting two indexes together silently halved
        the history it was chosen to hold. Deleting oldest-first across both
        would also have trimmed whichever index happened to be written first.
        """
        cutoff = time.time() - RETENTION_DAYS * 24 * 3600
        with self._lock:
            removed = self._db.execute(
                "DELETE FROM passages WHERE ts < ? AND model = ?",
                (cutoff, self.model_name)).rowcount
            total = self._db.execute(
                "SELECT COUNT(*) FROM passages WHERE model = ?",
                (self.model_name,)).fetchone()[0]
            if total > MAX_PASSAGES:
                removed += self._db.execute(
                    "DELETE FROM passages WHERE id IN ("
                    "  SELECT id FROM passages WHERE model = ?"
                    "  ORDER BY ts ASC LIMIT ?)",
                    (self.model_name, total - MAX_PASSAGES)).rowcount
            self._db.commit()
            if removed:
                # A full drop, deliberately. Deletion takes rows out of the
                # middle of the array and the bookkeeping to patch that is
                # worse than the rebuild -- and pruning runs hourly at most,
                # where writes run continuously.
                self._cached = None
        return removed

    def search(self, query: str, *, limit: int = 10, per_url: int = 2,
               floor: float | None = None, domains: list | None = None,
               mode: str = "auto") -> list:
        """The passages closest to a query, at most `per_url` from any one page.

        Capped per page because a long article about the right subject will
        otherwise fill every slot with its own paragraphs, and a reader learns
        nothing from the same source five times.

        `floor` is what stops this answering a question it has nothing for.
        Cosine always returns a best match, and asked in French about Moroccan
        tenders -- of which this corpus holds none -- the best match was a
        Google Drive login page at 0.35, against 0.65 for a real answer to a
        real question. Returning nothing is the correct answer to "we have
        nothing", and much better than returning the least-bad thing on file.

        `domains` scopes the search to particular sites. The cache is shared by
        every subject ever queried, so a corpus built from it is cross-subject
        by construction: a question about solar capacity will otherwise happily
        return pages about semiconductor foundries, which is useful about as
        often as it is misleading.
        """
        import re
        opaque = [w for w in re.findall(r"[\w.-]{12,}", query)
                  if any(c.isdigit() for c in w) and any(c in w for c in "-_.")]
        if mode == "lexical" or (mode == "auto" and opaque):
            from urllib.parse import urlsplit
            with self._lock:
                if self._fts and not opaque:
                    words = re.findall(r"\w+", query)[:30]
                    if not words:
                        return []
                    expression = " AND ".join('"' + w + '"' for w in words)
                    records = self._db.execute(
                        "SELECT p.url,p.title,p.text,bm25(passages_fts) FROM passages_fts "
                        "JOIN passages p ON p.rowid=passages_fts.rowid "
                        "WHERE passages_fts MATCH ? AND p.model=? "
                        "ORDER BY bm25(passages_fts) LIMIT 200",
                        (expression, self.model_name)).fetchall()
                else:
                    records = self._db.execute(
                        "SELECT url,title,text,0 FROM passages WHERE model=?",
                        (self.model_name,)).fetchall()
            out, seen = [], {}
            for url, title, text, score in records:
                if opaque and not all(w.casefold() in ((title or "") + " " + text).casefold()
                                      for w in opaque):
                    continue
                if not self._fts and not opaque and not all(
                        word.casefold() in ((title or "") + " " + text).casefold()
                        for word in re.findall(r"\w+", query)):
                    continue
                host = (urlsplit(url).hostname or "").lower()
                if domains and not any(host == d or host.endswith("." + d) for d in domains):
                    continue
                if seen.get(url_key(url), 0) >= per_url:
                    continue
                seen[url_key(url)] = seen.get(url_key(url), 0) + 1
                out.append({"url": url, "title": title, "text": text,
                            "score": -float(score), "retrieval": "lexical"})
                if len(out) >= limit:
                    break
            return out
        import numpy as np
        if floor is None:
            floor = self.floor
        vectors, meta = self.matrix()
        if vectors is None:
            return []
        q = np.asarray(self._embed([query], query=True)[0], dtype="float32")

        scores = vectors @ q
        wanted = tuple(d.lower() for d in (domains or ()))
        seen, out = {}, []
        for i in np.argsort(-scores):
            if scores[i] < floor:
                break                       # sorted, so nothing below clears it
            row = meta[i]
            if wanted and not any(d in row["url"].lower() for d in wanted):
                continue
            if seen.get(url_key(row["url"]), 0) >= per_url:
                continue
            seen[url_key(row["url"])] = seen.get(url_key(row["url"]), 0) + 1
            out.append(dict(row, score=float(scores[i])))
            if len(out) >= limit:
                break
        return out

    def stats(self) -> dict:
        with self._lock:
            rows = self._db.execute(
                "SELECT model, COUNT(*), COUNT(DISTINCT url) FROM passages "
                "GROUP BY model").fetchall()
        return {r[0]: {"passages": r[1], "pages": r[2]} for r in rows}


class MultilingualCorpus(Corpus):
    model_name = "e5-" + os.getenv("DETHROTTLED_E5_REVISION", "v1")[:12]
    floor = float(os.getenv("DETHROTTLED_E5_FLOOR", ".77"))

    def _embed(self, texts, *, query=False):
        return embed(texts, model_name="e5", query=query, batch=16)


class DualCorpus:
    def __init__(self):
        self.primary = Corpus()
        self.multilingual = MultilingualCorpus()

    def add(self, *args):
        result = self.primary.add(*args)
        self.multilingual.add(*args)
        return result

    def prune(self):
        return self.primary.prune() + self.multilingual.prune()

    def stats(self):
        return self.primary.stats()

    def search(self, query, **kwargs):
        primary = self.primary.search(query, **kwargs)
        if kwargs.get("mode") == "lexical":
            return primary
        # An English threshold must never be applied to a different embedding model.
        try:
            multilingual = self.multilingual.search(query, **dict(kwargs, floor=None))
        except Exception as exc:
            return [dict(row, retrieval_warning="multilingual_unavailable:" + type(exc).__name__)
                    for row in primary]
        merged = {}
        for model, rows in [(self.multilingual.model_name, multilingual), ("minilm", primary)]:
            for index, row in enumerate(rows):
                key = (url_key(row["url"]), normalized_digest(row["text"]) or row["text"])
                record = merged.setdefault(key, {**row, "embedding_model": model,
                                                "fusion_score": 0.0})
                record["fusion_score"] += 1 / (60 + index + 1)
        ranked = sorted(merged.values(), key=lambda row: -row["fusion_score"])
        selected, counts = [], {}
        for row in ranked:
            url = url_key(row["url"])
            if counts.get(url, 0) >= kwargs.get("per_url", 2):
                continue
            counts[url] = counts.get(url, 0) + 1
            selected.append(row)
            if len(selected) >= kwargs.get("limit", 10):
                break
        return selected


_SHARED_CORPUS = None
_SHARED_CORPUS_LOCK = threading.Lock()


def shared_corpus() -> Corpus:
    """Reuse the configured corpus, preserving v1 as an explicit rollback."""
    global _SHARED_CORPUS
    with _SHARED_CORPUS_LOCK:
        if _SHARED_CORPUS is None:
            if os.getenv("DETHROTTLED_CORPUS_SCHEMA", "2") == "1":
                multilingual = os.getenv("DETHROTTLED_MULTILINGUAL_CORPUS") == "1"
                _SHARED_CORPUS = DualCorpus() if multilingual else Corpus()
            else:
                from .corpus_v2 import CorpusV2

                _SHARED_CORPUS = CorpusV2()
        return _SHARED_CORPUS


# How much of a page the corpus takes, regardless of how much was fetched.
# These are two different jobs: a caller wants the whole article, the index
# wants the part of it that is about something. A page's tail is its footer,
# its comments and its related-articles, and indexing those makes them
# retrievable -- the corpus would start answering questions with boilerplate.
INDEX_CHARS = int(os.environ.get("DETHROTTLED_CORPUS_INDEX_CHARS", "4000"))


# Retention only means something if it runs. prune() had no callers at all --
# neither the 180-day limit nor the 200,000 cap was ever applied to anything --
# which mattered little while the corpus was frozen and matters now that it
# grows on every fetch. Once an hour is often enough for limits measured in
# months, and keeps a DELETE scan off the common path.
PRUNE_EVERY = int(os.environ.get("DETHROTTLED_CORPUS_PRUNE_SECONDS", "3600"))
_last_prune = 0.0


def index_fetched(fetched) -> int:
    """Add freshly fetched bodies to the corpus. Best effort, never fatal.

    Lives here rather than in provider.py, where it used to, because provider
    is only one of two callers and was the quieter one. The HTTP routes fetch
    far more pages than any batch job does, and indexed none of them: the corpus
    sat at 2790 passages across 617 urls while the extract cache grew past a
    thousand entries. A retrieval index that the main interface does not feed
    is a retrieval index that slowly stops being about anything.

    Takes (url, result) pairs. `result` may be a fetcher result (ok/text) or an
    API row (quality/content), because both callers have one of those and
    neither should have to reshape it.
    """
    global _last_prune
    if os.environ.get("DETHROTTLED_CORPUS_AUTOINDEX", "1") != "1":
        for _, result in fetched:
            result["corpus_indexing"] = {"accepted": False, "reason": "disabled"}
        return 0
    added = 0
    try:
        corpus = shared_corpus()
    except Exception:
        return 0
    if not hasattr(corpus, "enqueue") and time.time() - _last_prune > PRUNE_EVERY:
        corpus.prune()
        _last_prune = time.time()
    for url, result in fetched:
        try:
            if not (result.get("ok") or result.get("quality") in {"ok", "suspect"}):
                continue
            # Admission requires explicit public provenance, including on the
            # rollback path. public_only (SSRF protection) alone is not consent.
            if result.get("corpus_visibility") != "public":
                result["corpus_indexing"] = {
                    "accepted": False, "reason": "public_provenance_required"}

                continue
            body = result.get("_index_text") or result.get("text") or result.get("content") or ""
            if not body:
                continue
            if hasattr(corpus, "enqueue"):
                report = corpus.enqueue(url, result.get("title", ""), body, result)
                result["corpus_indexing"] = report
                added += int(report["accepted"])
                corpus.start()
            else:
                corpus.add(url, result.get("title", ""), body[:INDEX_CHARS])
                added += 1
        except Exception as exc:
            result["corpus_indexing"] = {"accepted": False, "reason": type(exc).__name__}
            continue
    return added


def backfill_multilingual(batch_urls=16):
    """Resume a separate model index from retained passages without refetching URLs.

    Commit a whole URL at once; a later ordinary refresh replaces migrated IDs.
    Existing MiniLM rows and thresholds are never overwritten.
    """
    primary, target = Corpus(), MultilingualCorpus()
    migrated = 0
    while True:
        with primary._lock:
            urls = [row[0] for row in primary._db.execute(
                "SELECT DISTINCT p.url FROM passages p WHERE p.model='minilm' "
                "AND NOT EXISTS (SELECT 1 FROM passages q WHERE q.url=p.url AND q.model=?) "
                "LIMIT ?", (target.model_name, batch_urls))]
        if not urls:
            return migrated
        with target._lock:
            records = []
            for url in urls:
                if target._db.execute("SELECT 1 FROM passages WHERE url=? AND model=?",
                                      (url, target.model_name)).fetchone():
                    continue
                records.extend(target._db.execute(
                    "SELECT id,url,title,text,ts FROM passages WHERE url=? AND model='minilm'",
                    (url,)).fetchall())
            if not records:
                continue
            vectors = target._embed([row[3] for row in records])
            target._db.executemany("INSERT OR IGNORE INTO passages VALUES(?,?,?,?,?,?,?)", [
                (hashlib.blake2b((row[0] + target.model_name).encode(), digest_size=12).hexdigest(),
                 row[1], row[2], row[3], target.model_name, _pack(vector), row[4])
                for row, vector in zip(records, vectors)])
            target._db.commit()
            migrated += len(records)
