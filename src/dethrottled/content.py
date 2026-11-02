"""Content fidelity and bounded page diagnostics, independent of transport."""

from __future__ import annotations

import codecs
import hashlib
import re
from urllib.parse import urljoin, urlsplit


def assess_content(text: str, html: str = "", *, structured: bool = False) -> dict:
    """Report suspect UI text without rewriting evidence or claiming semantic quality.

    Offsets refer to the full retained extraction, before focus or response clipping.
    Ordinary mentions and quoted examples are insufficient: require a leading error
    instruction or a small, explicitly marked UI container in the source HTML.
    """
    spans = []
    patterns = (
        ("application_error", r"something went wrong[.!]?\s+"
         r"(?:wait a moment and try again|please try again(?: later)?)[.!]?"),
        ("access_wall", r"access (?:to this page has been )?denied(?:[.!]|$)"),
        ("verification", r"verification required[.!]?\s+"
         r"please wait while we verify your request[.!]*"),
        ("interaction_wall", r"click (?:the )?button below to (?:continue|verify)[.!]?"),
    )

    def add(start, end, kind, signal):
        if any(start < s["end"] and end > s["start"] for s in spans):
            return
        if len(spans) < 16:
            spans.append(dict(start=start, end=end, quote=text[start:end], kind=kind,
                              signal=signal, offset_in="full_extraction"))

    quoted_messages = []
    if html and not structured:
        try:
            from selectolax.lexbor import LexborHTMLParser
            quoted_messages = [" ".join(n.text(separator=" ", strip=True).split()).casefold()
                               for n in LexborHTMLParser(html).css("pre,code,blockquote")[:64]]
        except (ImportError, ValueError, TypeError):
            pass
    if not structured:
        for kind, pattern in patterns:
            match = re.match(r"\s*(" + pattern + r")(?=\s|$)", text, re.I)
            if match and not any(" ".join(match[1].split()).casefold() in q
                                 for q in quoted_messages):
                add(match.start(1), match.end(1), kind, "leading_error_instruction")
        if html:
            try:
                from selectolax.lexbor import LexborHTMLParser
                tree = LexborHTMLParser(html)
                for node in tree.css('[role="alert"], [role="status"], [aria-live], '
                                     '.error, .error-message, .alert, #error, #px-captcha')[:64]:
                    parent, quoted = node, False
                    while parent is not None:
                        if parent.tag in {"pre", "code", "blockquote", "script", "template"}:
                            quoted = True
                            break
                        parent = parent.parent
                    message = node.text(separator=" ", strip=True)
                    if quoted or not message or len(message) > 500:
                        continue
                    if not any(re.fullmatch(pattern, message, re.I) for _, pattern in patterns):
                        continue
                    expression = r"\s+".join(re.escape(w) for w in message.split())
                    for match in re.finditer(expression, text, re.I):
                        add(match.start(), match.end(), "error_banner", "source_ui_container")
            except (ImportError, ValueError, TypeError):
                pass
    spans.sort(key=lambda s: s["start"])
    suspected = sum(s["end"] - s["start"] for s in spans)
    return dict(revision=1, text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                pollution=("not_assessed" if structured else
                "suspected" if spans else "none_detected"),
                completeness="unknown", usable_content="unverified",
                inspected_chars=0 if structured else len(text),
                suspected_chars=suspected, unflagged_chars=len(text) - suspected,
                spans=spans)


def annotate_content(row: dict, html: str = "", *, structured: bool = False) -> dict:
    """Attach diagnostics to canonical text; retain all existing evidence and warnings."""
    assessment = assess_content(row.get("text", ""), html, structured=structured)
    row["content_assessment"] = assessment
    if assessment["pollution"] == "suspected":
        row["quality"] = "suspect"
        row["warnings"] = list(dict.fromkeys([*row.get("warnings", []),
            "suspected_error_banner; text_preserved; inspect_content_assessment_spans"]))
    return row


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
        alternatives = []
        for node in tree.css('link[rel="alternate"],link[rel="amphtml"]'):
            target = urljoin(url, node.attributes.get("href", ""))
            kind = node.attributes.get("type", "").split(";")[0].strip().lower()
            if (urlsplit(target).scheme in {"http", "https"} and target != url
                    and node.attributes.get("hreflang", "") in {"", "x-default"}
                    and (kind in {"text/markdown", "application/json", "application/rss+xml",
                                  "application/atom+xml"} or
                         node.attributes.get("rel") == "amphtml")):
                alternatives.append({"url": target, "type": kind,
                                     "relationship": node.attributes.get("rel")})
        canonical_node = tree.css_first('link[rel="canonical"]')
        canonical = (urljoin(url, canonical_node.attributes.get("href", ""))
                     if canonical_node else url)
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
        return {"assets": assets[:24], "content_status": status, "warnings": warnings,
                "source_alternatives": alternatives[:8], "source_canonical": canonical}
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
