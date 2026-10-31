"""Content fidelity and bounded page diagnostics, independent of transport."""

from __future__ import annotations

import codecs
import re
from urllib.parse import urljoin, urlsplit


def decode_html(data: bytes, content_type: str = "") -> str:
    """Honor explicit declarations, not Requests' implicit Latin-1 default."""
    candidates = []
    for bom, encoding in ((codecs.BOM_UTF8, "utf-8-sig"),
                          (codecs.BOM_UTF16_LE, "utf-16"),
                          (codecs.BOM_UTF16_BE, "utf-16")):
        if data.startswith(bom):
            candidates.append(encoding)
    declared = re.search(r"charset\s*=\s*['\"]?([\w.-]+)", content_type, re.I)
    if declared:
        candidates.append(declared[1])
    meta = re.search(rb"<meta\b[^>]*charset\s*=\s*['\"]?([\w.-]+)",
                     data[:8192], re.I)
    if meta:
        candidates.append(meta[1].decode("ascii", errors="ignore"))
    candidates.append("utf-8")
    for encoding in candidates:
        try:
            return data.decode(encoding)
        except (UnicodeError, LookupError):
            continue
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(data).best()
        if best is not None:
            return str(best)
    except ImportError:
        pass
    return data.decode("windows-1252", errors="replace")


def page_details(html: str, url: str) -> dict:
    """Expose assets and extraction limitations without fetching linked targets."""
    try:
        from selectolax.lexbor import LexborHTMLParser
        tree = LexborHTMLParser(html)
        assets, seen = [], set()
        for tag, attribute in (("img", "src"), ("iframe", "src"), ("a", "href")):
            for node in tree.css(tag):
                target = urljoin(url, node.attributes.get(attribute, ""))
                if urlsplit(target).scheme not in {"http", "https"} or target in seen:
                    continue
                label = node.attributes.get("alt", "") or node.text(strip=True)[:200]
                if tag == "a" and not re.search(r"\.(pdf|xlsx?|docx?|png|jpe?g)(?:$|\?)",
                                                target, re.I):
                    continue
                if re.search(r"logo|favicon|tracking|banner|sprite|icon", target + label, re.I):
                    continue
                seen.add(target)
                assets.append({"url": target, "kind": {"img": "image", "iframe": "frame",
                                                        "a": "document"}[tag],
                               "label": label[:200]})
                if len(assets) >= 24:
                    break
        body = tree.body
        all_text = body.text(separator=" ", strip=True) if body else ""
        anchors = sum(len(n.text(strip=True)) for n in tree.css("a"))
        for node in tree.css("script,style,nav,header,footer,aside,form,noscript,svg"):
            node.decompose()
        main = tree.css_first("main,article,[role=main]") or tree.body
        text = main.text(separator=" ", strip=True) if main else ""
        image_table = any(re.search(r"schedule|timetable|chart|infographic", a["url"] +
                                   a["label"], re.I) for a in assets if a["kind"] == "image")
        density = anchors / max(len(all_text), 1)
        status = "complete"
        warnings = []
        if image_table and (len(text) < 1500 or density > 0.4):
            status = "image_content"
            warnings.append("Important information may be in images; "
                            "inspect assets before answering.")
        elif density > 0.65 and len(text) < 1500:
            status = "navigation_only"
            warnings.append("Extracted content may be navigation rather than "
                            "the requested information.")
        elif len(text) < 350:
            status = "short"
        return {"assets": assets[:24], "content_status": status, "warnings": warnings}
    except (ImportError, ValueError, TypeError):
        return {"assets": [], "content_status": "unknown", "warnings": []}


def short_text(html: str) -> str:
    """A small valid document is not an empty article or a JavaScript shell."""
    try:
        from selectolax.lexbor import LexborHTMLParser
        tree = LexborHTMLParser(html)
        for node in tree.css("script,style,nav,header,footer,aside,form,noscript,svg"):
            node.decompose()
        return tree.body.text(separator=" ", strip=True) if tree.body else ""
    except (ImportError, ValueError):
        return ""


def constrained(query: str, row: dict) -> bool:
    """Apply site operators after every merge, including corpus/fallback sources."""
    host = (urlsplit(row.get("url", "")).hostname or "").lower().rstrip(".")
    sites = re.findall(r"(?<![\w-])(-?)site:([\w.-]+)", query, re.I)
    positive = [site.lower().rstrip(".") for minus, site in sites if not minus]
    negative = [site.lower().rstrip(".") for minus, site in sites if minus]

    def matches(site):
        return host == site or host.endswith("." + site)

    return bool(host) and (not positive or any(matches(s) for s in positive)) and not any(
        matches(s) for s in negative)


def passage_excerpt(text: str, question: str, budget: int) -> tuple[str, list[dict]]:
    """Rank complete windows before clipping; never clip away their query matches."""
    import math
    from collections import Counter

    from .research import _STOP, _WORDS, evidence_windows
    if len(text) <= budget:
        return text, evidence_windows(text, question)
    terms = {w.casefold() for w in _WORDS.findall(question)
             if len(w) > 2 and w.casefold() not in _STOP}
    width = min(1000, budget)
    candidates = []
    for at in range(0, len(text), max(100, width // 2)):
        raw = text[at:at + width]
        excerpt = raw.strip()
        matched = terms & {w.casefold() for w in _WORDS.findall(excerpt)}
        if matched:
            offset = at + len(raw) - len(raw.lstrip())
            counts = Counter(w.casefold() for w in _WORDS.findall(excerpt))
            candidates.append((offset, excerpt, matched, counts))
    if not candidates:
        return text[:budget], []
    frequency = Counter(term for _, _, matched, _ in candidates for term in matched)
    candidate_count = len(candidates)

    def score(candidate):
        return sum(math.log(1 + candidate_count / (1 + frequency[term]))
                   * (1 + math.log(1 + candidate[3][term]))
                   for term in candidate[2])
    candidates.sort(key=lambda c: (-score(c), c[0]))
    selected, used, evidence = [], 0, []
    for offset, excerpt, matched, _ in candidates:
        if any(abs(offset - e["offset"]) < width for e in evidence):
            continue
        if used + len(excerpt) + (2 if selected else 0) > budget:
            continue
        selected.append(excerpt)
        used += len(excerpt) + (2 if len(selected) > 1 else 0)
        evidence.append({"offset": offset, "excerpt": excerpt,
                         "matched_terms": sorted(matched), "offset_in": "full_extraction"})
        if len(selected) >= 4:
            break
    return "\n\n".join(selected), evidence


def compact_row(row: dict) -> dict:
    """Opt-in removal of duplicate representations, retaining evidence text once."""
    row = dict(row)
    if row.get("html") == row.get("content"):
        row.pop("html", None)
    if row.get("evidence"):
        evidence = []
        for item in row["evidence"]:
            item = dict(item)
            excerpt = item.get("excerpt", "")
            start = row.get("content", "").find(excerpt) if excerpt else -1
            if start >= 0:
                item.pop("excerpt", None)
                item.update(content_start=start, content_end=start + len(excerpt))
            evidence.append(item)
        row["evidence"] = evidence
    return row
