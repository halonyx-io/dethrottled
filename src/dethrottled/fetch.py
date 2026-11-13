#!/usr/bin/env python3
"""Content-driven fetching through configured acquisition and recovery tiers.

The normal ladder tries direct HTTP, optional browser-like TLS through
curl_cffi, a configured Crawl4AI renderer, and conditional headed-browser
recovery. Rendering restrictions and local budgets control which tiers run.
All acquisition tiers run through the configured local transports and workers.
No hosted-reader fallback is provided.

Content validity, format-aware minimums and challenge detection drive escalation.
HTTP 200 alone does not make an empty JavaScript shell or a verification page a
successful read. Results retain acquisition provenance, warnings and partial
content signals. The caller must still assess whether the evidence is useful.

The fetch ladder does not request or consult robots.txt.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections import defaultdict
from contextvars import ContextVar
from datetime import datetime, timezone
from itertools import chain
from types import MappingProxyType
from urllib.parse import urljoin, urlparse

from . import __version__, adblock, workers
from . import netfilter as requests
from .challenges import classify as challenge_kind
from .content import decode_html, page_details, short_text, smart_truncate
from .urls import (
    canonical_url as canonical_url,
)

_READ_OPTIONS = ContextVar("read_options", default=MappingProxyType({}))


class TargetPolicyError(ValueError):
    """A public-target policy refusal, not a recoverable transport failure."""


def _get_with_policy(get, url, **kwargs):
    """Validate every redirect target for reads made through a public adapter."""
    from . import adblock
    if not _READ_OPTIONS.get().get("public_only"):
        return requests.get_using(get, url, **kwargs)
    from .research import public_url
    for _ in range(6):
        adblock.check(url)
        if not public_url(url):
            raise TargetPolicyError("public_target_required")
        response = get(url, **dict(kwargs, allow_redirects=False))
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response
        location = response.headers.get("Location")
        if hasattr(response, "close"):
            response.close()
        if not location:
            raise ValueError("redirect_without_location")
        url = urljoin(url, location)
    raise ValueError("too_many_redirects")

PROJECT_URL = "https://github.com/halonyx-io/dethrottled"

# Identify this fetcher and keep a contact URL. Operators can override it for
# their own deployment. The fetch ladder does not consult robots.txt.
#
# Two things here were wrong and both undercut that claim. The URL was still
# the templating placeholder, so every request we made announced an address
# that 404s -- an unreachable contact is not a contact. And the version was
# frozen at "0.1" by hand, which is how server.py ended up two releases stale.
# The version is stated in exactly one place, __init__.py, and read from there.
USER_AGENT = os.environ.get(
    "DETHROTTLED_USER_AGENT",
    "dethrottled/%s (+%s; automated fetcher)"
    % (__version__, PROJECT_URL))
# 10MB, not 3. A truncated HTML download is worse than a failed one: the parser
# still succeeds, on a document missing its tail, and reports a short article
# rather than an error. Real pages are already close to the old ceiling --
# tomshardware measured 2.34MB, 78% of it -- so this was going to start
# silently shortening articles rather than obviously breaking. Median is 0.36MB
# and the buffer is transient, so the headroom is close to free.
MAX_BYTES = int(os.environ.get("DETHROTTLED_MAX_HTML_BYTES", str(10_000_000)))


DEFAULT_TIMEOUT = 20
# Bound connection establishment separately; slow downloads keep their read budget.
CONNECT_TIMEOUT = max(0.1, float(os.getenv("DETHROTTLED_CONNECT_TIMEOUT", "2")))
MIN_DOMAIN_GAP = 1.5


# A real browser TLS fingerprint, without a browser.
#
# A great deal of what gets called "bot detection" never looks at your User-
# Agent: it looks at the shape of the TLS handshake -- cipher order, extension
# order, ALPN, the JA3/JA4 hash -- and every Python HTTP client has a
# conspicuously non-browser one. curl_cffi borrows a real Chrome's.
#
# Measured, this is not a slower fallback but a FASTER one: 310ms median
# against plain requests' 536ms on the same page set, because curl-impersonate
# is C. It sits second in the ladder for that reason.
#
# It does NOT render JavaScript, and it does not fix everything. Two hosts in
# testing returned 403 to every fingerprint tried -- chrome, chrome131,
# chrome124, safari17_0, safari15_5, edge101, firefox133. Those observations did
# not establish which upstream control
# caused the refusal; a failed profile sweep is not an IP-reputation diagnosis.
TLS_IMPERSONATE = os.environ.get("DETHROTTLED_TLS_IMPERSONATE", "chrome")

# Its own short timeout, and this is not a detail -- it is the whole reason the
# tier is safe to add.
#
# Measured: giving it the standard 20s turned a 25s bulk page budget into
# "direct, then tls, then nothing left". The renderer went from 6 solves to 4
# and outright failures went from 7 to 16, while tls itself solved 2. A tier
# that occasionally helps must never be able to spend the budget belonging to
# the tier that usually helps.
#
# 8s is generous for something whose median is 310ms. If it has not answered by
# then it was never going to be the cheap option.
TLS_TIMEOUT = int(os.environ.get("DETHROTTLED_TLS_TIMEOUT", "8"))
# Profile choice is not cosmetic. On one host chrome/safari/firefox all
# returned 200 and edge101 returned 403; on another the chrome family returned
# 163KB where every other profile returned 8KB.
ENABLE_TLS = os.environ.get("DETHROTTLED_ENABLE_TLS", "1").strip() not in (
    "0", "false", "no", "off", "")

# Empty by default. The render tier needs a Crawl4AI service you run; with no
# URL configured the tier is skipped entirely and the ladder is one rung
# shorter. `docker compose up` sets this for you.
CRAWL4AI_URL = os.environ.get("DETHROTTLED_CRAWL4AI_URL", "").rstrip("/")

# Which dialect the renderer speaks.
#
#   "auto"   probe once, remember the answer  (default)
#   "crawl"  upstream Crawl4AI: POST /crawl, port 11235
#   "render" a service exposing POST /render {url, timeout_ms}
#
# Two dialects because the upstream Docker image and a hand-rolled render
# worker are both perfectly reasonable things to point this at, and guessing
# wrong costs a silent dead tier rather than a loud error -- the failure this
# option exists to prevent. "auto" tries /crawl and falls back to /render, then
# caches which one answered so the cost is one extra request per process.
CRAWL4AI_API = os.environ.get("DETHROTTLED_CRAWL4AI_API", "auto").strip().lower()

# Remembered across calls within a process. None = not yet probed.
_crawl4ai_dialect = None if CRAWL4AI_API == "auto" else CRAWL4AI_API
# 25 rather than 90. Measured: this tier solved 1 page in 75 across two
# profiles. A ninety-second licence for a one-in-seventy-five tier means one
# page can cost more than the other forty-nine together.
CRAWL4AI_TIMEOUT = int(os.environ.get("DETHROTTLED_CRAWL4AI_TIMEOUT", "25"))

# The renderer's credential, when it has one.
#
# Upstream Crawl4AI refuses to listen on anything but loopback unless
# CRAWL4AI_API_TOKEN is set -- gunicorn's bind address is chosen from whether a
# credential exists. That is a sound default: a renderer reachable on a network
# with no auth is an open proxy that also runs a browser.
#
# So a containerised renderer necessarily has a token, and this must send it.
# Empty is normal for a loopback renderer that never needed one.
CRAWL4AI_TOKEN = os.environ.get("DETHROTTLED_CRAWL4AI_TOKEN", "").strip()


def _crawl4ai_headers() -> dict:
    return {"Authorization": "Bearer %s" % CRAWL4AI_TOKEN} if CRAWL4AI_TOKEN else {}

# Whole-page admission budget, checked before each tier. Configured renderers
# and headed recovery may need more time than direct HTTP; this bounds their
# admission without changing individual transport timeouts.
PAGE_BUDGET = float(os.environ.get("DETHROTTLED_PAGE_BUDGET", "60"))

# Bulk stays lean. search-and-extract runs its results one after another, so a
# generous per-page ceiling multiplies: six results at 60s each is six minutes
# for one search. Same one-versus-many split that governs OCR and the caps.
PAGE_BUDGET_BULK = float(os.environ.get("DETHROTTLED_PAGE_BUDGET_BULK", "25"))
# Must stay UNDER CRAWL4AI_TIMEOUT. It was 45000 against a 25s HTTP timeout,
# so we hung up at 25s on a renderer we had just asked to work for 45 -- paying
# the full wait, discarding the result, and leaving it rendering a page nobody
# would collect. 20s of render inside a 25s wait leaves slack for transport.
CRAWL4AI_RENDER_MS = int(os.environ.get("DETHROTTLED_CRAWL4AI_RENDER_MS", "20000"))
# Re-enabled 2026-08-26 after the worker was repaired.
#
# It was previously disabled because /render never returned: the service was
# capped at MemoryHigh=750M, and the kernel had throttled it into reclaim 7,392
# times. Two renders stalled, never released their semaphore slots, and every
# later request queued forever behind them while /health stayed green.
#
# Fixed at the source: limits raised to 1500M/2G, and the worker now bounds
# both slot acquisition and the render itself so a stall can no longer wedge
# it. Measured after the fix: example.com 2.1s, TrendForce 3.1s, DIGITIMES
# 3.4s, zero throttle events across 12 renders.
#
# It earns its slot in the ladder: DIGITIMES yields 432 chars through the CF
# Worker and 21,896 through the renderer.
# Local rendering is bounded by concurrent work and a fair queue. A positive
# legacy budget remains an explicit operator ceiling; zero disables rendering.
CRAWL4AI_BUDGET = int(os.environ.get("DETHROTTLED_CRAWL4AI_BUDGET", "-1"))
from .admission import AdmissionError, FairQueue  # noqa: E402

_RENDER_QUEUE = FairQueue(
    capacity=int(os.getenv("DETHROTTLED_RENDER_CONCURRENCY", "2")),
    max_waiting=int(os.getenv("DETHROTTLED_RENDER_MAX_WAITING", "32")),
    per_client=int(os.getenv("DETHROTTLED_RENDER_PER_CLIENT", "8")))
_HEADED_QUEUE = FairQueue(capacity=1, max_waiting=32, per_client=8)

_locks = defaultdict(threading.Lock)
_last_hit = {}
_lock_guard = threading.Lock()
_tier_stats = defaultdict(int)

# Tier budgets refill on a rolling window. An explicitly configured renderer
# ceiling must not become a process-lifetime cap in a long-running service.
BUDGET_WINDOW = float(os.environ.get("DETHROTTLED_TIER_BUDGET_WINDOW", "3600"))
_spent = defaultdict(list)
_spend_guard = threading.Lock()


def _spend(tier: str, budget: int) -> bool:
    """Take one unit of a tier budget. False when the window is exhausted."""
    now = time.time()
    with _spend_guard:
        recent = [used for used in _spent[tier] if now - used < BUDGET_WINDOW]
        if len(recent) >= budget:
            _spent[tier] = recent
            return False
        recent.append(now)
        _spent[tier] = recent
        return True


def budget_state() -> dict:
    """How much of each tier's window is spent. For /stats, and for diagnosis."""
    now = time.time()
    with _spend_guard:
        return {tier: len([u for u in used if now - u < BUDGET_WINDOW])
                for tier, used in _spent.items()}


def tier_stats() -> dict:
    return dict(_tier_stats)


def reset_tier_stats() -> None:
    _tier_stats.clear()
    with _spend_guard:
        _spent.clear()


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _throttle(domain: str) -> None:
    with _lock_guard:
        lock = _locks[domain]
    with lock:
        wait = MIN_DOMAIN_GAP - (time.time() - _last_hit.get(domain, 0.0))
        if wait > 0:
            time.sleep(wait)
        _last_hit[domain] = time.time()


def valid_url(url: str) -> bool:
    """Is this something we could fetch at all?"""
    try:
        parts = urlparse((url or "").strip())
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


# Below this a result is "thin": technically prose, but too little to be worth
# stopping on. Tracked separately from a plain success because a 432-character
# teaser off a paywall satisfies a naive length check while being useless: the
# fetch worked, the page is still not readable, and those are different facts.
THIN_CHARS = int(os.environ.get("DETHROTTLED_THIN_CHARS", "600"))

# An application shell: plenty of HTML but little readable text, served before
# client-side rendering. A static tier stopping on it reports success while
# the content (NSE's index data, a Mastodon profile) has not been read. Below
# SHELL_MAX_TEXT characters with at least SHELL_HTML_RATIO bytes of HTML per
# character of text, the result is kept only as a floor and rendering tiers
# are tried. Thresholds follow web-researcher-mcp's measured shell heuristic.
SHELL_MAX_TEXT = int(os.environ.get("DETHROTTLED_SHELL_MAX_TEXT", "2048"))
SHELL_HTML_RATIO = int(os.environ.get("DETHROTTLED_SHELL_HTML_RATIO", "20"))
# Tiers a shell can escalate FROM. Static reads go on to rendering; a thin
# crawl render goes on to the headed browser. Headed is last: nothing follows.
SHELL_TIERS = {"direct", "tls", "crawl4ai"}


def _looks_like_shell(name: str, candidate: dict, html) -> bool:
    """`html` is the page source, or its byte count when only that was kept."""
    # Judge the page's own text: an added metadata description must not lift a
    # shell over the threshold (NSE: 1,941 body chars became 2,576).
    chars = int(candidate.get("extraction", {}).get("pre_supplement_chars")
                or candidate.get("chars") or 0)
    size = html if isinstance(html, int) else len(html or "")
    rendered = name == "crawl4ai"
    return (name in SHELL_TIERS
            and (rendered or candidate.get("content_type") == "html")
            and 0 < chars < SHELL_MAX_TEXT and size >= SHELL_HTML_RATIO * chars)


def _supplement_thin(candidate: dict, html: str, descriptions=None) -> None:
    """Prefix page-supplied descriptions to a short HTML read that lacks them."""
    if (candidate.get("chars") or 0) >= SHELL_MAX_TEXT or not (html or descriptions):
        return
    if candidate.get("content_type") not in {"html", "", None}:
        return
    text = candidate.get("text") or ""
    folded = " ".join(text.split()).casefold()
    from . import extract as _fx
    found = _fx.meta_descriptions(html) if html else list(descriptions or [])
    extra = [d for d in found if d.casefold() not in folded]
    if not extra:
        return
    text_chars = int(candidate.get("chars") or len(text))
    candidate["text"] = "\n\n".join([*extra, text]).strip()
    candidate["chars"] = len(candidate["text"])
    candidate["extraction"] = {**candidate.get("extraction", {}),
                               "metadata_supplement": len(extra),
                               "pre_supplement_chars": text_chars}
    candidate["warnings"] = [*candidate.get("warnings", []), "page_metadata_description_added"]


def _tidy_text(value: str, limit: int | None = None) -> str:
    """Collapse whitespace on text a tier already extracted for us."""
    import re as _re
    out = _re.sub(r"\s+", " ", str(value or "")).strip()
    if limit and len(out) > limit:
        out = out[:limit].rsplit(" ", 1)[0].strip()
    return out


# A truncated PDF is not a short PDF. The cross-reference table lives at the
# END of the file, so cutting the stream mid-download yields bytes no parser
# can open -- an 8.3MB statistics yearbook failed as "no text layer" for
# exactly that reason, against the 3MB MAX_BYTES meant for runaway HTML.
# So PDFs get their own, larger budget and are downloaded whole or not at all.
# Spreadsheets and decks are small next to PDFs, and anything claiming to be a
# 50MB xlsx is not a statistics table. Kept separate from PDF_MAX_BYTES so the
# two can move independently.
DOC_MAX_BYTES = int(os.environ.get("DETHROTTLED_DOC_MAX_BYTES", str(50 * 1024 * 1024)))

PDF_MAX_BYTES = int(os.environ.get("DETHROTTLED_PDF_MAX_BYTES", str(25 * 1024 * 1024)))


def _pdf_text(data: bytes, limit: int) -> str:
    """Text from a PDF, or "" if it has none.

    Rejecting PDFs outright at the content-type gate is the wrong call, because
    a great deal of primary material is published as a PDF and as nothing else
    -- statistical releases, standards, filings, tender documents. A source that
    only exists as a PDF would simply be unreachable.

    pymupdf was already installed. Pages are read until the limit is reached
    rather than all of them, because a 300-page annual report costs seconds to
    parse and the first few pages are what any cap keeps anyway.

    A scanned PDF has no text layer and returns "" here. That is correct: the
    caller then falls through to the next tier and reports it thin, rather than
    this claiming success with an empty body.
    """
    try:
        import pymupdf
    except ImportError:                               # pragma: no cover
        return ""
    parts, total = [], 0
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            # PDF drawing order is not necessarily reading order. In a page
            # whose footer was added before its heading, the default returned
            # footer, body, heading. Position sorting restored the visible
            # heading, body, footer sequence without another parser or model.
            chunk = page.get_text(sort=True)
            parts.append(chunk)
            total += len(chunk)
            if total >= limit:
                break
    return "\n".join(parts)


# Classify the interstitial, then attempt browser recovery within the read policy.
def _is_challenge(status: int, headers, body: str) -> bool:
    if status in {403, 429, 503} and (body or "")[:200].lower().lstrip().startswith(
            "just a moment"):
        return True
    return bool(challenge_kind(body, headers))


def _http_reason(prefix: str, status: int, headers, body: str) -> str:
    """The reason string for a non-200, told apart properly."""
    if _is_challenge(status, headers, body):
        return "%schallenge_detected" % prefix
    return "%shttp_%d" % (prefix, status)


def _usable(html: str) -> bool:
    return bool(html) and len(html) > 800


# ── tiers ────────────────────────────────────────────────────────────────────

def _filename_hint(headers, fallback):
    from email.message import Message
    message = Message()
    message["content-disposition"] = headers.get("Content-Disposition", "")
    return message.get_filename() or fallback


def _binary_payload(blob, url, ctype, allow_ocr, filename=""):
    from . import formats
    kind = formats.kind_of(blob, filename or url, ctype)
    if not kind:
        return None
    try:
        sink = _READ_OPTIONS.get().get("source_sink")
        if sink is not None:
            sink(blob, filename or url.rsplit("/", 1)[-1])
        options = dict(_READ_OPTIONS.get(), filename=(filename or url.rsplit("/", 1)[-1]))
        text, metadata = formats.read_blob(blob, kind, CACHE_CHARS,
                                           allow_ocr=(allow_ocr
                                                      and options.get("ocr_mode") != "never"),
                                           options=options)
        import hashlib
        metadata.update(source_sha256=hashlib.sha256(blob).hexdigest(), source_bytes=len(blob))
        if not text.strip():
            raise ValueError("document_empty:" + kind)
        if metadata.get("partial"):
            metadata.setdefault("warnings", []).append(
                "Partial extraction; inspect page/member metadata or request another range.")
        return ({"text": text, "structured": True, "content_type": kind,
                 "extraction": metadata, "warnings": metadata.get("warnings", []),
                 "content_status": "partial" if metadata.get("partial") else "complete"},
                "", url)
    except Exception as exc:
        return ({}, "document_parse_failed:" + str(exc)[:120], url)


def _tier_direct(url: str, timeout: int, allow_ocr: bool = False) -> tuple:
    from .identity import POOL
    options = _READ_OPTIONS.get()
    with POOL.borrow(options.get("admission_key", "local"), url, "http",
                     public_only=options.get("public_only", False)) as get:
        return _tier_direct_once(url, timeout, allow_ocr, get=get)


def _origin_response(response):
    return {"status": response.status_code,
            "last_modified": (response.headers.get("Last-Modified") or "")[:128] or None}


def _tier_direct_once(url: str, timeout: int, allow_ocr: bool = False, *, get=None) -> tuple:
    domain = _domain(url)
    response = None
    try:
        _throttle(domain)
        response = _get_with_policy(get or requests.get,
            url, timeout=(min(CONNECT_TIMEOUT, timeout), timeout),
            stream=True, allow_redirects=True,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            })
        if response.status_code != 200:
            # The response is streamed specifically to bound memory use. Do
            # not read ``response.content`` here: an error page can itself be
            # huge, and checking it would buffer the entire body before the
            # 8KB challenge detector gets a chance to inspect it.
            error_head = bytearray()
            for chunk in response.iter_content(8192):
                error_head.extend(chunk[:8192 - len(error_head)])
                if len(error_head) >= 8192:
                    break
            response.close()
            final_url = str(getattr(response, "url", None) or url)
            return "", _http_reason("", response.status_code,
                                    response.headers,
                                    error_head.decode(response.encoding or "utf-8",
                                                      errors="replace")), final_url
        ctype = response.headers.get("Content-Type", "")
        # Read the first chunk before choosing a parser. A server's header or
        # the URL can lie in either direction: a PDF may be served as HTML, and
        # an HTML error page may arrive with a spreadsheet Content-Type.
        chunks = iter(response.iter_content(65536))
        first = next(chunks, b"")
        head = first[:1024].lstrip().lower()
        is_html = head.startswith((b"<!doctype", b"<html"))
        from . import formats
        filename = _filename_hint(response.headers, str(response.url))
        binary_kind = formats.kind_of(first, filename, ctype)
        if binary_kind and not is_html:
            data, size = [], 0
            ceiling = PDF_MAX_BYTES if binary_kind == "pdf" else DOC_MAX_BYTES
            for chunk in chain((first,), chunks):
                size += len(chunk)
                if size > ceiling:
                    if hasattr(response, "close"):
                        response.close()
                    return {}, "document_too_large", str(response.url)
                data.append(chunk)
            payload, reason, final = _binary_payload(
                b"".join(data), str(response.url), ctype, allow_ocr, filename)
            if isinstance(payload, dict) and payload:
                payload["origin_response"] = _origin_response(response)
            return payload, reason, final
        if not is_html and "html" not in ctype and "xml" not in ctype:
            return "", "content_type:%s" % ctype[:30], url
        html_chunks, size, clipped = [], 0, False
        for chunk in chain((first,), chunks):
            html_chunks.append(chunk)
            size += len(chunk)
            if size > MAX_BYTES:
                clipped = True
                break
        html = decode_html(b"".join(html_chunks), ctype)
        # Truncation used to be invisible. It has to be reported, because the
        # symptom is a short article rather than a failure, and a short article
        # is indistinguishable from a page that was simply short.
        return ({"html": html, "clipped": clipped, "origin_response": _origin_response(response)},
                "html_truncated" if clipped else "", str(response.url))
    except Exception as exc:
        return ({}, str(exc) if isinstance(exc, (adblock.AdblockBlocked, TargetPolicyError))
                else type(exc).__name__, url)
    finally:
        if response is not None and hasattr(response, "close"):
            response.close()


def _crawl4ai_payload(payload: dict, url: str) -> tuple:
    """Pull usable content out of whatever shape the renderer returned.

    Crawl4AI ALREADY EXTRACTS, and its extraction is better than re-extracting
    from its HTML. Measured on a JavaScript-heavy article: the cleaned HTML was
    6,586 characters that trafilatura could not read at all, while the markdown
    held 2,339 characters of clean prose. Running a local extractor over
    somebody else's good extraction threw the good extraction away.

    So markdown wins when there is enough of it, and the HTML fields are the
    fallback for a renderer that does not produce markdown.
    """
    final = payload.get("url") or url

    markdown = payload.get("markdown")
    # Upstream returns either a string or {raw_markdown, fit_markdown, ...}.
    # fit_markdown is the filtered one and is preferred when present, because
    # unfiltered markdown of a news page is mostly navigation.
    if isinstance(markdown, dict):
        markdown = (markdown.get("fit_markdown")
                    or markdown.get("raw_markdown")
                    or markdown.get("markdown"))
    html = ""
    # Selectors and raw callers need the source DOM, not the extractor's
    # cleaned article fragment. Prefer the full page HTML when requested.
    keep_html = _READ_OPTIONS.get().get("keep_html")
    fields = (("html", "raw_html", "cleaned_html", "fit_html", "content")
              if keep_html
              else ("cleaned_html", "fit_html", "content", "html", "raw_html"))
    for field in fields:
        value = payload.get(field)
        # A selector/raw caller can legitimately ask for a tiny page; do not
        # discard a small but valid source DOM behind the prose threshold.
        if isinstance(value, str) and (len(value) > 8 if keep_html else _usable(value)):
            html = value
            break
    source = next((payload[f] for f in ("html", "raw_html") if isinstance(payload.get(f), str)), "")
    # Kept even when the HTML is not: rendered output gets the same shell test
    # and page-description supplement as a static read.
    rendered = {"source_html_bytes": len(source)} if source else {}
    if source:
        from . import extract as _fx
        metadata = _fx.page_metadata(source)
        if metadata:
            rendered["page_metadata"] = metadata
        if metadata.get("descriptions"):
            rendered["page_descriptions"] = metadata["descriptions"]
    if isinstance(markdown, str) and len(markdown.strip()) > 220:
        result = {"text": markdown, **rendered}
        # Markdown wins for prose, but selectors/raw callers still need the
        # source DOM. Only retain it when the request asked for HTML.
        if html and _READ_OPTIONS.get().get("keep_html"):
            result["html"] = html
        return result, "", final

    if html:
        return {"html": html, **rendered}, "", final
    return {}, "crawl4ai_empty", url


def _crawl4ai_target_error(payload: dict) -> str:
    """Report the target page's HTTP failure, even when rendering succeeded.

    Crawl4AI's ``success`` means it produced a page. A rendered 404 can still
    contain enough prose to pass our extraction threshold. On redirects, the
    final response status takes precedence over the original response status.
    """
    headers = payload.get("response_headers") or {}
    if any(k.lower() == "x-dethrottled-blocked" and v == "adblock" for k, v in headers.items()):
        return "adblock_blocked:browser_navigation"
    status = payload.get("redirected_status_code")
    if status is None:
        status = payload.get("status_code")
    try:
        code = int(status)
    except (TypeError, ValueError):
        return ""
    return "crawl4ai_target_http_%d" % code if code >= 400 else ""


def _crawl4ai_via_crawl(url: str) -> tuple:
    """Upstream Crawl4AI's Docker API: POST /crawl on :11235.

    The response wraps results in a list, because the endpoint takes a list of
    URLs. One URL in, one result out, but the envelope is still there.
    """
    payload = {"urls": [url],
              "browser_config": {"type": "BrowserConfig",
                                 "params": {"headless": True}},
              "crawler_config": {"type": "CrawlerRunConfig",
                                 "params": {"cache_mode": "bypass",
                                            "check_robots_txt": False,
                                            "page_timeout": CRAWL4AI_RENDER_MS,
                                            "delay_before_return_html": _READ_OPTIONS.get().get(
                                                "render_delay", 0.5),
                                            **({"wait_for": "css:" +
                                                _READ_OPTIONS.get()["wait_for"]}
                                               if _READ_OPTIONS.get().get("wait_for") else {})}}}
    headers = _crawl4ai_headers()
    if os.getenv("DETHROTTLED_DNB", "0") == "1":
        from .access import CLAIMS, read_session_alias
        from .delegation import sign
        claims = CLAIMS.get()
        from .research import browser_public
        public = bool(claims) or browser_public(url, _READ_OPTIONS.get().get("public_only", False))
        headers["X-DNB-Delegation"] = sign(payload,
            owner=claims["namespace"] if claims else None,
            session=read_session_alias(url,public),
            scope="public-read" if public else "local-read",public_only=public)
    response = requests.post(CRAWL4AI_URL + "/crawl", json=payload,
                             headers=headers, timeout=max(CRAWL4AI_TIMEOUT,
            CRAWL4AI_RENDER_MS/1000 + _READ_OPTIONS.get().get("render_delay",.5) + 25)
            if os.getenv("DETHROTTLED_DNB", "0")=="1" else CRAWL4AI_TIMEOUT)
    if response.status_code != 200:
        return {}, "crawl4ai_http_%d" % response.status_code, url
    body = response.json()
    if not isinstance(body, dict):
        return {}, "crawl4ai_shape", url
    # `success: false` is a rendered failure, not a transport failure, and it
    # carries the reason. Reporting it beats reporting "empty".
    results = body.get("results")
    payload = (results[0] if isinstance(results, list) and results else body)
    if not isinstance(payload, dict):
        return {}, "crawl4ai_shape", url
    policy_error = _crawl4ai_target_error(payload)
    if policy_error.startswith("adblock_blocked:"):
        return {}, policy_error, payload.get("redirected_url") or url
    if payload.get("success") is False:
        reason = str(payload.get("error_message") or "render_failed")
        blocked = re.search(r'adblock_blocked:([a-zA-Z0-9.-]+)', reason)
        if blocked and adblock.FILTER.match('https://' + blocked[1]):
            return {}, 'adblock_blocked:' + blocked[1], url
        reason = reason[:240]
        if "Structural:" in reason:
            reason = "incomplete_render: " + reason
        # The DNB reports the target's HTTP failure as "http_NNN"; name it as
        # the target's, like _crawl4ai_target_error does, so it is never
        # mistaken for the rendering service refusing.
        if re.fullmatch(r"http_\d{3}", reason):
            return {}, "crawl4ai_target_" + reason, url
        return {}, "crawl4ai_" + reason, url
    target_error = _crawl4ai_target_error(payload)
    if target_error:
        return {}, target_error, payload.get("redirected_url") or url
    return _crawl4ai_payload(payload, url)


def _crawl4ai_via_render(url: str) -> tuple:
    """A service exposing POST /render {url, timeout_ms}."""
    response = requests.post(
        CRAWL4AI_URL + "/render",
        json={"url": url, "timeout_ms": CRAWL4AI_RENDER_MS},
        headers=_crawl4ai_headers(),
        timeout=CRAWL4AI_TIMEOUT)
    if response.status_code != 200:
        return {}, "crawl4ai_http_%d" % response.status_code, url
    try:
        payload = response.json()
    except ValueError:
        return {"html": response.text}, "", url
    if not isinstance(payload, dict):
        return {}, "crawl4ai_shape", url
    target_error = _crawl4ai_target_error(payload)
    if target_error:
        return {}, target_error, payload.get("redirected_url") or url
    return _crawl4ai_payload(payload, url)


# ── tier cooldown ────────────────────────────────────────────────────────────
#
# Tiers get rate limited, and a rate limit is a temporary condition wearing the
# costume of a permanent one. Asking a tier that just said 429 to try the very
# next page wastes a timeout and deepens the limit; dropping it permanently
# throws away a tier that will be fine in ten minutes.
#
# So a tier that refuses is RESTED: skipped for a cooling period, then tried
# again. One probe every cooling period costs almost nothing and the tier heals
# itself without anyone restarting anything.
#
# Backoff doubles per consecutive refusal, capped, and resets the moment the
# tier answers -- so a brief wobble costs one cooldown while a genuinely dead
# tier settles at the cap instead of being asked constantly.
TIER_COOLDOWN = float(os.environ.get("DETHROTTLED_TIER_COOLDOWN", "300"))
TIER_COOLDOWN_MAX = float(os.environ.get("DETHROTTLED_TIER_COOLDOWN_MAX", "3600"))

# What counts as "you are asking too often", as opposed to "that page is not
# here". A 404 says nothing about the tier; a 429 says everything.
_RATE_LIMIT_CODES = (401, 403, 407, 418, 429, 503)

# ONLY these can be rested, and getting this wrong is expensive.
#
# A cooldown is correct for a tier that is a single shared resource: one
# shared rendering service. Refuse once and the next request will
# be refused too, so standing back is right.
#
# It is flatly WRONG for `direct` and `tls`, which are not services at all --
# they are "make an HTTP request", per host. Measured, when they were included:
# one page 403'd, the direct tier was rested globally, and every subsequent
# page in the run skipped straight past it to the renderer. direct went from 42
# solves to 7, the renderer was asked to do 30 pages it had no business doing,
# and extraction fell from 87% to 67%.
#
# A 403 from one host says nothing whatsoever about the next host. Per-host
# per-host pacing is already handled by the per-domain request gap.
_RESTABLE_TIERS = frozenset(
    e.strip() for e in os.environ.get(
        "DETHROTTLED_RESTABLE_TIERS", "crawl4ai").split(",")
    if e.strip())

_tier_rest = {}                      # tier -> {"until": ts, "strikes": n}
_tier_rest_lock = threading.Lock()


def tier_resting(name: str) -> bool:
    """Is this tier in its cooling period?"""
    if name not in _RESTABLE_TIERS:
        return False
    with _tier_rest_lock:
        entry = _tier_rest.get(name)
        return bool(entry and time.time() < entry["until"])


def tier_refused(name: str, reason: str = "") -> None:
    """Record a refusal and start (or extend) the cooling period.

    A no-op for per-host tiers: see _RESTABLE_TIERS for why that distinction
    is the whole safety of this mechanism.
    """
    if name not in _RESTABLE_TIERS:
        return
    with _tier_rest_lock:
        entry = _tier_rest.get(name) or {"strikes": 0}
        entry["strikes"] += 1
        # The shift is capped BEFORE the power is computed, not after.
        # min(TIER_COOLDOWN * 2 ** (strikes - 1), MAX) reads as if it is
        # bounded, and is not: Python integers do not overflow, so a tier
        # refused a few thousand times built a number with hundreds of digits
        # and raised OverflowError converting it to a float -- only ever under
        # sustained failure, which is exactly when the cooldown matters.
        # Measured: 256 exceptions in a 1,280-refusal stress run.
        shift = min(max(entry["strikes"] - 1, 0), 20)
        entry["until"] = time.time() + min(TIER_COOLDOWN * (2 ** shift),
                                           TIER_COOLDOWN_MAX)
        entry["reason"] = reason[:60]
        _tier_rest[name] = entry


def tier_answered(name: str) -> None:
    """Clear the record. A tier that works is not on a warning."""
    with _tier_rest_lock:
        _tier_rest.pop(name, None)


def tier_rest_state() -> dict:
    """What is resting and for how long. Surfaced by /stats, because a silently
    skipped tier is exactly the kind of degradation that hides for days."""
    now = time.time()
    with _tier_rest_lock:
        return {name: {"resting_for": max(0, int(e["until"] - now)),
                       "strikes": e["strikes"], "reason": e.get("reason", "")}
                for name, e in _tier_rest.items() if now < e["until"]}


# The renderer is one local service: rest it only when the SERVICE is busy
# or unreachable. A target page's 403, timeout or failed navigation says
# nothing about the next site -- measured: one Stack Overflow 403 or a NOAA
# timeout rested rendering for every later page, and EUR-Lex (p05) then failed
# with "crawl4ai:resting" on both 1.8.4 and the test build.
_RENDERER_REFUSAL = re.compile(
    r"crawl4ai_http_(?:429|503)"
    r"|crawl4ai_(?:ConnectionError|ConnectTimeout|ReadTimeout|Timeout|ChunkedEncodingError)")


def _service_refusal(name: str, reason: str) -> bool:
    """Should this failure rest the tier (see _RESTABLE_TIERS)?"""
    if name == "crawl4ai":
        return bool(reason and _RENDERER_REFUSAL.fullmatch(reason))
    return _is_refusal(reason)


def _is_refusal(reason: str) -> bool:
    """Does this failure mean 'stop asking' rather than 'that page is missing'?"""
    if not reason:
        return False
    if "http_" in reason:
        for code in _RATE_LIMIT_CODES:
            if reason.endswith("_%d" % code):
                return True
        return False
    # Transport-level give-ups: the host hung up, or never answered.
    return any(word in reason for word in
               ("Timeout", "ConnectionError", "TooManyRedirects", "SSLError"))


def _tier_tls(url: str) -> tuple:
    if not ENABLE_TLS:
        return {}, "tls_disabled", url
    from .identity import POOL
    options = _READ_OPTIONS.get()
    try:
        with POOL.borrow(options.get("admission_key", "local"), url, "tls", TLS_IMPERSONATE,
                         options.get("public_only", False)) as get:
            return _tier_tls_once(url, get=get)
    except ImportError:
        return {}, "tls_not_installed", url


def _tier_tls_once(url: str, *, get=None) -> tuple:
    """Refetch with a browser's TLS fingerprint. Cheap, fast, no browser.

    Optional: without curl_cffi installed this reports itself unavailable and
    the ladder is one rung shorter, which is the same contract every other
    optional tier honours.
    """
    if not ENABLE_TLS:
        return {}, "tls_disabled", url
    try:
        from curl_cffi import requests as tls_requests
    except ImportError:
        return {}, "tls_not_installed", url
    from ._quiet import quiet_fd2
    try:
        # See _quiet.quiet_fd2: the HTTP/2 layer prints an unclean-shutdown
        # complaint from Rust on some hosts, after the response has already
        # arrived intact. Nothing actionable, and noisy on every such fetch.
        with quiet_fd2():
            response = _get_with_policy(get or tls_requests.get,
                url, impersonate=TLS_IMPERSONATE,
                timeout=(min(CONNECT_TIMEOUT, TLS_TIMEOUT),
                         max(0, TLS_TIMEOUT - min(CONNECT_TIMEOUT, TLS_TIMEOUT))),
                allow_redirects=True, stream=True)
    except Exception as exc:
        reason = (str(exc) if isinstance(exc, (adblock.AdblockBlocked, TargetPolicyError))
                  else "tls_" + type(exc).__name__)
        return {}, reason, url
    try:
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > max(DOC_MAX_BYTES, PDF_MAX_BYTES):
                return {}, "tls_document_too_large", str(response.url)
            chunks.append(chunk)
        blob = b"".join(chunks)
        text = decode_html(blob[:MAX_BYTES], response.headers.get("Content-Type", ""))
        if response.status_code >= 400:
            return {}, _http_reason("tls_", response.status_code, response.headers,
                                    text[:8192]), str(response.url)
        if "anomaly.js" in text[:20000].lower():
            return {}, "tls_challenge", str(response.url)
        parsed = _binary_payload(blob, str(response.url),
                                 response.headers.get("Content-Type", ""),
                                 _READ_OPTIONS.get().get("allow_ocr", True),
                                 _filename_hint(response.headers, str(response.url)))
        if parsed is not None:
            if isinstance(parsed[0], dict) and parsed[0]:
                parsed[0]["origin_response"] = _origin_response(response)
            return parsed
        return {"html": text, "origin_response": _origin_response(response)}, "", str(response.url)
    except Exception as exc:
        return {}, "tls_" + type(exc).__name__, str(response.url)
    finally:
        response.close()


def _tier_crawl4ai(url: str) -> tuple:
    """Headless Chromium you host. Renders JavaScript with bounded, fair admission.

    Optional. With DETHROTTLED_CRAWL4AI_URL unset this never runs and the ladder
    is one tier shorter, which is a smaller stack rather than a broken one.

    Executes JavaScript when a plain HTTP read produces only a page shell.
    The configured worker performs rendering rather than a hosted reader.
    """
    if not CRAWL4AI_URL:
        return {}, "crawl4ai_not_configured", url
    if CRAWL4AI_BUDGET >= 0 and not _spend("crawl4ai", CRAWL4AI_BUDGET):
        return {}, "crawl4ai_budget_spent", url

    try:
        with _RENDER_QUEUE.slot(_READ_OPTIONS.get().get("admission_key", "local"),
                               timeout=float(os.getenv("DETHROTTLED_RENDER_QUEUE_SECONDS", "60"))):
            return _crawl4ai_admitted(url)
    except AdmissionError as exc:
        return {}, str(exc), url


def _crawl4ai_admitted(url):
    global _crawl4ai_dialect
    order = ([_crawl4ai_dialect] if _crawl4ai_dialect
             else ["crawl", "render"])
    last = "crawl4ai_empty"
    for dialect in order:
        run = _crawl4ai_via_crawl if dialect == "crawl" else _crawl4ai_via_render
        try:
            payload, reason, final = run(url)
        except Exception as exc:
            last = "crawl4ai_" + type(exc).__name__
            continue
        # A 404 means this endpoint is not the one this server speaks. Any
        # other answer -- including an honest render failure -- means we found
        # the right dialect and should stop probing for it.
        if reason == "crawl4ai_http_404":
            last = reason
            continue
        _crawl4ai_dialect = dialect
        return payload, reason, final
    return {}, last, url


# What gets EXTRACTED and CACHED, independent of what the caller asked for.
#
# The cache used to be keyed on (url, max_chars), which meant raising the
# /extract cap from 3500 to 8000 orphaned all 904 cached extractions at a
# stroke -- every page became a cold fetch, on a tier ladder where the hard
# targets are exactly the ones that fail. That is a bad property: it makes
# tuning a cap quietly expensive, so caps do not get tuned.
#
# Retain a generous extraction independently of the requested response size.
# Focused reads and document continuations can reach later sections without
# requiring the agent to ingest the entire source. Provenance marks bounded reads.
CACHE_CHARS = int(os.environ.get("DETHROTTLED_EXTRACT_CACHE_CHARS", "4000000"))


def _clip(out: dict, max_chars: int) -> dict:
    """A copy of a cached extraction, cut to what this caller asked for."""
    text = out.get("text") or ""
    if len(text) <= max_chars:
        return out
    clipped = dict(out)
    clipped["text"], _ = smart_truncate(text, max_chars)
    clipped["_index_text"] = text
    clipped["chars"] = len(clipped["text"])
    clipped["content_chars"] = len(text)
    clipped["truncated"] = True
    return clipped


def _fetch_and_extract(url: str, *, max_chars: int = 3500, timeout: int = DEFAULT_TIMEOUT,
                      cache=None,
                      allow_render: bool = True,
                      render_first: bool = False,
                      allow_ocr: bool = True,
                      page_budget: float | None = None,
                      keep_html: bool = False) -> dict:
    """Run the ladder with EXTRACTION as the success test, not fetch.

    This is the important correction. Escalating only when a fetch fails leaves
    the common case unsolved: TrendForce returns 200 with 52KB through the CF
    Worker and DIGITIMES returns 200 directly, yet neither yields a word of
    article text, because the body arrives via JavaScript. A ladder that stops
    at "HTTP 200" declares victory on an empty shell.

    So each tier is judged on whether it produced readable prose. A cheap tier
    that returns a JS skeleton is a miss, and the page escalates to the
    renderer that can actually resolve it.

    Returns {ok, text, tier, extractor, title, published, chars, url, reason}.
    """
    from . import adblock
    from . import extract as _fx
    try:
        adblock.check(url)
    except adblock.AdblockBlocked as exc:
        return {"ok": False, "text": "", "url": url, "tier": None, "extractor": None,
                "title": "", "published": "", "chars": 0, "cached": False,
                "reason": str(exc), "policy_blocked": "adblock"}

    # keep_html deliberately bypasses the cache. The cache stores the
    # extracted text and NOT the source -- storing megabytes of HTML per page
    # would trade many-pages-cheaply for few-pages-expensively -- so a caller
    # who asked for the source cannot be served from it, and quietly returning
    # a row with no html would be the wrong kind of surprise.
    if cache is not None and not keep_html:
        # Keyed on the url alone. The stored copy is the generous one; what
        # this caller wanted is a clip of it. Validate the stored shape before
        # counting it as a hit: a valid-JSON wrong-shape row is a miss.
        from .cache import valid_extract

        hit = cache.get("extract", url, validator=valid_extract)
        acquisition = (hit or {}).get("acquisition", {})
        compatible = not render_first or acquisition.get("rendered", False)
        if hit is not None and (challenge_kind(hit.get("text", "")) or
                                not hit.get("text", "").strip()):
            compatible = False
        requested_wait = _READ_OPTIONS.get().get("wait_for", "")
        if requested_wait:
            compatible = compatible and acquisition.get("wait_for") == requested_wait
        compatible = compatible and acquisition.get("page_start", 1) == (
            _READ_OPTIONS.get().get("page_start", 1)) and acquisition.get("page_end") == (
            _READ_OPTIONS.get().get("page_end"))
        compatible = compatible and acquisition.get("ocr_mode", "auto") == (
            _READ_OPTIONS.get().get("ocr_mode", "auto"))
        for option, default in (("document_mode", "auto"), ("row_start", 1),
                                ("row_end", None), ("sheet", ""),
                                ("max_cell_chars", None)):
            compatible = compatible and acquisition.get(option, default) == (
                _READ_OPTIONS.get().get(option, default))
        compatible = compatible and acquisition.get("ocr_language", "") == (
            _READ_OPTIONS.get().get("ocr_language", ""))
        if _READ_OPTIONS.get().get("allow_ocr", True):
            compatible = compatible and acquisition.get("ocr_allowed", True)
        if render_first or requested_wait:
            compatible = compatible and (acquisition.get("render_delay") or 0) >= (
                _READ_OPTIONS.get().get("render_delay", 0.5))
        compatible = compatible and acquisition.get("layout_worker_configured", False) == bool(
            workers.endpoint("layout"))
        # Old archive XML / flat scan OCR must not hide newly enabled readers.
        if urlparse(url).path.lower().endswith((".msg", ".xlsb")):
            compatible = compatible and acquisition.get("format_worker_configured", False) == bool(
                workers.endpoint("formats"))
        scanned = any("ocr" in page.get("method", "")
                      for page in (hit or {}).get("extraction", {}).get("pages", []))
        if scanned and workers.endpoint("layout"):
            compatible = compatible and acquisition.get("scan_layout_revision") == 1
        if hit is not None and compatible:
            if hit.get("reason", "").startswith("thin, best available"):
                hit["quality"] = "thin"
            hit["acquisition_attempts"] = [{"tier": "cache", "outcome": "hit", "reason": ""}]
            hit["cached"] = True
            _tier_stats["cache"] += 1
            from .content import annotate_content
            if not hit.get("content_assessment"):
                annotate_content(hit, structured=bool(hit.get("content_type") not in {
                    "", "html", "text/html"}))
            return _clip(hit, max_chars)

    if not valid_url(url):
        _tier_stats["failed"] += 1
        return {"ok": False, "text": "", "tier": None, "extractor": None,
                "title": "", "published": "", "chars": 0, "url": url,
                "reason": "invalid_url", "cached": False}

    tiers = [("direct", lambda: _tier_direct(url, timeout, allow_ocr))]
    # Second, because it is the cheapest thing that can succeed where `direct`
    # failed -- faster than direct in measurement, and it needs no service.
    if ENABLE_TLS:
        tiers.append(("tls", lambda: _tier_tls(url)))
    if allow_render and CRAWL4AI_URL and CRAWL4AI_BUDGET != 0:
        tiers.append(("crawl4ai", lambda: _tier_crawl4ai(url)))
    if allow_render and os.getenv("DETHROTTLED_BROWSER_SEARCH_URL"):
        tiers.append(("headed", lambda: _tier_headed(url)))
    elif allow_render and _READ_OPTIONS.get().get("headed_fallback"):
        tiers.append(("headed", lambda: _tier_headed(url)))

    # render_first moves the renderer to the FRONT of the ladder.
    #
    # The ladder normally escalates only when a cheaper tier fails to yield
    # prose, which is right for almost everything. It is wrong in one case: a
    # page whose static HTML carries SOME readable text -- navigation, a
    # summary, a cookie notice -- while the content the caller wants arrives
    # with JavaScript.  clears THIN_CHARS on the chrome, the ladder is
    # satisfied, and the renderer is never asked. A caller who knows a page
    # needs a browser had no way to say so.
    #
    # The cheap tiers are kept behind it rather than discarded, so a renderer
    # that is resting, over budget or simply beaten by the page still falls
    # through instead of failing outright.
    if render_first:
        tiers.sort(key=lambda pair: pair[0] != "crawl4ai")

    reasons, best = [], None
    budget = PAGE_BUDGET if page_budget is None else page_budget
    budget_started = time.time()

    attempts = []

    def finish(out):
        # Recheck old cached interstitials on the read path as well.
        out["acquisition_attempts"] = [dict(a) for a in attempts]
        out["schema_version"] = 3
        rendered = out.get("tier") in {"crawl4ai", "headed"}
        out["acquisition"] = {"rendered": rendered,
                              "wait_for": (_READ_OPTIONS.get().get("wait_for", "")
                                           if rendered else ""),
                              "render_delay": _READ_OPTIONS.get().get("render_delay") if rendered
                              else None,
                              "extraction_limit": CACHE_CHARS,
                              "page_start": _READ_OPTIONS.get().get("page_start", 1),
                              "page_end": _READ_OPTIONS.get().get("page_end"),
                              "ocr_language": _READ_OPTIONS.get().get("ocr_language", ""),
                              "ocr_mode": _READ_OPTIONS.get().get("ocr_mode", "auto"),
                              "ocr_allowed": _READ_OPTIONS.get().get("allow_ocr", True),
                              "row_start": _READ_OPTIONS.get().get("row_start", 1),
                              "row_end": _READ_OPTIONS.get().get("row_end"),
                              "sheet": _READ_OPTIONS.get().get("sheet", ""),
                              "max_cell_chars": _READ_OPTIONS.get().get("max_cell_chars"),
                              "document_mode": _READ_OPTIONS.get().get("document_mode", "auto"),
                              "scan_layout_revision": 1,
                              "format_worker_configured": bool(
                                  workers.endpoint("formats")),
                              "layout_worker_configured": bool(
                                  workers.endpoint("layout"))}
        out.setdefault("retrieved_at", datetime.now(timezone.utc).isoformat())
        out.setdefault("cache_age_seconds", 0)
        out.setdefault("content_chars", len(out.get("text", "")))
        out.setdefault("truncated", bool(out.get("extraction", {}).get("partial")))
        # Store the full extraction, hand back only what was asked for.
        #
        # The source, when a caller asked for it, is deliberately NOT cached.
        # It is often twenty times the size of the text extracted from it, and
        # caching it would trade the whole point of a page cache -- many pages
        # cheaply -- for a few pages expensively.
        source = out.pop("html", None)
        if cache is not None and out.get("text"):
            cache.put("extract", url, value=out)
        out = _clip(out, max_chars)
        if source is not None:
            out["html"] = source
        return out

    # ── video, decided from the URL before anything is fetched ──────────
    #
    # A video page is the one case the ladder cannot win. Fetching it returns a
    # player, rendering it returns a player, and no extractor recovers prose
    # from either -- the words live in a caption track served separately.
    #
    # So it is routed here, on the URL alone, at the cost of one regex against
    # a host allowlist. Anything that is not a video URL falls straight through
    # to the ladder having spent no network at all.
    from . import media as _media
    if _media.is_video(url):
        caption_metadata = {}
        text, _title, why = _media.transcript(url, limit=CACHE_CHARS, metadata=caption_metadata)
        if text:
            out = {"ok": True, "text": text, "tier": "transcript",
                   "extractor": "captions", "title": "", "published": "",
                   "chars": len(text), "url": url, "reason": "",
                   "cached": False, "content_type": "transcript",
                   "extraction": caption_metadata}
            return finish(out)
        # No captions, or blocked. Reported under its own name rather than
        # falling through to a ladder that would spend four tiers proving it
        # cannot read a video player.
        _tier_stats["failed"] += 1
        return {"ok": False, "text": "", "tier": None, "extractor": None,
                "title": "", "published": "", "chars": 0, "url": url,
                "reason": why or "no_transcript", "cached": False}

    # Kept bound past the loop so a total failure can report which tier
    # it was last standing on, rather than reporting nothing at all.
    name = None
    challenged = False
    polluted = False
    alternatives = []
    script_shell = False
    last_attempted = None
    for name, run in tiers:
        if name == "headed" and not (
                challenged or script_shell or polluted
                or _READ_OPTIONS.get().get("headed_fallback")):
            continue
        # A resting tier is skipped without being asked. This is the smooth
        # transition: the ladder simply gets shorter for a while and the rungs
        # that still work carry the load.
        if tier_resting(name):
            reasons.append("%s:resting" % name)
            continue
        # A static shell, or a page served without prose, is HTML the server
        # gave freely, not a block: TLS impersonation got the same result in
        # every recorded case (shell 21/21, no prose 56/56), so go straight to
        # rendering. Challenges and failed fetches still try TLS, which does
        # rescue those (12 and 28 recorded reads).
        if (name == "tls" and attempts and attempts[-1]["tier"] == "direct"
                and attempts[-1]["outcome"] in {"shell", "response"}
                and any(other == "crawl4ai" and not tier_resting(other)
                        for other, _ in tiers)):
            reasons.append("tls:skipped_after_static_shell")
            continue
        # Checked before each tier rather than enforced during one: a tier
        # already running is allowed to finish, because killing a fetch that is
        # about to succeed wastes everything spent on it. This stops the NEXT
        # attempt, which is where a runaway page actually costs its minute.
        if (time.time() - budget_started > budget
                and not (name == "headed" and (challenged or script_shell))):
            if best is None:
                reasons.append("%s: skipped, page budget of %.0fs spent" % (name, budget))
            continue
        last_attempted = name
        attempt_started = time.monotonic()
        payload, reason, final = run()
        attempt = {"tier": name, "reason": reason, "outcome": "response" if payload else "failed",
                   "elapsed_ms": round((time.monotonic() - attempt_started) * 1000, 2)}
        status = re.fullmatch(r"(?:tls_)?http_(\d{3})", reason)
        if status:
            attempt.update(http_status=int(status[1]), final_url=final,
                           observed_at=datetime.now(timezone.utc).isoformat())
        attempts.append(attempt)
        if (reason.startswith('adblock_blocked:')
                or reason in {"public_target_required", "redirect_target_not_public"}):
            attempt['outcome'] = 'policy_blocked'
            return {"ok": False, "text": "", "url": final, "tier": name, "extractor": None,
                    "title": "", "published": "", "chars": 0, "cached": False,
                    "reason": reason,
                    "policy_blocked": ("adblock" if reason.startswith('adblock_blocked:')
                                       else "network"),
                    "acquisition_attempts": attempts}
        payload = payload if isinstance(payload, dict) else {}
        html = payload.get("html") or ""
        details = page_details(html, final) if html else {}
        for alternate in details.get("source_alternatives", []):
            if alternate not in alternatives and len(alternatives) < 8:
                alternatives.append(alternate)
        if (html and re.search(r"<(?:script|iframe)\b", html, re.I)
                and len(short_text(html).strip()) < 40):
            script_shell = True
        detected = challenge_kind(payload.get("html") or (
            "" if payload.get("structured") else payload.get("text") or ""))
        reported_block = "anti-bot" in reason.lower() and "http 429" not in reason.lower()
        if detected or "challenge" in reason or reported_block:
            challenged = True
            attempt.update(outcome="challenge", provider=detected or "unspecified")
            if detected:
                attempt["reason"] = reason or "challenge_detected:" + detected
                reasons.append(name + ":" + attempt["reason"])
                continue
        if _service_refusal(name, reason):
            tier_refused(name, reason)
        elif payload:
            # Answered with something. Whether it extracted is a separate
            # question -- an empty shell is the page's fault, not the tier's,
            # and resting a tier for it would be wrong.
            tier_answered(name)
        candidate = None

        # A tier may hand back already-extracted text. Re-running a local
        # extractor over someone else's good extraction only loses content.
        supplied = payload.get("text")
        # The 220 floor exists to reject junk from HTML extractors. A document
        # that PARSED is a different case: a five-row statistics table or a
        # one-page tender notice is short and completely real, and rejecting it
        # sent both to the html branch to be reported as "empty".
        structured_floor = 1 if payload.get("structured") else 220
        if isinstance(supplied, str) and len(_tidy_text(supplied)) >= structured_floor:
            # A table's row boundaries carry meaning: run two rows together
            # and it no longer says which number belongs to which year. So
            # spreadsheets, OCR pages and slides keep their line breaks.
            if payload.get("structured"):
                from . import documents as _docs
                whole = _docs.tidy_structured(supplied)
                text = _docs.tidy_structured(supplied, limit=CACHE_CHARS)
            else:
                whole = _tidy_text(supplied)
                text = _tidy_text(supplied, limit=CACHE_CHARS)
            supplied_clipped = len(whole) > len(text)
            source = {"html": payload.get("html") or ""} if keep_html else {}
            candidate = {**source,
                         "ok": True, "text": text, "tier": name,
                         "extractor": "%s-native" % name, "title": "",
                         "published": (payload.get("page_metadata") or {}).get("published", ""),
                         "chars": len(text), "url": final,
                         "reason": "", "cached": False,
                         "content_type": payload.get("content_type", ""),
                         "extraction": payload.get("extraction", {}),
                         "warnings": payload.get("warnings", []),
                         "page_metadata": payload.get("page_metadata", {}),
                         "content_status": payload.get("content_status", "complete")}
            candidate.update({k: details[k] for k in ("source_alternatives", "source_canonical")
                              if k in details})
            if supplied_clipped:
                # Same rule as the HTML path: a cut at the retained extraction
                # budget is reported, never presented as a complete read.
                candidate["extraction"] = {**candidate["extraction"], "partial": True,
                                           "partial_reason": "extraction_cache_limit"}
                candidate["warnings"] = [*candidate["warnings"], "extraction_cache_limit"]
        else:
            html = payload.get("html") or ""
            if not html or _challenge_document(html):
                reasons.append("%s:%s" % (name, reason or "empty"))
                continue
            result = _fx.extract(html, url=final, max_chars=CACHE_CHARS)
            if not result["ok"]:
                small = short_text(html).strip()
                if (len(small) >= 40 or keep_html
                        or _READ_OPTIONS.get().get("format") in {"html", "links"}):
                    result = {"ok": True, "text": small, "tier": "short",
                              "title": "", "published": "", "chars": len(small)}
            if result["ok"] and (result.get("text", "").strip() or keep_html
                                 or _READ_OPTIONS.get().get("format") in {"html", "links"}):
                # The source, only when asked for. finish() strips it before
                # the cache write, so this never bloats the page cache.
                source = {"html": html} if keep_html else {}
                candidate = {**source,
                             "ok": True, "text": result["text"], "tier": name,
                             "extractor": result["tier"],
                             "extraction": {"completeness": result.get("completeness", {})},
                             "page_metadata": result.get("page_metadata", {}),
                             "title": result.get("title", ""),
                             "published": result.get("published", ""),
                             "chars": result["chars"], "url": final,
                             "reason": ("html_truncated"
                                        if payload.get("clipped") else ""),
                             "cached": False, "content_type": "html",
                             **details}
                candidate["warnings"] = [*candidate.get("warnings", []),
                                         *result.get("warnings", [])]
                if result.get("clipped"):
                    candidate["extraction"] = {**candidate["extraction"], "partial": True,
                                               "partial_reason": "extraction_cache_limit"}
            else:
                # Fetched fine, but no prose -- almost always a JS shell.
                reasons.append("%s:fetched_but_%s" % (name, result["reason"]))
                continue

        _supplement_thin(candidate, payload.get("html") or "",
                         payload.get("page_descriptions"))
        if payload.get("browser_recovery"):
            candidate["browser_recovery"] = payload["browser_recovery"]
        if payload.get("origin_response"):
            candidate["origin_response"] = payload["origin_response"]
        pending = (payload.get("browser_recovery") or {}).get("document_ready_state") == "loading"
        visible_capture = candidate.get("extraction", {}).get("method") == "browser_visible_text"
        if candidate.get("content_type") == "html" and (
                pending or (payload.get("clipped") and not visible_capture)):
            partial_reason = "browser_document_loading" if pending else "html_capture_limit"
            candidate["extraction"] = {**candidate.get("extraction", {}),
                                       "partial": True, "partial_reason": partial_reason}
            candidate["warnings"] = [*candidate.get("warnings", []), partial_reason]
        from .content import annotate_content
        annotate_content(candidate, payload.get("html") or "",
                         structured=bool(payload.get("structured")))
        suspect = candidate["content_assessment"]["pollution"] == "suspected"
        attempt["content_assessment"] = {
            k: v for k, v in candidate["content_assessment"].items() if k != "spans"}
        if suspect:
            polluted = True
            attempt["outcome"] = "suspected_pollution"
            reasons.append(name + ":suspected_error_banner")
            if best is None or (candidate["content_assessment"]["unflagged_chars"]
                                > best["content_assessment"]["unflagged_chars"]):
                best = candidate
            continue
        # Structured payloads are never "thin". THIN_CHARS asks whether a page
        # gave up only a teaser, which is a question about HTML -- no later
        # tier is going to read a spreadsheet or a scan better than the parser
        # that already read it, so trying them only burns the page budget.
        if (_looks_like_shell(name, candidate,
                              payload.get("html") or payload.get("source_html_bytes") or "")
                and not payload.get("structured")
                and _READ_OPTIONS.get().get("format") not in {"html", "links"}):
            attempt["outcome"] = "shell"
            reasons.append("%s:shell/%d" % (name, candidate["chars"]))
            if (best is None or candidate["content_assessment"]["unflagged_chars"]
                    > best["content_assessment"]["unflagged_chars"]):
                best = candidate
            continue
        if (candidate["chars"] >= THIN_CHARS or payload.get("structured")
                or _READ_OPTIONS.get().get("format") in {"html", "links"}
                or candidate.get("content_status") == "image_content"):
            attempt["outcome"] = "extracted"
            _tier_stats[name] += 1
            return finish(candidate)

        # Thin: keep it as a floor and let a later tier try to beat it, rather
        # than either discarding a real result or stopping on a teaser.
        attempt["outcome"] = "thin"
        reasons.append("%s:thin/%d" % (name, candidate["chars"]))
        if (best is None or candidate["content_assessment"]["unflagged_chars"]
                > best["content_assessment"]["unflagged_chars"]):
            best = candidate

    if best is not None:
        if best.get("content_assessment", {}).get("pollution") == "suspected":
            _tier_stats[best["tier"] + "-suspect"] += 1
            best["quality"] = "suspect"
            best["reason"] = "suspected pollution, best available: " + ", ".join(reasons)
            return finish(best)
        _tier_stats[best["tier"] + "-thin"] += 1
        best["quality"] = "thin"
        best["warnings"] = [*best.get("warnings", []), "thin_content; coverage_not_verified"]
        best["reason"] = "thin, best available: " + ", ".join(reasons)
        return finish(best)

    _tier_stats["failed"] += 1
    # `best` is None on this path by construction (the `if best is not None`
    # branch above already returned). `name` is the last tier the loop tried
    # before giving up -- the same "how far did it get" fact `tier` reports on
    # success, so a caller checking only `tier` is not left with nothing.
    return {"ok": False, "text": "", "tier": last_attempted, "extractor": None,
            "title": "", "published": "", "chars": 0, "url": url,
            "reason": " | ".join(reasons), "cached": False,
            "acquisition_attempts": attempts, "source_alternatives": alternatives}


def _challenge_document(html: str) -> bool:
    return bool(challenge_kind(html))


class _HeadedReadFailure(ValueError):
    pass


def _tier_headed(url: str) -> tuple:
    backend = os.environ.get("DETHROTTLED_BROWSER_SEARCH_URL", "").rstrip("/")
    if not backend:
        return {}, "headed_unavailable", url
    try:
        queue_timeout = float(os.getenv("DETHROTTLED_HEADED_QUEUE_SECONDS", "60"))
        with _HEADED_QUEUE.slot(_READ_OPTIONS.get().get("admission_key", "local"),
                                timeout=queue_timeout) as ms:
            payload, reason, final = _headed_read(url, backend)
            if "browser_recovery" in payload:
                payload["browser_recovery"]["queue_ms"] = ms
            return payload, reason, final
    except AdmissionError as exc:
        return {}, str(exc).replace("renderer_", "headed_"), url


def _headed_read(url: str, backend: str) -> tuple:
    # Exact-host, caller-scoped browser identity. Never export cookies to another
    # transport or share clearance state across public clients.
    options = _READ_OPTIONS.get()
    host = urlparse(url).hostname
    from .access import automatic_session, read_session_alias
    from .research import browser_public
    public = browser_public(url, options.get("public_only", False))
    alias = read_session_alias(url, public)
    session = automatic_session(str(options.get("admission_key", "local")), alias)
    started = time.monotonic()
    deadline = started + float(os.getenv("DETHROTTLED_CHALLENGE_WAIT_SECONDS", "15"))
    body = {"session": session, "screenshot": "never", "allowed_hosts": [host],
            "public_only": public, "timeout_ms": 12000,
            "navigation_wait": "commit"}
    read = {"action": "html", "selector": "html", "max_chars": 120000}

    def drive(steps, navigate=False):
        payload = {**body, **({"url": url} if navigate else {}), "steps": steps}
        headers = {}
        if os.getenv("DETHROTTLED_DNB", "0") == "1":
            from . import delegation
            headers["x-dnb-delegation"] = delegation.sign(
                payload,
                owner=session,
                session=session,
                scope="public-read",
                public_only=bool(payload.get("public_only")),
                allowed_hosts=payload.get("allowed_hosts") or (),
                path="/drive",
            )
        response = requests.post(backend + "/drive", json=payload,
                                 headers=headers, timeout=15)
        response.raise_for_status()
        value = response.json()
        if not value.get("ok"):
            failed = next((step for step in value.get("steps", []) if not step.get("ok")), {})
            if "adblock_blocked:" in str(failed.get("reason", "")):
                raise adblock.AdblockBlocked("browser_navigation")
            raise _HeadedReadFailure("headed_step_failed:" + str(failed.get("action", "unknown"))
                                     + ":" + str(failed.get("reason") or "drive_failed")[:200])
        return value

    try:
        wait_for = options.get("wait_for")
        steps = ([{"action": "wait_for", "selector": wait_for, "ms": 5000}]
                 if wait_for else [{"action": "wait", "ms": 700}]) + [read]
        data = drive(steps, navigate=True)
        navigation = next((step.get("data") or {} for step in data.get("steps", [])
                           if step.get("action") == "goto"), {})
        restored = bool(data.get("session", {}).get("restored_from_checkpoint"))
        polls = 0
        loading_polls = 0
        while True:
            html = data["steps"][-1].get("data") or ""
            if isinstance(html, dict):
                html = html.get("html", "")
            headers = navigation.get("challenge_headers") if polls == 0 else None
            vendor = challenge_kind(html, headers)
            if vendor == 'login_required':
                return {}, 'headed_login_required', data.get('final', {}).get('url', url)
            loading = (data["steps"][-1].get("document_ready_state") == "loading"
                       and len(short_text(html).strip()) < 40)
            if not vendor and not loading:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {}, ("headed_challenge_unresolved:" + vendor if vendor
                            else "headed_document_still_loading"), url
            data = drive([{"action": "wait", "ms": min(1000, max(1, int(remaining * 1000)))},
                          read])
            polls += 1
            loading_polls += int(loading and not vendor)
        if (not wait_for and deadline - time.monotonic() > 4
                and os.getenv("DETHROTTLED_HEADED_SETTLE", "1") != "0"):
            # Second look after settling: bounded network-quiet wait plus
            # scroll-until-stable, as the crawl path does, so application pages
            # are not captured at first paint. It only ever adds: a page that
            # navigates away, times out or reads no better keeps the first
            # capture (Indeed redirected during settling and failed the read).
            try:
                settled = drive([{"action": "settle", "ms": 3000, "limit": 10}, read])
                later = settled["steps"][-1].get("data") or ""
                if isinstance(later, dict):
                    later = later.get("html", "")
                if (not challenge_kind(later)
                        and len(short_text(later)) > len(short_text(html))):
                    data, html = settled, later
            except (_HeadedReadFailure, requests.RequestException, ValueError, KeyError):
                pass
        visible = {}
        visible_error = None
        if data['steps'][-1].get('truncated'):
            # Large application DOMs can spend the entire HTML cap on scripts
            # and navigation. Retain actual rendered evidence rather than
            # treating that prefix as a complete read.
            try:
                rendered = drive([{'action': 'text', 'selector': 'body',
                                   'max_chars': min(CACHE_CHARS, 1000000)}])
            except (requests.RequestException, ValueError, _HeadedReadFailure) as exc:
                rendered = {'steps': [{}]}
                visible_error = type(exc).__name__
            snapshot = rendered['steps'][-1]
            text = snapshot.get('data', '')
            if isinstance(text, str) and len(text.strip()) >= 220 and not challenge_kind(text):
                visible = {'text': text, 'content_type': 'html',
                           'extraction': {'method': 'browser_visible_text',
                               'partial': bool(snapshot.get('truncated')),
                               'html_capture_partial': True},
                           'warnings': ['Rendered visible-text fallback; may include '
                                        'navigation, ads and related content. '
                                        'Source completeness remains unverified.']}
        # Checkpoints retain same-browser state across worker restarts. A failed
        # checkpoint must not discard acquired evidence or export credentials.
        checkpointed = True
        try:
            drive([{"action": "checkpoint"}])
        except (requests.RequestException, ValueError):
            checkpointed = False
        return {**visible, "html": html,
                "clipped": bool(data["steps"][-1].get("truncated")),
                "browser_recovery": {
            "visible_text_error": visible_error,
            "restored_from_checkpoint": restored,
            "challenge_polls": polls - loading_polls, "loading_polls": loading_polls,
            "document_ready_state": data["steps"][-1].get("document_ready_state"),
            "initial_navigation": navigation, "checkpointed": checkpointed,
            "elapsed_ms": int((time.monotonic() - started) * 1000)}}, "", (
                data.get("final", {}).get("url") or url)
    except (adblock.AdblockBlocked, _HeadedReadFailure) as exc:
        return {}, str(exc), url
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        return {}, "headed_" + type(exc).__name__, url


def fetch_and_extract(url: str, *, max_chars: int = 3500, timeout: int = DEFAULT_TIMEOUT,
                      cache=None, allow_render: bool = True, render_first: bool = False,
                      allow_ocr: bool = True, page_budget: float | None = None,
                      keep_html: bool = False, format: str = "text", wait_for: str = "",
                      render_delay: float = 0.5, headed_fallback: bool = False,
                      public_only: bool = False, ocr_language: str = "", ocr_mode: str = "auto",
                      page_start: int = 1, page_end: int | None = None,
                      row_start: int = 1, row_end: int | None = None, sheet: str = "",
                      max_cell_chars: int | None = None, document_mode: str = "auto",
                      source_sink=None, admission_key="local") -> dict:
    """Read a URL with request-local rendering/target policy and bounded output."""
    options = dict(format=format, wait_for=wait_for, render_delay=render_delay,
                   headed_fallback=headed_fallback, public_only=public_only,
                   keep_html=keep_html,
                   ocr_language=ocr_language, ocr_mode=ocr_mode,
                   page_start=page_start, page_end=page_end,
                   allow_ocr=allow_ocr, row_start=row_start, row_end=row_end,
                   sheet=sheet, max_cell_chars=max_cell_chars, document_mode=document_mode,
                   source_sink=source_sink, admission_key=admission_key)
    token = _READ_OPTIONS.set(options)
    try:
        if options.get("public_only"):
            from .research import public_url
            if not public_url(url):
                return {"ok": False, "text": "", "reason": "public_target_required",
                        "cached": False, "tier": None}
        result = _fetch_and_extract(url, max_chars=max_chars, timeout=timeout, cache=cache,
                                    allow_render=allow_render, render_first=render_first,
                                    allow_ocr=allow_ocr, page_budget=page_budget,
                                    keep_html=keep_html)
        if options.get("public_only") and result.get("url"):
            from .research import public_url
            if not public_url(result["url"]):
                return {"ok": False, "text": "", "reason": "redirect_target_not_public",
                        "cached": False, "tier": None}
        return result
    finally:
        _READ_OPTIONS.reset(token)
