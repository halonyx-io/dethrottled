"""Optional intent-aware query fan-out and cross-variant consensus.

The default search still sends one query. This module is the measured,
opt-in exploration of Hound's idea: a diverse variant can surface pages the
first wording misses, and a URL found by several variants/engines is a stronger
lead than one found once. Nothing here changes the default path.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_STOP = {
    "the", "a", "an", "of", "to", "in", "for", "on", "and", "or", "is", "are",
    "what", "how", "why", "when", "where", "who", "with", "from", "vs", "versus",
}

# Conservative expansions. False positives cost requests and dilute diversity;
# false negatives simply keep the current single-query behavior.
_RULES = (
    ("comparison", r"\b(vs\.?|versus|compare|difference between|better than)\b",
     "comparison benchmark"),
    ("howto", r"\b(how to|tutorial|guide|install|configure|setup|set up)\b",
     "step by step guide"),
    ("research", r"\b(paper|research|study|benchmark|evaluation|arxiv)\b",
     "paper benchmark results"),
    ("code", r"\b(code|api|sdk|library|function|implementation|example)\b",
     "code example implementation"),
    ("reference", r"\b(docs?|documentation|reference|manual|specification)\b",
     "official documentation reference"),
    ("news", r"\b(news|latest|today|release|announcement)\b",
     "latest news release"),
    ("factual", r"\b(architecture|parameter|dimension|throughput|latency|memory|"
                r"version|config|specification)\b", "technical details numbers"),
)


def intent(query: str) -> str:
    lowered = (query or "").casefold()
    for name, pattern, _suffix in _RULES:
        if re.search(pattern, lowered, re.I):
            return name
    return "general"


def expand_queries(query: str) -> list:
    """Return [original, optional expansion] for the detected intent."""
    original = " ".join((query or "").split())
    if not original:
        return []
    words = [w for w in _TOKEN.findall(original) if w.casefold() not in _STOP]
    if len(words) < 2 or len(words) >= 15:
        return [original]
    kind = intent(original)
    for name, _pattern, suffix in _RULES:
        if name == kind:
            return [original, (original + " " + suffix).strip()]
    return [original]


def _key(url: str) -> str:
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return url or ""
    host = (parts.netloc or "").lower()
    for prefix in ("www.", "m.", "amp."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host + (parts.path or "/").rstrip("/")


def merge_variants(groups: list) -> list:
    """Merge result lists from several query variants.

    A URL keeps the first row and accumulates discovery provenance. The
    consensus count is the number of distinct engines plus distinct query
    variants that surfaced it; no network call is made here.
    """
    seen, out = {}, []
    for group_index, rows in enumerate(groups):
        for row in rows or []:
            key = _key(row.get("url", ""))
            if not key:
                continue
            item = seen.get(key)
            if item is None:
                item = dict(row)
                item["discovery"] = [dict(entry) for entry in row.get("discovery", [])]
                item["query_variants"] = [group_index]
                seen[key] = item
                out.append(item)
            else:
                for entry in row.get("discovery", []):
                    if entry not in item["discovery"]:
                        item["discovery"].append(dict(entry))
                if group_index not in item["query_variants"]:
                    item["query_variants"].append(group_index)
    annotate_consensus(out)
    return out


def annotate_consensus(rows: list) -> list:
    """Add engines_consensus/consensus_score without changing source order."""
    for row in rows:
        generic = {"web", "searxng", "specialist", "supplements", "gnews-resolved"}
        engines = {
            str(entry.get("provider") or "")
            for entry in row.get("discovery", [])
            if entry.get("provider") and entry.get("provider") not in generic
        }
        engine = str(row.get("engine") or "")
        if engine:
            engine = engine.removeprefix("web-browser-").removeprefix("web-")
            engines.add(engine)
        variants = len(row.get("query_variants") or [1])
        row["engines_consensus"] = len(engines)
        row["consensus_score"] = round(len(engines) + max(0, variants - 1) * 0.5, 3)
    return rows
