"""One identity rule for search rows, fetched sources and corpus passages.

Every layer used to decide "same thing" its own way and then threw the
duplicate away, including whatever it carried that the survivor lacked: a
SearXNG row's publication date lost to the DDG copy of the same URL, a mirror's
provenance, a tracking-parameter variant indexed as a second corpus source.

Identity is decided at two levels. URL identity (`url_key`) is string work and
applies everywhere. Content identity (`text_fingerprint`) needs full text, so it
applies only to fetched sources and corpus passages: search snippets are too
short to prove syndication, and titles alone never do. A duplicate is merged
into its survivor (`merge_into`), never silently dropped, and the collapsed
address is listed under the survivor's `duplicates`.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from . import signals
from .urls import canonical_url

DUPLICATES_CAP = 8
NEAR_DUPLICATE_JACCARD = 0.65          # measured on research mirrors; see test_research
MIN_SHINGLE_WORDS = 80

_INDEX_PAGE = re.compile(r"/(?:index|default)\.(?:html?|php|aspx?)$", re.I)
_WORDS = re.compile(r"[\w-]+", re.UNICODE)
_NON_WORD = re.compile(r"\W+", re.UNICODE)
# Second-level labels under which registrations sit one level deeper (bbc.co.uk).
_SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov", "edu", "ne", "or", "go"}


def url_key(url: str) -> str:
    """Grouping key: the same page under any address maps to one key.

    Builds on `canonical_url` (tracking parameters, fragment, trailing slash,
    www/m/amp hosts) and also folds the scheme, default ports, index pages,
    a trailing /amp segment and query-parameter order. For grouping only:
    rows keep their real URL. Unparseable input is returned unchanged.
    """
    canon = canonical_url(url)
    try:
        parts = urlsplit(canon)
        port = parts.port
    except ValueError:
        return canon
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return canon
    host = parts.hostname
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = _INDEX_PAGE.sub("", parts.path)
    if path.endswith("/amp"):
        path = path[:-4]
    path = path.rstrip("/") or "/"
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    query = urlencode(sorted(pairs, key=lambda pair: pair[0]))
    return urlunsplit(("https", netloc, path, query, ""))


def _site(host: str) -> str:
    labels = [label for label in (host or "").lower().split(".") if label]
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def declared_key(row: dict) -> str | None:
    """The key of a page's declared canonical, when it is on the same site.

    A cross-site canonical (a syndicated copy pointing at its origin) is real
    information but is not trusted to collapse rows: a hostile or careless page
    could otherwise absorb an unrelated source.
    """
    meta = row.get("page_metadata") or {}
    declared = meta.get("canonical") if isinstance(meta, dict) else None
    url = row.get("url") or ""
    if not declared or not url:
        return None
    try:
        absolute = urljoin(url, declared)
        same = _site(urlsplit(absolute).hostname or "") == _site(urlsplit(url).hostname or "")
    except ValueError:
        return None
    return url_key(absolute) if same else None


def content_shingles(text: str) -> set[tuple[str, ...]]:
    """A bounded five-word fingerprint for near-identical extracted text.

    Requires enough body text that short shared boilerplate is never a
    duplicate; capping the input bounds CPU for long documents.
    """
    words = _WORDS.findall((text or "").casefold())[:700]
    if len(words) < MIN_SHINGLE_WORDS:
        return set()
    return {tuple(words[index:index + 5]) for index in range(len(words) - 4)}


def normalized_digest(text: str) -> str:
    """SHA-256 of case- and punctuation-folded text; empty text has no digest."""
    normalized = _NON_WORD.sub(" ", (text or "").casefold()).strip()
    return hashlib.sha256(normalized.encode()).hexdigest() if normalized else ""


def text_fingerprint(text: str, *, min_words: int = MIN_SHINGLE_WORDS) -> dict:
    """Exact and near fingerprints. Text under `min_words` words has neither:
    independent sources can share a short line without being copies."""
    if len(_WORDS.findall((text or "").casefold())) < min_words:
        return {"digest": "", "shingles": set()}
    return {"digest": normalized_digest(text), "shingles": content_shingles(text)}


def content_match(a: dict, b: dict) -> str | None:
    """`same_text`, `near_text` or None for two `text_fingerprint` results."""
    if a.get("digest") and a["digest"] == b.get("digest"):
        return "same_text"
    left, right = a.get("shingles") or set(), b.get("shingles") or set()
    if left and right and len(left & right) / len(left | right) >= NEAR_DUPLICATE_JACCARD:
        return "near_text"
    return None


def _structured_date(row: dict) -> str:
    value, source = signals.date_provenance(row)
    return value if source == "structured" else ""


def _merge_dates(survivor: dict, duplicate: dict) -> None:
    """A provider date beats a snippet date; a snippet date is never promoted."""
    if _structured_date(survivor):
        mine = signals.parse_date(_structured_date(survivor))
        theirs_value, theirs_source = signals.date_provenance(duplicate)
        theirs = signals.parse_date(theirs_value) if theirs_source == "snippet" else None
        if mine and theirs and abs((mine - theirs).days) > 7:
            survivor.setdefault("date_hint_rejected", {
                "value": theirs_value, "reason": "conflicts_with_provider_date",
                "from": duplicate.get("url", "")})
        return
    structured = _structured_date(duplicate)
    if structured:
        survivor["publishedDate"] = structured
        survivor["date_source"] = "structured"
        survivor.pop("date_relative", None)
        return
    if signals.date_provenance(survivor)[1] != "none" or survivor.get("date_relative"):
        return
    value, source = signals.date_provenance(duplicate)
    if source == "snippet" and value:
        survivor["publishedDate"] = value
        survivor["date_source"] = "snippet"
        for key in ("date_relative", "date_precision", "observed_at"):
            if duplicate.get(key):
                survivor[key] = duplicate[key]


def _provider(row: dict) -> str:
    for entry in row.get("discovery") or []:
        if entry.get("provider"):
            return str(entry["provider"])
    return str(row.get("engine") or "")


def merge_into(survivor: dict, duplicate: dict, reason: str = "same_url", *,
               provenance: bool = True) -> dict:
    """Fold what `duplicate` carries into `survivor`, which keeps its place.

    The survivor's URL, title and position are unchanged. Missing dates and an
    empty snippet are filled, provenance and query variants are unioned, and a
    duplicate at a different address is listed under `duplicates` (bounded).
    `provenance=False` skips the `discovery` union for compact row shapes.
    """
    _merge_dates(survivor, duplicate)
    if not (survivor.get("snippet") or "").strip() and (duplicate.get("snippet") or "").strip():
        survivor["snippet"] = duplicate["snippet"]
    if provenance and duplicate.get("discovery"):
        entries = survivor.setdefault("discovery", [])
        for entry in duplicate["discovery"]:
            if entry not in entries:
                entries.append(dict(entry))
    if duplicate.get("query_variants"):
        variants = survivor.setdefault("query_variants", [])
        for value in duplicate["query_variants"]:
            if value not in variants:
                variants.append(value)
    records = list(duplicate.get("duplicates") or [])
    if duplicate.get("url") and duplicate["url"] != survivor.get("url"):
        records.insert(0, {"url": duplicate["url"], "provider": _provider(duplicate),
                           "reason": reason})
    if records:
        listed = survivor.setdefault("duplicates", [])
        known = {item.get("url") for item in listed} | {survivor.get("url")}
        for record in records:
            if len(listed) >= DUPLICATES_CAP:
                break
            if record.get("url") not in known:
                listed.append(dict(record))
                known.add(record.get("url"))
    return survivor


def collapse(rows, *, by: str = "url", text_field: str = "content",
             counts: dict | None = None) -> list:
    """Stable, order-preserving fold of duplicate rows into their first copy.

    `by="url"` uses `url_key` and a same-site declared canonical. `by="content"`
    also compares `text_field` fingerprints. Rows are copied; inputs are not
    modified. `counts`, when given, accumulates collapses by reason.
    """
    out, by_key, prints = [], {}, []
    for row in rows or []:
        key = url_key(row.get("url") or "")
        reason, survivor = None, None
        if key and key in by_key:
            reason, survivor = "same_url", by_key[key]
        else:
            declared = declared_key(row)
            if declared and declared in by_key:
                reason, survivor = "declared_canonical", by_key[declared]
        fingerprint = None
        if survivor is None and by == "content":
            fingerprint = text_fingerprint(row.get(text_field) or "")
            for prior, kept in prints:
                found = content_match(fingerprint, prior)
                if found:
                    reason, survivor = found, kept
                    break
        if survivor is not None:
            merge_into(survivor, row, reason)
            if counts is not None:
                counts[reason] = counts.get(reason, 0) + 1
            continue
        kept = dict(row)
        out.append(kept)
        for value in (key, declared_key(row)):
            if value:
                by_key.setdefault(value, kept)
        if by == "content":
            prints.append((fingerprint or text_fingerprint(row.get(text_field) or ""), kept))
    return out
