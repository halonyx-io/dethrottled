"""Bounded lexical, model-specific semantic, and explicit hybrid retrieval."""

from __future__ import annotations

import re
import time
from urllib.parse import urlsplit

from .corpus_config import integer
from .corpus_jobs import inference


class Matches(list):
    """List-compatible hits carrying per-query diagnostics, even when empty."""

    def __init__(self, rows, warnings):
        super().__init__(rows)
        self.retrieval_warnings = list(warnings)


def search(store, query, *, limit=10, per_url=2, floor=None, domains=None, mode="auto",
           support="standard"):
    if mode not in {"auto", "semantic", "lexical", "hybrid"}:
        raise ValueError("unknown corpus retrieval mode")
    if support not in {"standard", "broad"}:
        raise ValueError("unknown corpus support policy")
    limit, per_url = max(1, min(int(limit), 100)), max(1, min(int(per_url), 100))
    opaque = [
        word
        for word in re.findall(r"[\w.-]{12,}", query)
        if any(c.isdigit() for c in word) and any(c in word for c in "-_.")
    ]
    if mode == "auto":
        mode = "lexical" if opaque else "semantic"
    excluded = re.findall(r"(?<!\w)-(\w+)", query)
    clean = re.sub(r"(?<!\w)-\w+", " ", query).strip()
    if not clean:
        return []
    wanted = tuple(domain.lower().strip(".") for domain in (domains or []))
    # Retain enough per-source candidates to apply diversity after fusion.
    depth = min(400, max(50, limit * 10))
    lists, warnings = [], []
    with store.lock:
        fresh_urls = {
            row[0]
            for row in store.db.execute(
                "SELECT url FROM sources WHERE active=1 AND touched>=?",
                (time.time() - integer("RETENTION_DAYS", 90) * 86400,),
            )
        }

    def eligible(url):
        host = (urlsplit(url).hostname or "").lower()
        return url in fresh_urls and (
            not wanted or any(host == domain or host.endswith("." + domain) for domain in wanted)
        )

    if mode in {"lexical", "hybrid"}:
        words = re.findall(r"\w+", clean)[:40]
        if words:
            expression = " AND ".join('"' + word + '"' for word in words)
            with store.lock:
                rows = store.db.execute(
                    "SELECT p.id,s.url,p.text,bm25(passage_fts) score FROM passage_fts "
                    "JOIN passages p ON p.id=passage_fts.rowid JOIN sources s ON s.id=p.source_id "
                    "WHERE passage_fts MATCH ? AND s.active=1 ORDER BY score LIMIT 2000",
                    (expression,),
                ).fetchall()
            ranked = []
            for row in rows:
                if eligible(row["url"]) and all(
                    value.casefold() in row["text"].casefold() for value in opaque
                ):
                    ranked.append((row["id"], -float(row["score"]), "lexical"))
                if len(ranked) >= depth:
                    break
            lists.append(ranked)
    if mode in {"semantic", "hybrid"}:
        try:
            import numpy as np

            from .corpus import FLOOR, MultilingualCorpus, embed

            for model in store.models:
                try:
                    with inference():
                        encoded = embed(
                            [clean], model_name="minilm" if model == "minilm" else "e5", query=True
                        )[0]
                    q = np.asarray(encoded, dtype="float32")
                    threshold = (
                        (FLOOR if floor is None else floor)
                        if model == "minilm"
                        else MultilingualCorpus.floor
                    )
                    from .corpus_vectors import candidates

                    lists.append(candidates(store, model, q, threshold, depth, eligible, per_url))
                except (ImportError, OSError, ValueError, RuntimeError) as exc:
                    warnings.append(model + ": " + type(exc).__name__)
        except ImportError:
            warnings.append("semantic_dependencies_unavailable")
    # Each semantic model first applies its own floor; fusion never compares
    # their cosine scales with each other or with BM25.
    scores, details = {}, {}
    for ranked in lists:
        for rank, (identifier, score, model) in enumerate(ranked, 1):
            scores[identifier] = scores.get(identifier, 0) + 1 / (60 + rank)
            details.setdefault(identifier, {})[model] = {"score": score, "rank": rank}
    records = store._records(list(scores))
    from .corpus_support import assess

    source_models = {}
    for identifier, individual in details.items():
        row = records.get(identifier)
        if row is not None:
            source_models.setdefault(row["url"], set()).update(individual)
    out, seen = [], {}
    for identifier in sorted(scores, key=lambda key: (-scores[key], key)):
        row = records.get(identifier)
        if row is None or seen.get(row["url"], 0) >= per_url:
            continue
        if excluded and any(
            re.search(r"\b" + re.escape(word) + r"\b", row["text"], re.I) for word in excluded
        ):
            continue
        support_status = assess(clean, row, source_models[row["url"]])
        if support == "standard" and support_status == "unconfirmed":
            continue
        seen[row["url"]] = seen.get(row["url"], 0) + 1
        individual = details[identifier]
        score = next(iter(individual.values()))["score"] if len(lists) == 1 else scores[identifier]
        row["document_available"] = store.document_available(row["document_id"])
        row.update(
            score=score,
            retrieval=mode,
            fusion_score=scores[identifier],
            model_scores=individual,
            visibility="public",
            schema=2,
            support_status=support_status,
            answer_support="unverified",
        )
        if support_status == "unconfirmed":
            row["retrieval_warning"] = ["single_model_match_without_query_anchors"]
        if warnings:
            row.setdefault("retrieval_warning", []).extend(warnings)
        out.append(row)
        if len(out) >= limit:
            break
    return Matches(out, warnings)
