"""Offset-preserving structural chunks and distributed semantic admission."""

from __future__ import annotations

import bisect
import hashlib
import re
from dataclasses import dataclass

VERSION = "structure-2"


@dataclass(frozen=True)
class Chunk:
    start: int
    end: int
    text: str
    heading: str
    page: int | None
    digest: str


def chunks(text: str, *, chars=900):
    """Visit all text, retain original offsets, prefer paragraph/line boundaries.

    Character bounds are only a first cut; embedding admission splits further
    against the actual configured model tokenizers, without truncating text.
    """
    heading, page, start = "", None, 0
    boundaries = [match.start() for match in re.finditer(r"(?mi)^#{1,6}\s+Page\s+\d+", text)]
    while start < len(text):
        end = min(start + chars, len(text))
        if end < len(text):
            boundary = text.rfind("\n\n", start + chars // 3, end)
            if boundary < 0:
                boundary = text.rfind("\n", start + chars // 3, end)
            if boundary < 0:
                boundary = text.rfind(" ", start + chars // 2, end)
            if boundary >= 0:
                end = boundary + 1
        following = bisect.bisect_right(boundaries, start)
        if following < len(boundaries):
            end = min(end, boundaries[following])
        raw = text[start:end]
        chunk_heading = heading
        for match in re.finditer(r"(?m)^#{1,6}\s+(.+)", raw):
            if match.start() == 0:
                chunk_heading = match[1].strip()
            heading = match[1].strip()
            number = re.fullmatch(r"Page\s+(\d+)", heading, re.I)
            if number:
                page = int(number[1])
        if raw:
            yield Chunk(
                start, end, raw, chunk_heading, page, hashlib.sha256(raw.encode()).hexdigest()
            )
        start = end


def distributed(items, count):
    """Include beginning/end and spread the remaining budget over the source."""
    if len(items) <= count:
        return list(items)
    if count <= 0:
        return []
    if count == 1:
        return [items[0]]
    return [items[round(i * (len(items) - 1) / (count - 1))] for i in range(count)]


def representative(items, count):
    """Exclude exact/near duplicates from embedding, never from lexical storage."""
    unique, seen = [], set()
    for item in items:
        normalized = re.sub(r"\W+", " ", item.text.casefold()).strip()
        # Normalization makes punctuation/whitespace-only variants identical.
        digest = hashlib.sha256(normalized.encode()).hexdigest()
        words = normalized.split()
        # These scripts do not consistently separate words with spaces. Count
        # their letters rather than treating an entire useful sentence as one
        # word; actual tokenizer limits are checked independently by the worker.
        unspaced = len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff\u0e01-\u0e5b]", normalized))
        if digest in seen or max(len(words), unspaced) < 6:
            continue
        # Link-heavy menus are retained lexically, but not given scarce vectors.
        if item.text.count("](") > max(3, len(words) // 8):
            continue
        seen.add(digest)
        unique.append(item)
    return distributed(unique, count)
