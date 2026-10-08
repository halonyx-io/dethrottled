#!/usr/bin/env python3
"""An HTTP API over the free stack: search, fetch, extract.

Six routes, no keys, no quota, no shared pool. Point anything that speaks HTTP
at it and it works:

    POST /search              free search across every configured source
    POST /fetch               URLs -> their prose (raw=true for the source)
    POST /drive               drive the private browser: click, fill, read
    POST /search-and-fetch    both at once, fetching only the winners
    GET  /corpus/search       what has already been fetched, no network
    GET  /health              is the process alive
    GET  /v2/status           which sources and extractors actually work
    GET  /v2/capabilities     what this build can do

Two response fields are worth knowing about because most search APIs do not
give you them. `search_attempts` reports which engine returned how many rows
and which ones did not answer at all, so a caller can tell a genuinely empty
result from a silently degraded one. `tier` says HOW a page was obtained --
`direct/trafilatura`, `crawl4ai/readability` -- which is the difference between
trusting a result and knowing why you got it.

Deliberately NOT included: any editorial opinion about which sources are good.
The reputable-domain sweep and the preferred-domain ranking are available and
are driven entirely by lists the CALLER supplies. A search service that decides
for you what counts as a real publisher is a search service you cannot use for
a subject it was not built for.

Two verbs and one combination, not one endpoint per tier. There is
deliberately no `/crawl`: rendering is a STRATEGY for obtaining a page, not
something a caller wants for its own sake. The ladder escalates to the renderer
by itself when the cheap tiers fail, and a caller choosing it by hand would
spend four seconds of Chromium on pages `direct` serves in two hundred
milliseconds. Where forcing the question is genuinely useful, that is the
`render` parameter, not a route.

`/drive` is the one place that rule bends, and on purpose. `/fetch` READS a
page; `/drive` OPERATES one -- click, type, hold a session, read what rendered.
That is not a strategy the ladder could have chosen for you, because the caller
is not asking for a page, it is asking for a sequence of actions against one.
It is proxied straight to the private browser worker, which owns the single
warm, headed, stealth browser this stack already runs; the caller never
launches a browser, sets a DISPLAY, or picks a Chromium build.

`/extract` and `/search-and-extract` remain as aliases: they are what earlier
callers were written against, and renaming for tidiness is a poor trade. So is
`/extract-with-links`, which is `/fetch` with `links: true` -- the anchors kept
and rendered as markdown, for callers doing link discovery rather than reading.

Run:
    dethrottled --port 8182
    python -m dethrottled.server --port 8182
"""

from __future__ import annotations

import argparse
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Read from the package, never restated here.
#
# This was hardcoded to "0.1.0" while pyproject.toml and __init__.py both said
# 0.1.2, so /health and /v2/capabilities reported a version the software had
# not been for two releases. That is the number anyone evaluating this actually
# sees, and a reviewer duly wrote it up as "version 0.1.0 -- early".
#
# Three places claiming a version is two too many.
from . import __version__ as VERSION
from . import domains as domain_health
from . import extract as fx
from . import fetch as fetcher
from . import paths as _paths
from . import rank as ranker
from . import research as research_engine
from . import search as fs
from .cache import Cache
from .corpus import index_fetched, shared_corpus

STARTED = time.time()

_cache = None
_cache_init_lock = threading.Lock()


def cache() -> Cache:
    global _cache
    if _cache is None:
        with _cache_init_lock:
            if _cache is None:
                _cache = Cache(Path(os.environ.get(
                    "DETHROTTLED_CACHE",
                    str(_paths.data_dir() / "cache.sqlite"))))
    return _cache


app = FastAPI(title="dethrottled", version=VERSION,
              description="Zero-API search, fetch and extraction")


# Page reads spend most of their time waiting on different origin servers.
# Share eight slots across requests and let one request occupy at most four;
# response rows still come back in the caller's order.
_FETCH_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="page-fetch")


def _read_batch(items, read):
    rows = []
    for start in range(0, len(items), 4):
        futures = [_FETCH_POOL.submit(read, item) for item in items[start:start + 4]]
        rows.extend(future.result() for future in futures)
    return rows


class SearchBody(BaseModel):
    # Unknown fields are rejected rather than ignored, so a caller that mistypes
    # one hears about it instead of silently getting the default.
    model_config = ConfigDict(extra="forbid")

    query: str
    # The contract's name for result count. num_results and max_items remain
    # accepted for callers already written against them; limit wins.
    limit: int | None = None
    num_results: int = 8
    max_items: int | None = None
    # Default search includes direct web, Bing News RSS, local SearXNG and
    # resolved Google News headlines. This preserves existing callers.
    categories: str = ""
    # SearXNG uses this hint. Direct web engines are
    # English-centric and do not take it, so it biases rather than constrains.
    language: str = ""
    engines: str = ""
    # Honoured: bypasses the search cache for this call. It was accepted and
    # ignored until an external benchmark set it, measured this engine's cache
    # against another engine doing live work, and published the wrong
    # conclusion. Accepting a field costs nothing right up until someone
    # believes it.
    fresh: bool = False
    profile: str = "balanced"

    # Source order is the measured default; BM25 remains opt-in.
    rank: bool = False
    # Accept explicit false for existing callers. Reject true instead of
    # claiming success when the removed model cannot run.
    rerank: bool = False

    @field_validator("rerank")
    @classmethod
    def reranker_is_retired(cls, value: bool) -> bool:
        if value:
            raise ValueError("Dethrottled no longer provides a reranker")
        return value
    # How many already-fetched corpus passages to merge into the pool before
    # ranking. 0 disables it. These cost no fetch, so they are cheaper than the
    # web rows they compete with, not merely additional.
    corpus: int = 0
    # 0.0 = pure relevance, 1.0 = freshness dominates. Bounded and
    # multiplicative: it may reorder relevant results and may never promote an
    # irrelevant one.
    recency: float = 0.0


class FetchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    urls: list[str] = Field(default_factory=list)
    # What the ladder is ALLOWED to do, not what it must do. "never" keeps it
    # on the cheap local tiers for callers to whom latency matters more than
    # coverage.
    # auto    escalate to the renderer only when cheaper tiers fail (default)
    # always  try the renderer FIRST, for a page you know needs a browser
    # never   stay on the cheap local tiers
    # auto | always | never. A bool is also accepted and mapped, because
    # callers were written against one -- and because typing this field
    # differently on two engines is what returned 422 on every fetch through a
    # bridge for a day. The enum is canonical; True means always, False auto.
    render: str | bool = "auto"
    # text   article prose (default)
    # links  prose with anchors kept as markdown, for link discovery
    # html   the source, for callers doing their own parsing
    #
    # Replaces the raw/links booleans, which could contradict each other and
    # left a caller no way to say "either one" without knowing which won.
    format: str = "text"
    # The prose is the point; `raw` is for callers doing their own parsing, and
    # is the only reason this is a distinct verb rather than a rename. Kept
    # because callers send it; `format` wins when both appear.
    raw: bool = False
    # Keep the anchors, rendered as markdown links. For callers doing link
    # discovery rather than reading: an index page's VALUE is its outbound
    # links, and the article extractors throw those away by design.
    links: bool = False
    # 8000, not 3500: 3,500 characters is about 550 words, and a news article
    # is 500 to 800 -- this endpoint was truncating typical articles. Not
    # 10,000, because past roughly eight thousand most sites are into
    # related-articles and footer.
    max_chars: int = 8000
    fresh: bool = False
    profile: str = "balanced"


class SearchFetchBody(SearchBody):
    # auto | always | never. A bool is also accepted and mapped, because
    # callers were written against one -- and because typing this field
    # differently on two engines is what returned 422 on every fetch through a
    # bridge for a day. The enum is canonical; True means always, False auto.
    render: str | bool = "auto"
    raw: bool = False
    # 3000. Leaner than /extract on purpose: this path multiplies by the number
    # of results, and it is the ranking path, where measurement says less text
    # ranks better -- titles plus 240 characters beat 3,000 characters of body.
    # 3000 is the measured sweet spot for the ranking path.
    max_chars: int = 3000


class ResearchBody(BaseModel):
    """A question and optional facets; returns sources, not a model answer."""
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=500)
    queries: list[str] = Field(default_factory=list, max_length=3)
    max_sources: int = Field(default=6, ge=1, le=6)
    max_chars: int = Field(default=5000, ge=500, le=6000)
    language: str = ""
    fresh: bool = False
    categories: str = ""


class DriveStep(BaseModel):
    """One action for the browser to take. `action` selects which fields matter."""
    model_config = ConfigDict(extra="forbid")

    # goto      navigate to `url`
    # click     click `selector`
    # fill      type `value` into `selector`
    # press     press `value` (a key) at `selector` (defaults to the page body)
    # wait      sleep `ms`
    # wait_for  wait for `selector` to appear, up to `ms`
    # text      read the text of `selector` (or the whole body)
    action: str = Field(min_length=1, max_length=20)
    selector: str = Field(default="", max_length=1000)
    value: str = Field(default="", max_length=4000)
    url: str = Field(default="", max_length=2048)
    ms: int = Field(default=1000, ge=0, le=30000)
    delay_ms: int = Field(default=0, ge=0, le=1000)
    name: str = Field(default="", max_length=200)
    index: int = Field(default=0, ge=0, le=500)
    limit: int = Field(default=100, ge=1, le=200)


class DriveBody(BaseModel):
    """A scripted sequence for the private browser worker to perform.

    The manipulation twin of FetchBody: /fetch READS a page, /drive OPERATES
    one. Steps run in order and the run stops at the first failure -- an agent
    that has to click through an app gets asked to, and told exactly which step
    failed and why, rather than being handed a page and left to guess.
    """
    model_config = ConfigDict(extra="forbid")

    url: str = Field(default="", max_length=2048)
    steps: list[DriveStep] = Field(default_factory=list, max_length=40)
    # Whole-run budget. The worker also caps each step; this is the backstop
    # that stops one slow selector holding a browser forever.
    timeout_ms: int = Field(default=45000, ge=1000, le=180000)
    session: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9._-]*$")
    close_session: bool = False
    allowed_hosts: list[str] = Field(default_factory=list, max_length=32)
    canaries: list[str] = Field(default_factory=list, max_length=20)
    include_events: bool = True
    screenshot: bool | Literal["never", "failure", "canary", "always"] = "failure"
    screenshot_full_page: bool = False

    @model_validator(mode="after")
    def _need_something(self):
        # Reject an empty request here rather than round-tripping to the worker
        # to be told the same thing. Same refusal, one less hop, and the caller
        # gets a 422 from the API it is actually talking to.
        if not self.url and not self.steps and not (self.session and self.close_session):
            raise ValueError("nothing to do: supply url and/or steps")
        return self


def _attempts(meta: dict) -> list:
    """Per-engine telemetry: who answered, with how many rows, how fast.

    Callers use this to tell an honestly empty result from a silently degraded
    one. An engine that has been CAPTCHA-ed out contributes zero rows and no
    error, which looks exactly like a query nobody has written about.
    """
    rows = []
    for name, count in (meta.get("per_source") or {}).items():
        # A source can report a row count or the string "not_configured".
        # Both become a count here, because callers do arithmetic on this
        # field -- but the distinction survives in `status`, which is the
        # whole reason the source bothered to say so.
        configured = not isinstance(count, str)
        rows.append({"engine": name,
                     "count": count if configured else 0,
                     "status": "ok" if configured else count,
                     "elapsed_ms": meta.get("elapsed_ms", 0),
                     "unresponsive": []})
    browser = meta.get("browser_search") or {}
    if browser:
        rows.append({"engine": "browser-search", "count": 0,
                     "status": browser.get("status", "unknown"),
                     "elapsed_ms": browser.get("elapsed_ms", 0),
                     "unresponsive": []})
        for attempt in browser.get("attempts") or []:
            rows.append({"engine": "browser-" + str(attempt.get("engine") or "unknown"),
                         "count": attempt.get("count", 0),
                         "status": attempt.get("status"),
                         "reason": attempt.get("reason"),
                         "elapsed_ms": int(1000 * float(attempt.get("elapsed_s") or 0)),
                         "unresponsive": []})
    return rows


def _search_row(row: dict, meta: dict, index: int) -> dict:
    return {
        "url": row.get("url", ""),
        "title": row.get("title", ""),
        "snippet": row.get("snippet", ""),
        "publishedDate": row.get("publishedDate") or None,
        "engine": row.get("engine", "dethrottled"),
        "engines": [row.get("engine", "dethrottled")],
        "category": None,
        "score": None,
        "cached": False,
        "search_attempts": _attempts(meta) if index == 0 else [],
        "search_elapsed_ms": meta.get("elapsed_ms", 0),
        # Which ranking stages actually ran.
        "ranking": meta.get("ranking", []) if index == 0 else [],
        "from_corpus": bool(row.get("from_corpus")),
    }


MIME = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "csv": "text/csv",
    "docx": ("application/vnd.openxmlformats-officedocument"
             ".wordprocessingml.document"),
    "pptx": ("application/vnd.openxmlformats-officedocument"
             ".presentationml.presentation"),
    "html": "text/html",
}


def _render_mode(render) -> str:
    """auto | always | never, whichever spelling arrived.

    The enum is canonical and a bool is a documented alias, because this field
    was typed differently on two engines and the mismatch returned 422 on every
    fetch through a bridge for a day. Accepting both on both is what makes them
    agree without breaking either engine's callers.
    """
    if isinstance(render, bool):
        return "always" if render else "auto"
    return render


def _extract_row(url: str, max_chars: int, allow_ocr: bool = True,
                 page_budget: float | None = None, allow_render: bool = True,
                 raw: bool = False, render_first: bool = False,
                 links: bool = False, fresh: bool = False) -> dict:
    # allow_ocr is the one-URL-versus-many split. OCR costs about 1.4s a page,
    # which is worth it for a page somebody asked for by name and is not worth
    # it multiplied across a page of search results.
    # fresh means fresh. The cache is a parameter, so bypassing it is simply
    # not passing one -- and a field that says it bypasses the cache must, or
    # a caller cannot tell what they measured.
    result = fetcher.fetch_and_extract(url, max_chars=max_chars,
                                       cache=None if fresh else cache(),
                                       allow_ocr=allow_ocr,
                                       page_budget=page_budget,
                                       allow_render=allow_render,
                                       render_first=render_first,
                                       keep_html=raw or links)
    # Record what happened, per domain. A cache hit is not evidence about the
    # site -- it says the cache worked, which is a different fact -- so only
    # live attempts count.
    if not result.get("cached"):
        domain_health.record(url, result["ok"])

    if not result["ok"]:
        return {"url": url, "content": "", "content_type": None,
                "quality": "failed", "failure_reason": result["reason"][:160],
                # fetch_and_extract now reports which tier it was last
                # standing on when it gave up; a hardcoded None here would
                # throw that away and leave a tier-only consumer with nothing.
                "tier": result.get("tier"), "cached": result.get("cached", False)}
    row = {
        "url": url,
        "content": result["text"],
        "content_type": MIME.get(result.get("content_type", ""), "text/html"),
        "quality": "ok",
        # `tier` says HOW the content was obtained: which fetch tier, which
        # extractor. "It worked" and "it worked on the fourth try through a
        # renderer" are different levels of confidence in the same text.
        "tier": "%s/%s" % (result["tier"], result["extractor"]),
        "cached": result.get("cached", False),
        "title": result.get("title", ""),
        "published": result.get("published", ""),
        # Only present when the caller asked for it. Absent, not empty, so a
        # client can distinguish did-not-ask from asked-and-got-nothing.
        **({"html": result.get("html", "")} if raw else {}),
    }
    if links:
        # Falls back to the prose on an empty result rather than handing
        # back nothing: a page whose anchors could not be parsed is still
        # a page the caller asked to read.
        annotated = fx.links(result.get("html", ""), url, max_chars=max_chars)
        if annotated:
            row["content"] = annotated
    elif raw and result.get("html"):
        # format=html asked for the source, so the source is the content. It is
        # still echoed in `html` for callers written against raw=true.
        row["content"] = result["html"][:max_chars]
    return row


@app.get("/health")
def health():
    return {"status": "ok", "service": "dethrottled", "version": VERSION}


@app.get("/ready")
def ready():
    report = fs.health()
    return {"status": "ok" if report["ok"] else "degraded", **report}


@app.get("/v2/status")
def v2_status():
    report = fs.health()
    return {
        "status": "ok" if report["ok"] else "degraded",
        "components": {
            # An unconfigured source is not a down source: "down" sends you
            # looking for a broken service, "not_configured" sends you to the
            # settings, and only one of those is where the problem is.
            "searxng": {"status": "ok" if report["searxng"]
                        else ("down" if fs.SEARXNG_URL else "not_configured")},
            "bing_news_rss": {"status": "ok" if report["bing_news"] else "down"},
        },
        "providers": {k: {"configured": v}
                      for k, v in fx.available().items()},
        "profiles": {p: {"ready": True} for p in ("fast", "balanced", "thorough")},
        "cost": {"api_calls": 0, "daily_caps": None, "keys_required": False},
        "uptime_seconds": int(time.time() - STARTED),
    }


@app.get("/v2/capabilities")
def v2_capabilities():
    import importlib.util
    import shutil

    def installed(name: str) -> bool:
        return importlib.util.find_spec(name) is not None

    readable = ["html", "csv", "tsv"]
    for module, formats in (
        ("pymupdf", ("pdf",)),
        ("openpyxl", ("xlsx",)),
        ("xlrd", ("xls",)),
        ("docx", ("docx",)),
        ("pptx", ("pptx",)),
        ("odf", ("odt", "ods", "odp")),
        ("ebooklib", ("epub",)),
        ("striprtf", ("rtf",)),
    ):
        if installed(module):
            readable.extend(formats)

    return {
        "service": "dethrottled",
        "version": VERSION,
        # What is CONFIGURED, not what the code is capable of. Listing searxng
        # on a host with no SearXNG is the same class of lie as a health check
        # that reports ok because a socket opened.
        "search": [name for name, on in (
            ("browser-search", bool(fs.BROWSER_SEARCH_URL)),
            # General web, via whichever keyless engines still answer. Listed
            # by the engines actually configured. Direct DDGS is a fallback
            # when the private browser worker is configured and responsive.
            *(("web-%s" % e, True) for e in fs.WEB_ENGINES),
            ("searxng-multi-engine", bool(fs.SEARXNG_URL)),
            ("bing-news-rss", True),
            ("google-news-rss", True)) if on],
        # In ladder order, and only what is actually switched on. Listing
        # jina-reader here while DETHROTTLED_ENABLE_JINA=0 was a lie of exactly
        # the kind /v2/status exists to avoid.
        "fetch_tiers": [name for name, on in (
            ("direct", True),
            ("tls", fetcher.ENABLE_TLS),
            ("crawl4ai", bool(fetcher.CRAWL4AI_URL)),
            ("jina-reader", fetcher.ENABLE_JINA),
        ) if on],
        # Browser MANIPULATION, as distinct from the fetch ladder above. /fetch
        # reads a page; /drive operates one. Present only when the private
        # worker that owns the headed browser is configured -- /drive is a
        # straight proxy to it, so with no worker the capability is absent, not
        # degraded. Same rule the fetch tiers follow: never advertise a rung
        # that cannot answer.
        "manipulation": {
            "available": bool(fs.BROWSER_SEARCH_URL),
            "endpoint": "/drive",
            "actions": list(fs.DRIVE_ACTIONS),
            "persistent_sessions": True,
            "session_ttl_seconds": fs.DRIVE_SESSION_TTL,
            "max_sessions": fs.DRIVE_MAX_SESSIONS,
            "screenshot_modes": ["never", "failure", "canary", "always"],
            "event_telemetry": ["dialogs", "console", "page_errors",
                                "request_failures", "http_errors"],
            "navigation_allowlist": True,
        },
        "tiers_resting": fetcher.tier_rest_state(),
        "extract": [k for k, v in fx.available().items() if v],
        "ranking": ranker.available(),
        "research": {"available": True, "model_used": False,
                     "max_sources": 6, "max_queries": 4},
        "read": {
            "formats": readable,
            "pdf_ocr_installed": installed("pymupdf") and shutil.which("tesseract") is not None,
            # Installed is not the same as reachable: YouTube may refuse this
            # host, so this does not promise that a given transcript succeeds.
            "youtube_captions_configured": (
                installed("youtube_transcript_api")
                and _transcripts_enabled()),
            "pdf_max_bytes": fetcher.PDF_MAX_BYTES,
            "document_max_bytes": fetcher.DOC_MAX_BYTES,
        },
        "quotas": None,
        "keys_required": False,

        # Policy, so a caller can choose an engine on what it will and will not
        # do rather than discovering it from a refusal.
        #
        # No tier in the fetch ladder consults robots.txt.
        "respects_robots": False,
        # Every tier here is free and keyless, so a call costs a caller nothing
        # and no budget can be exhausted on their behalf.
        "metered_tiers": False,
        # The external reader is the only tier that would send a URL to a third
        # party, and it is off unless explicitly enabled.
        "leaves_network": bool(fetcher.ENABLE_JINA),
        # What `fresh` bypasses.
        "cache_ttl_seconds": 6 * 3600,

        # Beyond the core contract fields, which every engine takes. A client
        # sends core + whatever is listed here, so one client works against
        # engines that differ without knowing which it is talking to.
        # Every field accepted beyond the core, and nothing that is not. An
        # under-declared field is as bad as an over-declared one: a client that
        # trusts this drops a refinement the engine would have used.
        "optional_fields": {
            # Only fields this engine actually honours. `engines` and
            # `profile` are accepted for compatibility but change nothing --
            # engines would reach one of five sources, profile is read
            # nowhere -- and a declared field is a promise that sending it
            # does something.
            "search": ["categories", "language", "rank",
                       "corpus", "recency"],
            "fetch": ["raw", "links"],
        },
    }


def _transcripts_enabled() -> bool:
    from . import media
    return media.ENABLED


def _ranked(body) -> tuple:
    """Search, then order the pool BEFORE anything expensive happens to it.

    The whole point of ranking here rather than in the caller is that fetching
    is the costly step: order first, fetch only the winners. A caller that
    ranks after fetching has already paid for every page it is about to throw
    away.

    Over-fetches the pool on purpose when ranking is on. Ranking `limit` rows
    and returning `limit` rows is not ranking, it is sorting -- there has to be
    something for the ranker to reject.
    """
    limit = body.limit or body.max_items or body.num_results
    pool = limit * 3 if body.rank else limit
    rows, meta = fs.search(body.query, max_items=pool,
                           categories=body.categories,
                           language=body.language or None,
                           # Same again: fresh bypasses the six-hour search
                           # cache rather than being accepted and ignored.
                           cache=None if body.fresh else cache())
    rows, stages = ranker.apply(
        rows, body.query, bm25=body.rank,
        corpus=body.corpus, recency=body.recency)
    # AFTER ranking, and only here. Relevance order is decided above and is
    # not touched; this moves domains that measurably never yield text to the
    # back of the queue, so the fetches about to be spent land on results that
    # can actually be read. Nothing is dropped -- if the whole pool is poor
    # domains, they are still what comes back.
    ordered = domain_health.order_for_fetching(rows)
    if ordered[:limit] != rows[:limit]:
        stages.append("fetchability")
    rows = ordered

    meta = dict(meta, ranking=stages)
    return rows[:limit], meta, limit


@app.post("/search")
def search(body: SearchBody):
    rows, meta, _limit = _ranked(body)
    return [_search_row(r, meta, i) for i, r in enumerate(rows)]


def _harvest(rows) -> list:
    """(url, row) pairs worth indexing, from API rows."""
    return [(r.get("url", ""), r) for r in rows
            if r.get("quality") == "ok" and r.get("content")]


@app.post("/fetch")
@app.post("/extract")            # alias, for callers written against the old name
def fetch_urls(body: FetchBody, background: BackgroundTasks):
    # Named URLs: try hard, OCR included.
    # format is the contract's single name; raw/links remain accepted for
    # callers written against them, and format wins when both are given.
    # Both spellings converge here, so nothing downstream has to know which
    # arrived.
    mode = _render_mode(body.render)
    want_html = body.format == "html" or (body.format == "text" and body.raw)
    want_links = body.format == "links" or (body.format == "text" and body.links)
    rows = _read_batch(
        [u for u in body.urls if u],
        lambda u: _extract_row(u, body.max_chars, allow_ocr=True,
                               allow_render=mode != "never",
                               render_first=mode == "always",
                               raw=want_html, links=want_links,
                               fresh=body.fresh))
    # Indexed AFTER the response, not during it. Embedding costs ~250ms a page
    # and the caller should not wait for work they did not ask for.
    # Not indexed when links were kept: the corpus is prose to match
    # against later, and this output has markdown link syntax woven
    # through it. Feeding it in makes every future match slightly worse.
    if not body.links:
        background.add_task(index_fetched, _harvest(rows))
    return rows


@app.post("/extract-with-links")
def fetch_with_links(body: FetchBody, background: BackgroundTasks):
    """`/fetch` with the anchors kept. Same verb, different output shape.

    A route rather than only a parameter for the same reason `/extract` is
    still here: it is what existing callers were written against, and renaming
    for tidiness is a poor trade. `links: true` on /fetch does exactly this.

    Note this path does not use the page cache -- keeping the source HTML
    bypasses it, because caching twenty times the bytes to serve a minority of
    requests is the wrong trade for a cache whose whole point is many pages
    cheaply.
    """
    body.links = True
    return fetch_urls(body, background)


@app.post("/drive")
def drive(body: DriveBody):
    """Operate the private browser: navigate, click, fill, read, screenshot.

    The manipulation twin of /fetch. /fetch READS a page; /drive OPERATES one,
    holding a real session the way an agent driving an app has to. Proxied
    straight to the private browser worker, which owns the single warm, headed,
    stealth browser this stack already runs -- so a caller never launches a
    browser, picks a Chromium build, or sets a DISPLAY.

    Steps run in order and the run STOPS at the first failure, reporting which
    step failed and why. A driver that presses on after a failed click is
    describing a page it is no longer looking at.

    The worker being absent, overloaded, or refusing is a 502 here, not an
    empty 200: a caller that asked a browser to click something must never be
    told "ok, nothing happened".
    """
    payload = body.model_dump()
    try:
        return fs.browser_drive(payload)
    except fs.BrowserWorkerError as exc:
        # A client-side refusal from the worker (4xx) is the caller's fault and
        # should reach them as-is; only an unreachable or failing worker is a
        # 502. Flattening "your step was malformed" into "bad gateway" is how a
        # caller ends up debugging the wrong machine.
        code = exc.status if 400 <= (exc.status or 0) < 500 else 502
        raise HTTPException(status_code=code, detail=exc.detail) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:300]) from exc


@app.post("/search-and-fetch")
@app.post("/search-and-extract")     # alias
def search_and_fetch(body: SearchFetchBody, background: BackgroundTasks):
    rows, meta, _limit = _ranked(body)
    def read(indexed):
        index, row = indexed
        merged = _search_row(row, meta, index)
        # Search results: no OCR. N results times 1.4s a page is a different
        # trade from one URL somebody asked for.
        sf_mode = _render_mode(body.render)
        extracted = _extract_row(row.get("url", ""), body.max_chars,
                                 allow_ocr=False,
                                 page_budget=fetcher.PAGE_BUDGET_BULK,
                                 allow_render=sf_mode != "never",
                                 render_first=sf_mode == "always",
                                 raw=body.raw)
        merged.update({k: v for k, v in extracted.items() if k != "url"})
        return merged

    out = _read_batch(list(enumerate(rows)), read)
    # This is the high-volume route, so it is the one that actually grows the
    # corpus -- and it was growing it by nothing at all.
    background.add_task(index_fetched, _harvest(out))
    return out


_RESEARCH_REQUESTS = threading.BoundedSemaphore(2)


@app.post("/research")
def research(body: ResearchBody, background: BackgroundTasks):
    """Collect a cited, diverse evidence bundle without a language model."""
    if not _RESEARCH_REQUESTS.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="research busy")
    started = time.monotonic()
    try:
        if any(not query.strip() or len(query) > 500 for query in body.queries):
            raise HTTPException(status_code=422, detail="invalid research query")
        if body.categories not in {"", "news"}:
            raise HTTPException(status_code=422, detail="invalid research category")
        queries = research_engine.queries_for(body.question, body.queries or None)
        def search_one(query):
            try:
                rows, meta, _ = _ranked(SearchBody(
                    query=query, limit=8, language=body.language,
                    fresh=body.fresh, categories=body.categories))
                return rows, {"query": query, "found": len(rows),
                              "elapsed_ms": meta.get("elapsed_ms", 0),
                              "attempts": _attempts(meta)}
            except Exception as exc:
                return [], {"query": query, "found": 0,
                            "error": type(exc).__name__}

        # Two research requests may run concurrently; at most two discovery
        # probes from each are active, while map preserves the query order.
        with ThreadPoolExecutor(max_workers=2) as pool:
            probed = list(pool.map(search_one, queries))
        searches = [rows for rows, _ in probed]
        telemetry = [meta for _, meta in probed]

        selected = research_engine.select_sources(
            searches, body.max_sources + 4,
            official_first=not body.queries)

        def read(item):
            try:
                row = _extract_row(item["url"], body.max_chars,
                                   allow_ocr=True,
                                   page_budget=fetcher.PAGE_BUDGET_BULK,
                                   fresh=body.fresh)
            except Exception as exc:
                row = {"url": item["url"], "quality": "failed", "content": "",
                       "failure_reason": type(exc).__name__}
            content = row.get("content", "")
            return {**item, **row,
                    "title": row.get("title") or item["title"],
                    "evidence": research_engine.evidence_windows(
                        content, body.question)}

        sources, skipped, fingerprints = [], [], []
        with ThreadPoolExecutor(max_workers=3) as pool:
            pending = selected[:body.max_sources]
            offset = len(pending)
            while pending:
                for item in pool.map(read, pending):
                    if item.get("quality") == "ok" and item.get("content"):
                        fingerprint = research_engine.content_shingles(item["content"])
                        duplicate_of = research_engine.duplicate_source(
                            fingerprint, fingerprints)
                        if duplicate_of:
                            skipped.append({"url": item["url"],
                                            "reason": "duplicate_content",
                                            "duplicate_of": duplicate_of})
                        else:
                            sources.append(item)
                            fingerprints.append((item["url"], fingerprint))
                    else:
                        skipped.append({"url": item["url"],
                                        "reason": item.get("failure_reason")
                                        or "empty_content"})
                if len(sources) >= body.max_sources or offset >= len(selected):
                    break
                pending = selected[offset:offset + body.max_sources - len(sources)]
                offset += len(pending)
        sources = sources[:body.max_sources]
        for index, item in enumerate(sources, 1):
            item["id"] = "S%d" % index
        background.add_task(index_fetched, _harvest(sources))
        return {"question": body.question, "queries": telemetry,
                "sources": sources, "skipped": skipped,
                "summary": {"candidates": sum(len(rows) for rows in searches),
                            "selected": len(sources),
                            "read": len(sources),
                            "attempted": len(sources) + len(skipped),
                            "elapsed_ms": int((time.monotonic() - started) * 1000),
                            "model_used": False}}
    finally:
        _RESEARCH_REQUESTS.release()


@app.get("/corpus/search")
def corpus_search(q: str, limit: int = 10, floor: float | None = None):
    """Search what has already been fetched, without fetching anything.

    The index was being written on every extraction and read by nothing over
    HTTP, which made it a write-only store: pages went in, and the only way to
    get one back was to fetch it off the network again.

    `floor` is what stops this answering a question it has nothing for. Cosine
    similarity always returns a best match, and the best match against an empty
    subject is noise with a number next to it. Leave it unset to use the floor
    calibrated for whichever model is in use -- the two do not share a scale.
    """
    try:
        hits = shared_corpus().search(q, limit=limit, floor=floor)
    except Exception as exc:
        return {"ok": False, "reason": str(exc)[:200], "results": []}
    return {"ok": True, "count": len(hits), "results": hits}


@app.get("/corpus/stats")
def corpus_stats():
    try:
        return {"ok": True, "models": shared_corpus().stats()}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)[:200], "models": {}}


@app.get("/stats")
def stats():
    # Tier budgets are surfaced because their exhaustion used to be invisible:
    # they were lifetime counters that nothing reset, so crawl4ai stopped
    # rendering after 8 pages and jina after 25, silently, for the rest of the
    # process. They refill hourly now, and you can see how much is spent.
    return {"cache": cache().stats(), "version": VERSION,
            "tiers_resting": fetcher.tier_rest_state(),
            "domain_health": domain_health.stats(),
            "uptime_seconds": int(time.time() - STARTED),
            "tiers": fetcher.tier_stats(),
            "tier_budget_used": fetcher.budget_state(),
            "tier_budgets": {"crawl4ai": fetcher.CRAWL4AI_BUDGET,
                             "jina-reader": fetcher.JINA_READER_BUDGET,
                             "window_seconds": fetcher.BUDGET_WINDOW}}


def main():
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get(
        "DETHROTTLED_HOST", "127.0.0.1"),
        help="loopback by default; see docs/OPERATIONS.md before changing it")
    parser.add_argument("--port", type=int, default=int(os.environ.get(
        "DETHROTTLED_PORT", "8787")))
    jina = parser.add_mutually_exclusive_group()
    jina.add_argument("--jina", dest="jina", action="store_true", default=None,
                      help="allow the external r.jina.ai reader tier")
    jina.add_argument("--no-jina", dest="jina", action="store_false",
                      help="never contact r.jina.ai; local tiers only")
    args = parser.parse_args()
    if args.jina is not None:
        # Set before anything imports the value off the module.
        fetcher.ENABLE_JINA = args.jina
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
