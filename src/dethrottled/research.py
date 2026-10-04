"""Bounded, keyless evidence gathering for a question.

This module selects diverse public sources and extracts traceable passages.
It does not produce an answer or call a language model.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlsplit

from .fetch import canonical_url

_WORDS = re.compile(r"[\w-]+", re.UNICODE)
_STOP = frozenset("a an and are as at be by can did do does for from how in into is it of on or the to was were what when where which who why with".split())


def content_shingles(text: str) -> set[tuple[str, ...]]:
    """A bounded fingerprint for near-identical extracted articles.

    Require enough body text to avoid declaring short shared boilerplate to
    be a duplicate. Capping the input also bounds CPU for long documents.
    """
    words = _WORDS.findall(text.casefold())[:700]
    if len(words) < 80:
        return set()
    return {tuple(words[index:index + 5])
            for index in range(len(words) - 4)}


def duplicate_source(fingerprint: set[tuple[str, ...]],
                     accepted: list[tuple[str, set[tuple[str, ...]]]]) -> str | None:
    """Return an accepted source URL when most five-word phrases are shared."""
    if not fingerprint:
        return None
    for url, prior in accepted:
        if not prior:
            continue
        overlap = len(fingerprint & prior)
        if overlap / len(fingerprint | prior) >= 0.65:
            return url
    return None


def queries_for(question: str, supplied: list[str] | None = None) -> list[str]:
    """Use the question and one primary-source probe, or caller-supplied facets."""
    candidates = [question, *(supplied or [question.rstrip(" ?.") + " official source"])]
    out, seen = [], set()
    for value in candidates:
        text = " ".join(value.split())[:500]
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
        if len(out) >= 4:
            break
    return out


def public_url(url: str) -> bool:
    """Do not let a search result turn research into a local-network fetch."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        if parsed.username or parsed.password or parsed.fragment:
            return False
        if parsed.port not in {None, 80, 443}:
            return False
        host = parsed.hostname.rstrip(".").lower()
        if host in {"localhost", "localhost.localdomain"} or host.endswith(
                (".localhost", ".local", ".lan", ".home", ".internal")):
            return False
        addresses = socket.getaddrinfo(
            host, parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM)
        return bool(addresses) and all(
            ipaddress.ip_address(row[4][0]).is_global for row in addresses)
    except (ValueError, OSError, UnicodeError):
        return False


def select_sources(searches: list[list[dict]], limit: int,
                   *, official_first: bool = False) -> list[dict]:
    """Interleave queries, dedupe URLs, and avoid one site filling the pack.

    The default second query asks for a primary source. Prefer its first
    result in that case: live probes of Python and WHO questions found useful
    official documents there while a broad first query could lead with Reddit
    or local news. Caller-supplied facets keep their given order.
    """
    selected, by_url, per_host = [], {}, {}
    width = max((len(rows) for rows in searches), default=0)
    query_order = list(range(len(searches)))
    if official_first and len(query_order) > 1:
        query_order[0], query_order[1] = query_order[1], query_order[0]
    for rank in range(width):
        for query_index in query_order:
            rows = searches[query_index]
            if rank >= len(rows):
                continue
            row = rows[rank]
            url = row.get("url") or ""
            if not public_url(url):
                continue
            key = canonical_url(url)
            if key in by_url:
                by_url[key]["query_indexes"].append(query_index)
                continue
            host = urlsplit(url).hostname or ""
            if per_host.get(host, 0) >= 2 or len(selected) >= limit:
                continue
            item = {"url": url, "title": row.get("title") or "",
                    "snippet": row.get("snippet") or "",
                    "publishedDate": row.get("publishedDate"),
                    "query_indexes": [query_index], "search_rank": rank + 1}
            selected.append(item)
            by_url[key] = item
            per_host[host] = per_host.get(host, 0) + 1
    return selected


def evidence_windows(text: str, question: str, *, count: int = 2,
                     width: int = 700) -> list[dict]:
    """Return non-overlapping source excerpts most aligned with query terms."""
    terms = {word.casefold() for word in _WORDS.findall(question)
             if len(word) > 2 and word.casefold() not in _STOP}
    if not text or not terms:
        return []
    candidates = []
    step = max(width - 150, 200)
    for offset in range(0, len(text), step):
        excerpt = text[offset:offset + width].strip()
        if not excerpt:
            continue
        matched = sorted(terms & {word.casefold() for word in _WORDS.findall(excerpt)})
        if matched:
            candidates.append((len(matched), offset, excerpt, matched))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    chosen = []
    for _, offset, excerpt, matched in candidates:
        if any(abs(offset - prior["offset"]) < width for prior in chosen):
            continue
        chosen.append({"offset": offset, "excerpt": excerpt,
                       "matched_terms": matched})
        if len(chosen) >= count:
            break
    return chosen
