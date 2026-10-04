"""Ranking: put the answer near the top before anything expensive happens.

Search sources return rows in whatever order they feel like. Optional ranking
has two local stages:

    1. BM25            lexical, no model, no dependencies, microseconds
    2. corpus merge    passages already fetched, added to the pool

The ordering of the stages was chosen on measurement:

**Rank before fetching.** Fetching is the expensive step -- seconds per page
against microseconds to rank -- and ranking does not need page bodies. Titles
beat bodies for ranking anyway (see rank_rows). So the pool is ordered first
and only the winners are ever fetched.

**Merge the corpus before ranking**, not after. A corpus passage and a web
result are both candidate answers, and appending the corpus to the end of a
ranked list quietly declares every corpus hit worse than every web hit. Merging
first allows lexical ranking to compare both types of result.

Nothing here is required. With no corpus built, the pool is what the web
returned.
"""
from __future__ import annotations

import math
import os
import re

from . import paths as _paths

_TOKEN = re.compile(r"[a-z0-9]+")


def _log(message: str) -> None:
    if os.environ.get("DETHROTTLED_QUIET") != "1":
        print(message)


# ── stage 1: BM25 ────────────────────────────────────────────────────────────

def rank_rows(rows: list, want: str, *, recency: float = 0.0,
              half_life: float = 21.0) -> list:
    """Order a pool by how well each row answers `want`. BM25, no model.

    Chosen on measurement rather than fashion: against a neural bi-encoder on
    the pool this was written for, BM25 placed more useful rows in the top 14
    and did it in no time at all rather than 167 seconds. Rare words are what
    discriminate between search results -- the specific noun, the model number,
    the place name -- and a bi-encoder trained for semantic similarity prefers
    documents that are broadly on-topic to documents that contain the answer.

    `recency` blends in freshness for callers who want the last fortnight
    rather than the best reference page. Multiplicative and bounded, never
    additive: freshness may reorder results that already earned a relevance
    score, and may never promote an irrelevant one. Undated rows count as
    neutral rather than old, because the single most useful result in the case
    this was built for was an undated list.
    """
    if not rows or not want:
        return rows

    terms = [w for w in _TOKEN.findall(want.lower()) if len(w) > 2]
    if not terms:
        return rows

    # Scored on the title and the opening of the text, not the whole page.
    # Measured: ranking on 3000 characters of extracted body and on
    # title-plus-240 both put 5 of 10 useful rows in the top 14, but the short
    # form put the best one at rank 1 rather than rank 3. The rest of a page is
    # navigation, cookie notice and footer, and all of it votes.
    #
    # This is only what RANKING sees. Whatever wins is still returned in full.
    docs = [_TOKEN.findall(
        ("%s %s" % (r.get("title", ""), (r.get("text") or "")[:240])).lower())
        for r in rows]
    count = len(docs)
    average = sum(len(d) for d in docs) / (count or 1)
    seen_in = {t: sum(1 for d in docs if t in d) or 1 for t in terms}

    scored = []
    for index, doc in enumerate(docs):
        length = len(doc) or 1
        score = 0.0
        for term in terms:
            freq = doc.count(term)
            if not freq:
                continue
            idf = math.log(1 + (count - seen_in[term] + 0.5) / (seen_in[term] + 0.5))
            norm = 0.25 + 0.75 * length / average
            score += idf * (freq * 2.5) / (freq + 1.5 * norm)
        if recency > 0:
            age = age_days(rows[index])
            fresh = 1.0 if age is None else 0.5 ** (age / half_life)
            score *= (1.0 - recency) + recency * fresh
        scored.append((score, index))

    scored.sort(key=lambda pair: -pair[0])
    return [rows[i] for _, i in scored]


def age_days(row: dict):
    """Age of a result in days, or None when it does not say.

    Two formats because search results arrive in both: RSS gives RFC 2822 and
    everything modern gives ISO 8601. A row whose date cannot be parsed is
    undated, not ancient -- guessing old would bury it under `recency`.
    """
    raw = (row.get("published") or row.get("publishedDate") or "").strip()
    if not raw:
        return None
    from datetime import datetime, timezone
    from email.utils import parsedate_to_datetime
    for parse in (parsedate_to_datetime,
                  lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))):
        try:
            when = parse(raw)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - when).days)
        except (ValueError, TypeError):
            continue
    return None


# ── stage 2: the corpus ──────────────────────────────────────────────────────

def add_corpus(rows: list, want: str, *, limit: int = 10) -> list:
    """Merge corpus passages into the pool, skipping URLs already in it.

    Passages arrive with their text already extracted, so they cost no fetch --
    which makes a corpus row cheaper than a web row, not merely extra.

    Never fatal: an unbuilt or unreadable corpus leaves the pool exactly as the
    web returned it.
    """
    if not want or limit <= 0:
        return rows
    try:
        from .corpus import Corpus
        corpus = Corpus()
        hits = corpus.search(want, limit=limit)
    except Exception as exc:
        _log("  corpus unavailable (%s); web results only" % str(exc)[:60])
        return rows

    # An index with nothing in it returns [] exactly like an index with no
    # match, and that silence hid a real bug once: an index that nothing wrote
    # to returned nothing forever, with no indication of why. "No match" and
    # "nothing to match against" are different answers and must not look the
    # same.
    if not hits:
        try:
            # stats() is keyed by MODEL, not flat -- reading it flat would
            # report 0 always and cry "empty" on an honest no-match.
            held = corpus.stats().get(corpus.model_name, {}).get("passages", 0)
        except Exception:
            held = -1
        if held == 0:
            _log("  corpus is EMPTY -- nothing has been indexed yet")
        return rows

    have = {r.get("url") for r in rows}
    added = [{"url": h["url"], "title": h["title"] or "", "text": h["text"],
              "snippet": h["text"][:240], "published": "", "engine": "corpus",
              "from_corpus": True, "score": h.get("score")}
             for h in hits if h["url"] not in have]
    if added:
        _log("  +%d from the corpus that search did not return" % len(added))
    return rows + added


def available() -> dict:
    """Report the ranking stages supported by this installation."""
    import importlib.util
    have_ort = importlib.util.find_spec("onnxruntime") is not None
    have_models = have_ort and importlib.util.find_spec("tokenizers") is not None
    return {
        "bm25": True,
        "corpus": have_models and (_paths.model_dir() / "emb-minilm" / "model.onnx").is_file(),
        "rerank": False,
    }

def apply(rows: list, want: str, *, bm25: bool = True,
          corpus: int = 0, recency: float = 0.0) -> tuple:
    """Apply optional corpus merge and lexical ranking, reporting each stage."""
    stages = []
    if not want:
        return rows, stages
    if corpus > 0:
        before = len(rows)
        rows = add_corpus(rows, want, limit=corpus)
        if len(rows) != before:
            stages.append("corpus")
    if bm25:
        rows = rank_rows(rows, want, recency=recency)
        stages.append("bm25+recency" if recency > 0 else "bm25")
    return rows, stages
