#!/usr/bin/env python3
"""Free article extraction: trafilatura, then resiliparse, then selectolax.

All local, all open source, no service call, and every rung ships an aarch64
wheel -- this runs on a Raspberry Pi without a compiler.

The order was set by measuring all five candidates on the same ten pages,
scoring both what they recovered and how much of it was page furniture:

    extractor      median ms   junk %   note
    resiliparse          2.0     5.5%   fastest; misses main content on some
                                        layouts entirely (78 chars on a page
                                        trafilatura read 7,445 from)
    selectolax           2.6     3.1%   fast, and never returns nothing
    readability         27.4     1.5%   low junk because it often returns
                                        almost nothing: 0 chars on one page,
                                        239 on another
    trafilatura         33.4     0.9%   cleanest output, best coverage
    BeautifulSoup       37.2    66.5%   slowest AND two thirds boilerplate

So trafilatura leads on quality. resiliparse is second because it is sixteen
times faster and catches real trafilatura misses -- on one news front page it
recovered 13,955 characters where trafilatura found 3,545. selectolax is the
floor: not a content extractor at all, just a very fast parser with the
furniture removed, which is exactly what a last resort should be.

readability and BeautifulSoup were both dropped. BeautifulSoup was the worst
rung on both axes at once, and readability rarely earned its 27ms.

The cascade matters more than the leader. Any single extractor fails on some
layouts; three with different failure modes get usable text off far more pages
than the best one alone. Whatever produced the text is recorded, so a site that
only ever falls through to the crude tier is visible rather than silently
producing mush.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin

try:
    import trafilatura
    from trafilatura.settings import use_config
    _TRAF_CONFIG = use_config()
    # Default is 10s per document, which is generous on modest hardware and
    # occasionally hangs outright on pathological markup.
    _TRAF_CONFIG.set("DEFAULT", "EXTRACTION_TIMEOUT", "6")
    HAVE_TRAFILATURA = True
except Exception:
    HAVE_TRAFILATURA = False
    _TRAF_CONFIG = None

# A 220-character first-rung fragment can hide a substantially fuller article
# recovered by the next extractor. The 350-character floor was measured on the
# live 40-page sample and previously applied by a host-only startup hook.
MIN_USEFUL_CHARS = 350

# lxml refuses to build a tree containing NULLs or stray control characters and
# raises deep inside drop_tree(), which surfaced as a noisy traceback during
# backfill. Real pages do carry these -- truncated responses, mis-declared
# encodings, embedded binary. Stripping them costs nothing: none of these are
# meaningful in article text.
# XML 1.0 permits #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] |
# [#x10000-#x10FFFF]. Everything outside that makes lxml raise, and readability
# parses through lxml, so one bad codepoint kills the whole extractor.
#
# The C0 set alone was not enough. Pages whose declared encoding disagrees with
# their bytes decode to lone SURROGATES (\ud800-\udfff), which survive a
# C0-only filter and then blow up deep inside lxml_html_clean as "All strings
# must be XML compatible". Observed live during the 16-week backfill: twice in
# the first six weeks, each one a page whose text was silently lost.
_CONTROL_CHARS = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff\ufffe\uffff]"
)


def _strip_control_chars(html: str) -> str:
    return _CONTROL_CHARS.sub("", html or "")

# Boilerplate that survives naive extraction and pollutes evidence summaries.
_JUNK_LINE = re.compile(
    r"^\s*(share this|advertisement|sign up|subscribe|read more|related stories|"
    r"cookie|accept all|newsletter|follow us|©|all rights reserved)\b",
    re.IGNORECASE,
)


def _tidy(text: str, limit: int | None = None) -> str:
    lines = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or _JUNK_LINE.match(line):
            continue
        lines.append(line)
    out = re.sub(r"\s+", " ", " ".join(lines)).strip()
    if limit and len(out) > limit:
        out = out[:limit].rsplit(" ", 1)[0].strip()
    return out


def _via_trafilatura(html: str, url: str) -> dict:
    if not HAVE_TRAFILATURA:
        return {}
    try:
        # favor_precision is NOT set, and that is a measured decision. It cost
        # 5-7% of the text on every page tried -- pv-magazine 1842 against
        # 1905, Wikipedia 5551 against 5726, tomshardware 14771 against 15541,
        # semiwiki 3333 against 3798 -- and the share of characters living in
        # sentence-length lines was identical either way, so what it dropped
        # was article rather than furniture.
        #
        # favor_recall IS set. On the original article sample it returned
        # byte-identical output, but on list- and definition-heavy pages the
        # default drops whole <ul>/<dd> blocks: SQLite's WAL page lost both
        # advantage/disadvantage lists and the WHATWG parsing spec lost its
        # tokenizer-state text (12 Nov 2026 acquisition benchmark). Across the
        # 35 captured benchmark pages recall was never worse, fixed exactly
        # those two, and made no page shorter.
        #
        # include_tables stays on because tables are where the numbers are, and
        # a ledger of cited figures cannot afford to drop them. include_comments
        # stays off because comment threads are the single largest source of
        # off-topic text on the pages this fetches.
        text = trafilatura.extract(
            html, url=url, include_comments=False, include_tables=True,
            favor_recall=True, config=_TRAF_CONFIG,
        )
        if not text or len(text) < MIN_USEFUL_CHARS:
            return {}
        meta = {}
        try:
            doc = trafilatura.extract_metadata(html, default_url=url)
            if doc:
                meta = {
                    "title": doc.title or "",
                    "published": doc.date or "",
                    "author": doc.author or "",
                    "sitename": doc.sitename or "",
                }
        except Exception:
            meta = {}
        return {"text": text, "tier": "trafilatura", **meta}
    except Exception:
        return {}


def _via_resiliparse(html: str, url: str) -> dict:
    """C++/Cython, built for Common Crawl. Sixteen times faster than tier one.

    Higher recall than trafilatura and correspondingly more boilerplate, which
    is the right trade for a SECOND rung: it only runs when the careful one has
    already declined, and some text with a bit of furniture beats none.

    Its `main_content` heuristic is decisive rather than cautious -- on a few
    layouts it locks onto the wrong block and returns almost nothing. That is
    survivable here because there is another rung underneath, and it is exactly
    why this is not tier one.
    """
    try:
        from resiliparse.extract.html2text import extract_plain_text
    except ImportError:
        return {}
    try:
        text = extract_plain_text(html, main_content=True, list_bullets=False,
                                  alt_texts=False, links=False, form_fields=False)
        if not text or len(text) < MIN_USEFUL_CHARS:
            return {}
        return {"text": text, "tier": "resiliparse", "title": _title_of(html)}
    except Exception:
        return {}


def _via_selectolax(html: str, url: str) -> dict:
    """The floor. A very fast HTML parser with the obvious furniture removed.

    Deliberately not clever. Everything above this has already tried to find
    the article and failed, so the useful thing to do is return the page's text
    without the parts that are certainly not article -- and to do it in about
    two milliseconds rather than the thirty-seven BeautifulSoup was taking to
    return two thirds boilerplate.
    """
    try:
        from selectolax.lexbor import LexborHTMLParser
    except ImportError:
        return {}
    try:
        tree = LexborHTMLParser(html)
        for tag in ("script", "style", "nav", "header", "footer", "aside",
                    "form", "noscript", "svg", "iframe", "template"):
            for node in tree.css(tag):
                node.decompose()
        body = tree.body
        if body is None:
            return {}
        text = body.text(separator="\n", strip=True)
        # The separator also lands between inline nodes, so a linked term ends
        # up as "abort a parser , it must" -- re-attach closing punctuation.
        text = re.sub(r"[ \t\n]+([,.;:!?)\]])", r"\1", text)
        text = re.sub(r"([(\[])[ \t\n]+", r"\1", text)
        if not text or len(text) < MIN_USEFUL_CHARS:
            return {}
        title = tree.css_first("title")
        return {"text": text, "tier": "selectolax",
                "title": " ".join(title.text().split()) if title else ""}
    except Exception:
        return {}


def _title_of(html: str) -> str:
    """The <title>, cheaply. Tier one returns metadata of its own; the faster
    rungs do not, and a result without a title is noticeably worse to read."""
    try:
        from selectolax.lexbor import LexborHTMLParser
        node = LexborHTMLParser(html).css_first("title")
        return " ".join(node.text().split()) if node else ""
    except Exception:
        return ""


def _coverage_key(text):
    return " ".join(re.findall(r"\w+", text.casefold()))


def _structural_samples(html):
    """Sample substantive blocks outside known furniture, not an HTML/text ratio."""
    if len(html) < 20000:
        return []
    try:
        from selectolax.lexbor import LexborHTMLParser
        tree = LexborHTMLParser(html)
        for node in tree.css("script,style,nav,header,footer,aside,form,noscript,template"):
            node.decompose()
        blocks = []
        explicit = tree.css("main,article")
        if not explicit and len(tree.css("section")) < 12 and len(tree.css("pre")) < 12:
            return []  # Unstructured page furniture is not evidence of missing article prose.
        # List items and definition descriptions carry the substance of
        # reference pages (feature lists, spec algorithms); sampling only <p>
        # left such pages permanently "not_checked".
        nodes = (tree.css("main p,article p,main pre,article pre,main li,article li,"
                          "main dd,article dd,main td,article td")
                 if explicit else tree.css("p,pre,li,dd,td"))
        # Text-heavy leaf <div>s: app-style pages put prose in bare divs.
        leaves = []
        for node in tree.css("main div,article div" if explicit else "div")[:3000]:
            if node.css_first("div,p,li,section,article,table,pre,ul,ol,dl") is None:
                leaves.append(node)
        nodes = [*nodes, *leaves]
        for node in nodes:
            text = node.text(separator=" ", strip=True)
            if len(text) >= 180:
                key = _coverage_key(text)
                if len(key.split()) >= 25:
                    words = key.split()
                    blocks.append((" ".join(words[:20]), " ".join(words[-20:])))
        if len(blocks) < 12:
            return []
        count = min(24, len(blocks))
        return list(dict.fromkeys(anchor for i in range(count)
            for anchor in blocks[round(i * (len(blocks) - 1) / (count - 1))]))
    except (ImportError, ValueError, TypeError):
        return []


def _compare_coverage(html, url, result):
    samples = _structural_samples(html)
    if not samples:
        return result, {"status": "unverified", "assessment": "not_checked"}

    def covered(candidate):
        key = _coverage_key(candidate.get("text", ""))
        return {i for i, sample in enumerate(samples) if sample in key}

    original_tier = result["tier"]
    kept = covered(result)
    compared = [original_tier]
    # Multiple missing prose samples justify comparison. A small response limit
    # does not: this assessment always precedes caller-visible truncation.
    if len(samples) - len(kept) >= 2:
        alternatives = {"resiliparse": _via_resiliparse, "selectolax": _via_selectolax}
        for name, extractor in alternatives.items():
            if name == original_tier:
                continue
            compared.append(name)
            try:
                candidate = extractor(html, url)
            except Exception:
                candidate = {}
            if not candidate:
                continue
            found = covered(candidate)
            # Preserve all sampled original evidence; do not pick merely longer text.
            if kept < found:
                result = dict(result, **candidate)
                kept = found
            if len(kept) == len(samples):
                break
    missing = len(samples) - len(kept)
    return result, {"status": "suspected_incomplete" if missing >= 2 else "unverified",
                    "assessment": "structural_samples", "sampled_anchors": len(samples),
                    "missing_samples": missing, "compared_extractors": compared,
                    "selection_changed": result["tier"] != original_tier}


def meta_descriptions(html: str) -> list:
    """Page-supplied summaries: OpenGraph/Twitter/meta description and JSON-LD.

    App-style pages (Mastodon and Bluesky profiles, many dashboards) render
    their body client-side; the server still writes the profile bio or page
    summary into these tags, so a thin read can carry it instead of nothing.
    """
    if not html:
        return []
    found = []
    try:
        from selectolax.lexbor import LexborHTMLParser
        tree = LexborHTMLParser(html[:2_000_000])
        for selector in ('meta[property="og:description"]', 'meta[name="description"]',
                         'meta[name="twitter:description"]'):
            for node in tree.css(selector):
                found.append(node.attributes.get("content") or "")
        for node in tree.css('script[type="application/ld+json"]'):
            try:
                data = json.loads(node.text() or "")
            except ValueError:
                continue
            for item in (data if isinstance(data, list) else [data]):
                if isinstance(item, dict) and isinstance(item.get("description"), str):
                    found.append(item["description"])
    except Exception:
        return []
    out = []
    for value in found:
        value = " ".join(value.split())
        if len(value) >= 20 and value.casefold() not in (o.casefold() for o in out):
            out.append(value[:2000])
    return out[:4]


TITLE_BLOCK_MAX_CHARS = 600

_ID_KEYS = ("identifier", "sku", "gtin", "gtin13", "gtin12", "mpn", "isbn", "issn",
            "doi", "version", "softwareVersion", "productID", "serialNumber")
_ID_META = {"citation_doi": "doi", "citation_isbn": "isbn", "citation_issn": "issn",
            "dc.identifier": "identifier", "prism.doi": "doi"}


def _ld_items(data):
    stack = data if isinstance(data, list) else [data]
    while stack:
        item = stack.pop(0)
        if isinstance(item, dict):
            yield item
            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)
        elif isinstance(item, list):
            stack.extend(item)


def page_metadata(html: str) -> dict:
    """Publisher-declared page identity: descriptions, types, canonical URL,
    identifiers. Read from meta tags, JSON-LD and microdata, never inferred.

    Returned on every read so an agent gets a page's declared identity (a
    package URL, DOI, ISBN, version) even when extraction keeps only prose.
    """
    if not html:
        return {}
    out = {"descriptions": meta_descriptions(html)}
    try:
        from selectolax.lexbor import LexborHTMLParser
        tree = LexborHTMLParser(html[:2_000_000])
        identifiers, types = {}, []
        for node in tree.css("meta[name]"):
            key = _ID_META.get((node.attributes.get("name") or "").lower())
            value = " ".join((node.attributes.get("content") or "").split())
            if key and value:
                identifiers.setdefault(key, value[:300])
        for node in tree.css("[itemprop]"):
            prop = node.attributes.get("itemprop") or ""
            if prop in _ID_KEYS:
                value = node.attributes.get("content") or " ".join(node.text().split())
                if value:
                    identifiers.setdefault(prop, value[:300])
        for node in tree.css('script[type="application/ld+json"]'):
            try:
                data = json.loads(node.text() or "")
            except ValueError:
                continue
            for item in _ld_items(data):
                kind = item.get("@type")
                for t in (kind if isinstance(kind, list) else [kind]):
                    if isinstance(t, str) and t not in types:
                        types.append(t)
                for key in _ID_KEYS:
                    value = item.get(key)
                    if isinstance(value, dict):
                        value = value.get("value") or value.get("@id")
                    if isinstance(value, (str, int, float)) and str(value).strip():
                        identifiers.setdefault(key, str(value).strip()[:300])
        og = tree.css_first('meta[property="og:type"]')
        if og and og.attributes.get("content") and og.attributes["content"] not in types:
            types.append(og.attributes["content"])
        canonical = tree.css_first('link[rel="canonical"]')
        if canonical and canonical.attributes.get("href"):
            out["canonical"] = canonical.attributes["href"][:2048]
        if identifiers:
            out["identifiers"] = dict(list(identifiers.items())[:12])
        if types:
            out["types"] = types[:8]
    except Exception:
        pass
    return {k: v for k, v in out.items() if v}


def _title_block(html: str) -> str:
    """The compact block around the page's <h1>, if it is compact.

    Registry and product pages keep identifiers beside the heading -- Maven
    Central's package URL, a crate's version, a project's tags -- in labels
    and spans that article extractors classify as furniture.
    """
    try:
        from selectolax.lexbor import LexborHTMLParser
        tree = LexborHTMLParser(html)
        for node in tree.css("script,style,svg,noscript,template,button"):
            node.decompose()
        heading = tree.css_first("h1")
        parent = heading.parent if heading else None
        if parent is None or parent.tag in {"body", "html"}:
            return ""
        text = " ".join(parent.text(separator=" ", strip=True).split())
        text = re.sub(r" ([,.;:!?)\]])", r"\1", text)
        return text if 0 < len(text) <= TITLE_BLOCK_MAX_CHARS else ""
    except Exception:
        return ""


# A main-content pick this small, beside a second extractor finding several
# times more text, usually means the first locked onto one block of an
# app-style page (Crunchbase: trafilatura 664 chars of 130K visible text,
# resiliparse 7.4K including the location and founding facts).
THIN_PICK_CHARS = 2000
THIN_PICK_RATIO = 3


# Coverage form of the same guard: whatever its size, a trafilatura pick that
# holds under THIN_PICK_COVERAGE of the page's visible text (furniture removed)
# on a page with at least THIN_PICK_VISIBLE characters is compared too.
THIN_PICK_COVERAGE = 0.10
THIN_PICK_VISIBLE = 5000


def _visible_chars(html):
    """Visible text size with furniture removed; a measurement, not an extraction."""
    try:
        from selectolax.lexbor import LexborHTMLParser
        tree = LexborHTMLParser(html)
        for node in tree.css("script,style,nav,header,footer,aside,form,noscript,svg,"
                             "iframe,template"):
            node.decompose()
        return len(" ".join((tree.body.text(separator=" ") if tree.body else "").split()))
    except Exception:
        return 0


def _guard_thin_choice(html, url, result, completeness):
    if result.get("tier") != "trafilatura":
        return result, completeness
    chosen = len(result.get("text", ""))
    small = chosen < THIN_PICK_CHARS
    if not small:
        # Visible text never exceeds the HTML, so a pick holding a tenth of the
        # raw markup cannot fall under the coverage floor: skip the measurement.
        if chosen >= len(html) * THIN_PICK_COVERAGE:
            return result, completeness
        visible = _visible_chars(html)
        if visible < THIN_PICK_VISIBLE or chosen >= visible * THIN_PICK_COVERAGE:
            return result, completeness
    try:
        alternative = _via_resiliparse(html, url)
    except Exception:
        alternative = {}
    if not alternative or len(alternative.get("text", "")) < max(MIN_USEFUL_CHARS,
                                                                 chosen * THIN_PICK_RATIO):
        return result, completeness
    merged = dict(result, text=alternative["text"], tier=alternative["tier"])
    return merged, dict(completeness, assessment="thin_primary_compared",
                        compared_extractors=["trafilatura", "resiliparse"],
                        selection_changed=True, primary_chars=chosen,
                        selected_chars=len(alternative["text"]))


def extract(html: str, url: str = "", *, max_chars: int = 3500) -> dict:
    """Return {ok, text, tier, title, published, chars, reason}."""
    if not html or len(html) < 200:
        return {"ok": False, "text": "", "tier": None, "reason": "empty_html",
                "title": "", "published": "", "chars": 0}

    html = _strip_control_chars(html)
    for extractor in (_via_trafilatura, _via_resiliparse, _via_selectolax):
        try:
            result = extractor(html, url)
        except Exception:
            # An extractor blowing up must not end the cascade -- that is the
            # entire reason there are three of them.
            result = {}
        if not result:
            continue
        result, completeness = _compare_coverage(html, url, result)
        result, completeness = _guard_thin_choice(html, url, result, completeness)
        text = _tidy(result["text"])
        block = _title_block(html)
        if block and _coverage_key(block) not in _coverage_key(text):
            text = block + " " + text
            completeness = dict(completeness, title_block_added=True)
        metadata = page_metadata(html)
        # Declared identifiers missing from the text are kept with it as well,
        # wherever the page placed them (JSON-LD, microdata, citation meta).
        missing = {k: v for k, v in (metadata.get("identifiers") or {}).items()
                   if _coverage_key(v) and _coverage_key(v) not in _coverage_key(text)}
        if missing:
            text = "Identifiers: " + "; ".join(f"{k} {v}" for k, v in missing.items()) + ". " + text
            completeness = dict(completeness, identifiers_added=sorted(missing))
        # Clipping to the cache limit must be visible: Moby-Dick (1.21M chars)
        # was cut at 1M and still reported complete, losing its last 18%.
        clipped = bool(max_chars) and len(text) > max_chars
        if clipped:
            text = text[:max_chars].rsplit(" ", 1)[0].strip()
        if len(text) < MIN_USEFUL_CHARS:
            continue
        return {
            "ok": True,
            "text": text,
            "tier": result["tier"],
            "title": result.get("title", ""),
            "published": result.get("published", ""),
            "author": result.get("author", ""),
            "chars": len(text),
            "reason": "",
            "completeness": completeness,
            "page_metadata": metadata,
            "clipped": clipped,
            "warnings": ((["extraction_missing_structural_samples"]
                          if completeness["status"] == "suspected_incomplete" else [])
                         + (["extraction_cache_limit"] if clipped else [])),
        }

    return {"ok": False, "text": "", "tier": None, "reason": "no_extractor_succeeded",
            "title": "", "published": "", "chars": 0}


def links(html: str, url: str = "", *, max_chars: int = 3500) -> str:
    """The page's text with its anchors kept, as markdown links.

    A separate function rather than a flag on extract() because the two want
    opposite things. extract() is hunting for the article and throwing the
    navigation away; this is for callers who came FOR the navigation -- link
    discovery, crawl frontiers, "what does this index page point at". Running
    the article extractors first and re-attaching hrefs afterwards would mean
    parsing twice to recover exactly what the first parse set out to discard.

    Relative hrefs are resolved against the page, so a caller can fetch what
    comes back without knowing where it came from. Returns "" rather than
    raising: this is a degraded-quality answer at worst, never a failed
    request, and the caller already has the prose from the normal path.
    """
    try:
        from selectolax.lexbor import LexborHTMLParser
    except ImportError:
        return ""
    try:
        tree = LexborHTMLParser(html)
        for tag in ("script", "style", "nav", "header", "footer", "aside",
                    "form", "noscript", "svg", "iframe", "template"):
            for node in tree.css(tag):
                node.decompose()
        body = tree.body
        if body is None:
            return ""
        for anchor in body.css("a"):
            href = (anchor.attributes.get("href") or "").strip()
            text = " ".join(anchor.text().split())
            if not href or not text:
                continue
            if href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            anchor.replace_with("[%s](%s)" % (text, urljoin(url, href)))
        # Same de-duplication the article path does, for the same reason: a
        # nav rendered twice for mobile and desktop is one link, not two.
        seen = {}
        for line in body.text(separator="\n", strip=True).splitlines():
            line = line.strip()
            if line:
                seen.setdefault(line, None)
        return "\n".join(seen)[:max_chars]
    except Exception:
        return ""


def available() -> dict:
    """Which rungs of the cascade this installation actually has.

    selectolax is reported rather than assumed: it is the floor, so if it is
    missing the cascade has no last resort and a trafilatura failure becomes a
    failed extraction rather than a scruffy one.
    """
    def have(module):
        import importlib.util
        return importlib.util.find_spec(module) is not None

    return {
        "trafilatura": HAVE_TRAFILATURA,
        "resiliparse": have("resiliparse"),
        "selectolax": have("selectolax"),
    }
