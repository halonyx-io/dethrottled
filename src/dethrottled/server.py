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
import base64
import os
import secrets
import sqlite3
import threading
import time
import uuid
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
from . import ocr as ocr_engine
from . import paths as _paths
from . import providers
from . import rank as ranker
from . import research as research_engine
from . import search as fs
from .cache import Cache, CacheView
from .content import compact_row, constrained, passage_excerpt
from .corpus import index_fetched, shared_corpus
from .evidence import Documents
from .jobs import JobError, Jobs
from .workflow import INSTRUCTIONS, guidance

_jobs = None
_jobs_lock = threading.Lock()

_documents = None
_documents_lock = threading.Lock()


def documents():
    global _documents
    with _documents_lock:
        if _documents is None:
            _documents = Documents(_paths.data_dir() / "evidence.sqlite")
        return _documents


def jobs():
    global _jobs
    with _jobs_lock:
        if _jobs is None:
            _jobs = Jobs(_paths.data_dir() / "jobs.sqlite")
        return _jobs


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


@app.middleware("http")
async def request_trace(request, call_next):
    incoming = request.headers.get("x-request-id", "")
    valid = len(incoming) == 32 and all(c in "0123456789abcdef" for c in incoming)
    trace = incoming if valid else (
        uuid.uuid4().hex)
    response = await call_next(request)
    response.headers["X-Request-ID"] = trace
    return response


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

    query: str = Field(min_length=1, max_length=500)
    # The contract's name for result count. num_results and max_items remain
    # accepted for callers already written against them; limit wins.
    limit: int | None = Field(default=None, ge=1, le=10)
    num_results: int = Field(default=8, ge=1, le=10)
    max_items: int | None = Field(default=None, ge=1, le=10)
    # Default search includes direct web, Bing News RSS, local SearXNG and
    # resolved Google News headlines. This preserves existing callers.
    categories: Literal["", "news", "academic"] = ""
    # SearXNG uses this hint. Direct web engines are
    # English-centric and do not take it, so it biases rather than constrains.
    language: str = ""
    engines: str = ""

    @field_validator("engines")
    @classmethod
    def validate_sources(cls, value):
        allowed = {"auto", "web", "news", "mwmbl", "crossref", "openalex", "arxiv",
                   "exa", "tavily", "parallel"}
        if any(x.strip() not in allowed for x in value.split(",") if x.strip()):
            raise ValueError("supported sources: " + ", ".join(sorted(allowed)))
        return ",".join("web" if x.strip() == "auto" else x.strip()
                        for x in value.split(",") if x.strip())

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, value):
        if not value.strip():
            raise ValueError("query must not be blank")
        return value.strip()

    # Honoured: bypasses the search cache for this call. It was accepted and
    # ignored until an external benchmark set it, measured this engine's cache
    # against another engine doing live work, and published the wrong
    # conclusion. Accepting a field costs nothing right up until someone
    # believes it.
    fresh: bool = False
    cache_mode: Literal["use", "refresh", "bypass"] = "use"
    max_age: float | None = Field(default=None, ge=0, le=1814400)
    profile: Literal["fast", "web", "balanced", "thorough", "news", "academic"] = "web"

    # Source order is the measured default; BM25 remains opt-in.
    rank: bool = False
    ranking: Literal["source", "bm25", "fusion"] = "source"
    prefer_domains: list[str] = Field(default_factory=list, max_length=10)
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
    corpus: int = Field(default=0, ge=0, le=20)
    # 0.0 = pure relevance, 1.0 = freshness dominates. Bounded and
    # multiplicative: it may reorder relevant results and may never promote an
    # irrelevant one.
    recency: float = Field(default=0.0, ge=0, le=1)


class FetchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    urls: list[str] = Field(min_length=1, max_length=10)
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
    render: Literal["auto", "always", "never"] | bool = "auto"
    # text   article prose (default)
    # links  prose with anchors kept as markdown, for link discovery
    # html   the source, for callers doing their own parsing
    #
    # Replaces the raw/links booleans, which could contradict each other and
    # left a caller no way to say "either one" without knowing which won.
    format: Literal["text", "links", "html"] = "text"
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
    max_chars: int = Field(default=8000, ge=1, le=120000)
    fresh: bool = False
    cache_mode: Literal["use", "refresh", "bypass"] = "use"
    max_age: float | None = Field(default=None, ge=0, le=1814400)
    wait_for: str = Field(default="", max_length=500)
    render_delay: float = Field(default=0.5, ge=0, le=5)
    headed_fallback: bool = False
    public_only: bool = False
    focus: str = Field(default="", max_length=1000)
    response_format: Literal["detailed", "concise"] = "detailed"
    evidence_namespace: str = Field(default="local", max_length=100)
    ocr_language: str = Field(default="", pattern=r"^[a-z_]*(?:\+[a-z_]+)*$", max_length=100)
    document_mode: Literal["auto", "native", "layout"] = "auto"
    ocr_mode: Literal["auto", "always", "never"] = "auto"
    row_start: int = Field(default=1, ge=1, le=1048576)
    row_end: int | None = Field(default=None, ge=1, le=1048576)
    sheet: str = Field(default="", max_length=200)
    max_cell_chars: int | None = Field(default=None, ge=1, le=1000000)
    page_start: int = Field(default=1, ge=1, le=100000)
    page_end: int | None = Field(default=None, ge=1, le=100000)
    recovery: Literal["auto", "manual"] = "auto"
    profile: Literal["fast", "balanced", "thorough"] = "balanced"


    @model_validator(mode="after")
    def read_constraints(self):
        if self.page_end is not None and (self.page_end < self.page_start
                                          or self.page_end - self.page_start >= 100):
            raise ValueError("page range must contain 1 to 100 pages")
        if self.row_end is not None and (self.row_end < self.row_start
                                         or self.row_end - self.row_start >= 2000):
            raise ValueError("row range must contain 1 to 2000 rows")
        if self.focus and (self.format != "text" or self.raw or self.links):
            raise ValueError("focus requires text format")
        if self.wait_for and (self.render == "never" or self.profile == "fast"):
            raise ValueError("wait_for requires rendering")
        return self


class SearchFetchBody(SearchBody):
    document_mode: Literal["auto", "native", "layout"] = "auto"
    ocr_mode: Literal["auto", "always", "never"] = "auto"
    ocr_language: str = Field(default="", pattern=r"^[a-z_]*(?:\+[a-z_]+)*$", max_length=100)
    evidence_namespace: str = Field(default="local", max_length=100)
    # auto | always | never. A bool is also accepted and mapped, because
    # callers were written against one -- and because typing this field
    # differently on two engines is what returned 422 on every fetch through a
    # bridge for a day. The enum is canonical; True means always, False auto.
    render: Literal["auto", "always", "never"] | bool = "auto"
    raw: bool = False
    # 3000. Leaner than /extract on purpose: this path multiplies by the number
    # of results, and it is the ranking path, where measurement says less text
    # ranks better -- titles plus 240 characters beat 3,000 characters of body.
    # 3000 is the measured sweet spot for the ranking path.
    max_chars: int = Field(default=3000, ge=1, le=120000)


class ResearchBody(BaseModel):
    """A question and optional facets; returns sources, not a model answer."""
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=500)
    queries: list[str] = Field(default_factory=list, max_length=3)
    max_sources: int = Field(default=6, ge=1, le=6)
    max_chars: int = Field(default=5000, ge=500, le=6000)
    language: str = ""
    fresh: bool = False
    follow_assets: bool = True
    engines: str = ""
    profile: Literal["web", "balanced", "thorough", "academic", "news"] = "thorough"
    categories: str = ""
    response_format: Literal["detailed", "concise"] = "detailed"
    evidence_namespace: str = Field(default="local", max_length=100)


    @field_validator("engines")
    @classmethod
    def validate_engines(cls, value):
        return SearchBody.validate_sources(value)


class DocumentReadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(min_length=1, max_length=100)
    public_only: bool = False
    focus: str = Field(default="", max_length=1000)
    reparse: bool = False
    row_start: int = Field(default=1, ge=1, le=1048576)
    row_end: int | None = Field(default=None, ge=1, le=1048576)
    sheet: str = Field(default="", max_length=200)
    max_cell_chars: int | None = Field(default=None, ge=1, le=1000000)
    page_start: int = Field(default=1, ge=1, le=100000)
    page_end: int | None = Field(default=None, ge=1, le=100000)
    document_mode: Literal["auto", "native", "layout"] = "auto"
    ocr_mode: Literal["auto", "always", "never"] = "auto"
    ocr_language: str = Field(default="", pattern=r"^[a-z_]*(?:\+[a-z_]+)*$", max_length=100)
    offset: int = Field(default=0, ge=0)
    max_chars: int = Field(default=12000, ge=1, le=120000)
    response_format: Literal["detailed", "concise"] = "detailed"
    evidence_namespace: str = Field(default="local", max_length=100)


    @model_validator(mode="after")
    def bounded_ranges(self):
        if self.row_end is not None and (self.row_end < self.row_start
                                        or self.row_end - self.row_start >= 2000):
            raise ValueError("row range must contain 1 to 2000 rows")
        if self.page_end is not None and (self.page_end < self.page_start
                                         or self.page_end - self.page_start >= 100):
            raise ValueError("page range must contain 1 to 100 pages")
        return self


class DocumentImageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    public_only: bool = False
    document_id: str = Field(min_length=1, max_length=100)
    page: int = Field(default=1, ge=1)
    max_dimension: int = Field(default=2400, ge=512, le=6000)
    crop: tuple[int, int, int, int] | None = None
    evidence_namespace: str = Field(default="local", max_length=100)


class FetchJobBody(FetchBody):
    operation_id: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9._-]*$")


class JobReadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1, max_length=100)
    cursor: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=10)
    evidence_namespace: str = Field(default="local", max_length=100)


class StructureBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(min_length=1, max_length=100)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=30, ge=1, le=100)
    focus: str = Field(default="", max_length=1000)
    evidence_namespace: str = Field(default="local", max_length=100)


class SiteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    urls: list[str] = Field(min_length=1, max_length=10)
    max_pages: int = Field(default=10, ge=1, le=50)
    max_depth: int = Field(default=2, ge=0, le=5)
    path_prefix: str = Field(default="/", max_length=1000, pattern=r"^/")
    render: Literal["auto", "always", "never"] = "auto"
    public_only: bool = False
    evidence_namespace: str = Field(default="local", max_length=100)

    @model_validator(mode="after")
    def site_scope(self):
        from urllib.parse import urlsplit

        from .site import canonical
        self.urls = [canonical(u) for u in self.urls]
        origins = {(urlsplit(u).scheme, urlsplit(u).netloc) for u in self.urls}
        if len(origins) != 1 or any(
            not urlsplit(u).path.startswith(self.path_prefix) for u in self.urls
        ):
            raise ValueError("seeds must share one origin and match path_prefix")
        return self


class DriveStep(BaseModel):
    """One action for the browser to take. `action` selects which fields matter."""
    model_config = ConfigDict(extra="forbid")

    # goto      navigate to `url`
    # click     click `selector`
    # fill      set `value` and emit input/change events at `selector`
    # press     press `value` (a key) at `selector` (defaults to the page body)
    # wait      sleep `ms`
    # wait_for  wait for `selector` to appear, up to `ms`
    # text      read the text of `selector` (or the whole body)
    action: str = Field(min_length=1, max_length=20)
    frame: str = Field(default="", max_length=1000,
                       description="CSS selector for an allowed iframe")
    selector: str = Field(default="", max_length=1000)
    value: str = Field(default="", max_length=4000)
    url: str = Field(default="", max_length=2048)
    ms: int = Field(default=1000, ge=0, le=30000)
    delay_ms: int = Field(default=0, ge=0, le=1000)
    name: str = Field(default="", max_length=200)
    index: int = Field(default=0, ge=0, le=500)
    limit: int = Field(default=100, ge=1, le=200)
    max_chars: int | None = Field(default=None, ge=1, le=120000)


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
    operation_id: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9._-]*$")
    close_session: bool = False
    allowed_hosts: list[str] = Field(default_factory=list, max_length=32)
    public_only: bool = False
    canaries: list[str] = Field(default_factory=list, max_length=20)
    include_events: bool = True
    screenshot: bool | Literal["never", "failure", "canary", "always"] = "failure"
    screenshot_full_page: bool = False
    evidence_namespace: str = Field(default="local", max_length=100)
    ocr_language: str = Field(default="", pattern=r"^[a-z_]*(?:\+[a-z_]+)*$", max_length=100)

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
                     "unresponsive": [],
                     **(meta.get("source_reports") or {}).get(name, {}),
                     **(meta.get("source_reports") or {}).get("providers", {}).get(name, {})})
    browser = meta.get("browser_search") or {}
    if browser.get("direct"):
        direct = browser["direct"]
        rows.append({"engine": "tls-ddg-lite", "count": direct.get("count", 0),
                     "status": direct.get("status"), "reason": direct.get("reason"),
                     "elapsed_ms": direct.get("elapsed_ms", 0), "unresponsive": []})
    if browser and browser.get("attempts"):
        rows.append({"engine": "browser-search", "count": 0,
                     "status": browser.get("status", "unknown"),
                     "elapsed_ms": browser.get("elapsed_ms", 0),
                     "queue_ms": browser.get("queue_ms", 0),
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
        "discovery": row.get("discovery", []),
        "category": None,
        "score": row.get("score"),
        "cached": bool(row.get("cached")),
        "retrieved_at": row.get("retrieved_at"),
        "cache_age_seconds": row.get("cache_age_seconds"),
        "upstream_rank": row.get("upstream_rank"),
        "search_attempts": _attempts(meta) if index == 0 else [],
        "search_elapsed_ms": meta.get("elapsed_ms", 0),
        # Which ranking stages actually ran.
        "ranking": meta.get("ranking", []) if index == 0 else [],
        "from_corpus": bool(row.get("from_corpus")),
    }


MIME = {
    "captions": "text/vtt", "media": "text/plain", "transcript": "text/plain",
    "text": "text/plain", "json": "application/json", "jsonl": "application/x-ndjson",
    "xml": "application/xml", "eml": "message/rfc822", "zip": "application/zip",
    "gzip": "application/gzip", "tar": "application/x-tar", "image": "application/octet-stream",
    "doc": "application/msword", "ppt": "application/vnd.ms-powerpoint",
    "epub": "application/epub+zip", "rtf": "application/rtf",
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


def _extract_once(url: str, max_chars: int, allow_ocr: bool = True,
                 page_budget: float | None = None, allow_render: bool = True,
                 raw: bool = False, render_first: bool = False,
                 links: bool = False, fresh: bool = False, cache_mode: str = "use",
                 max_age: float | None = None, wait_for: str = "", render_delay: float = 0.5,
                 headed_fallback: bool = False, public_only: bool = False,
                 focus: str = "", evidence_namespace: str = "local",
                 ocr_language: str = "", ocr_mode: str = "auto", page_start: int = 1,
                 page_end: int | None = None, row_start: int = 1,
                 row_end: int | None = None, sheet: str = "",
                 max_cell_chars: int | None = None, document_mode: str = "auto") -> dict:
    # allow_ocr is the one-URL-versus-many split. OCR costs about 1.4s a page,
    # which is worth it for a page somebody asked for by name and is not worth
    # it multiplied across a page of search results.
    # fresh means fresh. The cache is a parameter, so bypassing it is simply
    # not passing one -- and a field that says it bypasses the cache must, or
    # a caller cannot tell what they measured.
    result = fetcher.fetch_and_extract(url, max_chars=max(max_chars, fetcher.CACHE_CHARS)
                                       if focus else max_chars,
                                       cache=CacheView(cache(),
                                                       mode="refresh" if fresh else cache_mode,
                                                       max_age=max_age),
                                       allow_ocr=allow_ocr,
                                       page_budget=page_budget,
                                       allow_render=allow_render,
                                       render_first=render_first,
                                       keep_html=raw or links,
                                       format="html" if raw else "links" if links else "text",
                                       wait_for=wait_for, render_delay=render_delay,
                                       headed_fallback=headed_fallback, public_only=public_only,
                                       ocr_language=ocr_language, ocr_mode=ocr_mode,
                                       page_start=page_start,
                                       page_end=page_end, row_start=row_start, row_end=row_end,
                                       sheet=sheet, max_cell_chars=max_cell_chars,
                                       document_mode=document_mode)
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
        **({"html": result.get("html", "")[:max_chars]} if raw else {}),
        "retrieved_at": result.get("retrieved_at"),
        "cache_age_seconds": result.get("cache_age_seconds", 0),
        "cache_expires_at": result.get("cache_expires_at"),
        "truncated": bool(result.get("truncated")),
        "content_chars": result.get("content_chars", len(result.get("text", ""))),
        "content_status": result.get("content_status", "complete"),
        "assets": result.get("assets", []),
        "warnings": result.get("warnings", []),
        "_index_text": result.get("_index_text", result.get("text", "")),
        "acquisition": result.get("acquisition", {}),
        "extraction": result.get("extraction", {}),
        "source_partial": bool(result.get("extraction", {}).get("partial")),
        "final_url": result.get("url", url),
        "source_sha256": result.get("extraction", {}).get("source_sha256"),
    }
    canonical = row["_index_text"]
    try:
        metadata = {k: v for k, v in row.items() if k not in {"content", "html", "_index_text"}}
        row.update(documents().put(evidence_namespace, url, canonical, metadata))
    except (OSError, ValueError, sqlite3.Error) as exc:
        row["warnings"] = [*row["warnings"], "Document retention unavailable: "
                           + type(exc).__name__]
    if focus:
        selected, evidence = passage_excerpt(canonical, focus, max_chars)
        row.update(content=selected, evidence=evidence, focus=focus,
                   focus_status="term_matches" if evidence else "no_term_matches",
                   content_chars=len(canonical), truncated=len(selected) < len(canonical))
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
        row["content_chars"] = len(result["html"])
        row["truncated"] = len(result["html"]) > max_chars
    return row


def _extract_row(url, max_chars, *, recovery="auto", **options):
    """Recover known evidence gaps without guessing UI actions or hiding attempts."""
    row = _extract_once(url, max_chars, **options)
    attempts = []
    if recovery == "auto" and not options.get("raw") and not options.get("links"):
        if (
            row.get("content_status") == "navigation_only"
            and options.get("allow_render", True)
            and not row.get("acquisition", {}).get("rendered")
        ):
            retry_options = dict(options, render_first=True, headed_fallback=True)
            stronger = _extract_once(url, max_chars, **retry_options)
            attempts.append(
                {
                    "action": "render",
                    "url": url,
                    "quality": stronger.get("quality"),
                    "reason": "navigation_only",
                }
            )
            if (
                stronger.get("quality") == "ok"
                and stronger.get("content_status") != "navigation_only"
            ):
                row = stronger
        if row.get("content_status") == "image_content":
            for asset in row.get("assets", [])[:2]:
                if asset.get("kind") not in {"image", "document"}:
                    continue
                child_options = {
                    k: v
                    for k, v in options.items()
                    if k
                    not in {
                        "wait_for",
                        "render_first",
                        "row_start",
                        "row_end",
                        "sheet",
                        "max_cell_chars",
                        "page_start",
                        "page_end",
                    }
                }
                child = _extract_once(asset["url"], max_chars, **child_options)
                attempts.append(
                    {
                        "action": "read_asset",
                        "url": asset["url"],
                        "quality": child.get("quality"),
                        "reason": "image_content",
                    }
                )
                if child.get("quality") == "ok" and child.get("content"):
                    child.update(parent_url=url, parent_document_id=row.get("document_id"))
                    row = child
                    break
    if attempts:
        row["recovery_attempts"] = attempts
    row["workflow"] = guidance(
        row, focused=bool(options.get("focus")), rendered_allowed=options.get("allow_render", True)
    )
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
        "profiles": {p: {"sources": list(v)} for p, v in fs.SOURCE_PROFILES.items()},
        "cost": {"api_calls": 0, "daily_caps": None, "keys_required": False},
        "uptime_seconds": int(time.time() - STARTED),
    }


@app.get("/v2/capabilities")
def v2_capabilities():
    import hashlib
    import importlib.util
    import shutil

    def installed(name: str) -> bool:
        return importlib.util.find_spec(name) is not None

    readable = ["html", "csv", "tsv", "text", "markdown", "json", "jsonl", "xml", "vtt", "srt",
                "svg-text", "eml", "zip", "tar", "gzip"]
    if installed("PIL") and shutil.which("tesseract"):
        readable.extend(["png", "jpeg", "webp", "tiff", "gif", "bmp"])
    if shutil.which("antiword"):
        readable.append("doc")
    if shutil.which("catppt"):
        readable.append("ppt")
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
        "optional_search_providers": providers.configured(),
        "version": VERSION,
        "client_contract": {
            "workflow_sha256": hashlib.sha256(INSTRUCTIONS.encode()).hexdigest(),
            "preserve_fields": ["document_id", "document_sha256", "workflow", "warnings",
                                "source_partial", "truncated", "extraction", "next_offset"],
            "mcp_images": "forward native image content blocks to vision-capable models",
            "startup_check": "Compare initialize.instructions hash with workflow_sha256; "
                             "refresh tools/list after service upgrades.",
            "client_activation": "Server version does not prove a remote plugin revision loaded.",
        },
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
            "automatic_sessions": True,
            "session_ttl_seconds": fs.DRIVE_SESSION_TTL,
            "max_sessions": fs.DRIVE_MAX_SESSIONS,
            "screenshot_modes": ["never", "failure", "canary", "always"],
            "event_telemetry": ["dialogs", "console", "page_errors",
                                "request_failures", "http_errors"],
            "failure_diagnostics": ["hidden", "unstable", "covered",
                                    "out_of_viewport", "disabled", "detached",
                                    "selector_error"],
            "navigation_allowlist": True,
            "operation_replay": "durable journal; unknown outcomes never auto-repeat",
            "operation_retention_seconds": 86400,
            "checkpoint": {"action": "checkpoint", "retention_seconds": 86400,
                           "state": ["cookies", "local_storage", "indexed_db", "session_storage"],
                           "restore": "same session and original allowed_hosts"},
            "network_response_inspection": True,
            "frames": "CSS frame selector within allowed_hosts",
            "tabs": ["tabs", "switch_tab"],
            "action_history": "bounded outcome history; checkpoint persists it",
            "download_reading": True,
            "text_max_chars": 120000,
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
            "layout_worker_configured": bool(os.getenv("DETHROTTLED_LAYOUT_WORKER_URL")),
            "document_modes": ["auto", "native", "layout"],
            "speech_worker_configured": bool(os.getenv("DETHROTTLED_MEDIA_WORKER_URL")),
            "timed_caption_evidence": True,
            "pdf_page_selection": True,
            "pdf_mixed_page_ocr": True,
            "image_ocr_installed": installed("PIL") and shutil.which("tesseract") is not None,
            "ocr_language_selection": True,
            "ocr_languages": ocr_engine.languages(),
            "pdf_max_bytes": fetcher.PDF_MAX_BYTES,
            "document_max_bytes": fetcher.DOC_MAX_BYTES,
        },
        "workflow": {"instructions": INSTRUCTIONS, "automatic_recovery": [
            "transport/format/OCR ladder", "navigation-only rendered retry",
            "up to two image/document asset attempts"],
            "next_actions": "Each read returns tool, endpoint, arguments, reason and prerequisites",
            "manual_control": "fetch recovery=manual; explicit render/OCR/ranges remain available"},
        "documents": {"read_endpoint": "/documents/read", "versioned": True,
                      "retention_seconds": 604800, "scoped": True,
                      "structure_endpoint": "/documents/structure",
                      "citation_selectors": "exact text offsets and version hash"},
        "site": {"endpoint": "/site/crawl", "max_pages": 50,
                 "scope": "same origin and caller path prefix", "coverage_ledger": True},
        "jobs": {"submit_endpoint": "/jobs/fetch", "read_endpoint": "/jobs/read",
                 "cancel_endpoint": "/jobs/cancel", "retention_seconds": 86400,
                 "progressive": True, "restart_policy": "unfinished jobs become interrupted",
                 "resume_endpoint": "/jobs/resume", "resume": "explicit; missing sources only"},
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
            "search": ["categories", "language", "rank", "engines", "profile",
                       "cache_mode", "max_age", "ranking", "prefer_domains",
                       "corpus", "recency"],
            "fetch": ["raw", "links", "wait_for", "render_delay", "headed_fallback",
                      "cache_mode", "max_age", "focus", "response_format", "ocr_language",
                      "page_start", "page_end", "ocr_mode", "row_start", "row_end",
                      "sheet", "max_cell_chars", "recovery"],
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
    pool = limit * 3 if body.rank or body.ranking != "source" else limit
    rows, meta = fs.search(body.query, max_items=pool,
                           categories=body.categories,
                           language=body.language or None,
                           # Same again: fresh bypasses the six-hour search
                           # cache rather than being accepted and ignored.
                           cache=CacheView(cache(),
                                           mode="refresh" if body.fresh else body.cache_mode,
                                           max_age=body.max_age),
                           profile=body.profile, engines=body.engines)
    rows, stages = ranker.apply(
        rows, body.query, bm25=body.rank or body.ranking == "bm25",
        corpus=body.corpus, recency=body.recency)
    if body.ranking == "fusion":
        rows = ranker.fuse_rows(rows, body.query, recency=body.recency)
        stages.append("rank_fusion")
    if body.prefer_domains:
        rows = fs.rank(rows, body.prefer_domains)
        stages.append("preferred_domains")
    rows = [r for r in rows if constrained(body.query, r)]
    # AFTER ranking, and only here. Relevance order is decided above and is
    # not touched; this moves domains that measurably never yield text to the
    # back of the queue, so the fetches about to be spent land on results that
    # can actually be read. Nothing is dropped -- if the whole pool is poor
    # domains, they are still what comes back.
    ordered = domain_health.order_for_fetching(rows) if isinstance(body, SearchFetchBody) else rows
    if ordered[:limit] != rows[:limit]:
        stages.append("fetchability")
    rows = ordered

    meta = dict(meta, ranking=stages)
    return rows[:limit], meta, limit


@app.post("/search")
def search(body: SearchBody):
    rows, meta, _limit = _ranked(body)
    return [_search_row(r, meta, i) for i, r in enumerate(rows)]


@app.post("/v2/search")
def search_envelope(body: SearchBody):
    rows, meta, _ = _ranked(body)
    return {"results": [_search_row(r, meta, i) for i, r in enumerate(rows)],
            "status": "ok" if rows else "no_results_or_degraded",
            "attempts": _attempts(meta), "elapsed_ms": meta.get("elapsed_ms"),
            "ranking": meta.get("ranking", []), "profile": body.profile}


def _harvest(rows) -> list:
    """(url, row) pairs worth indexing, from API rows."""
    harvested = []
    for row in rows:
        canonical = row.pop("_index_text", row.get("content", ""))
        extraction = row.get("extraction", {})
        if extraction.get("embedded_images") and "## Embedded image:" in canonical:
            canonical = canonical.split("## Embedded image:", 1)[0].rstrip()
        pages = extraction.get("pages", [])
        has_pdf_ocr = any("ocr" in page.get("method", "") for page in pages)
        if has_pdf_ocr and row.get("content_type") == "application/pdf":
            native = []
            for index, page in enumerate(pages):
                if page.get("method") not in {"text", "text+ocr"}:
                    continue
                marker = "## Page " + str(page["page"]) + "\n"
                start = canonical.find(marker)
                if start < 0:
                    continue
                end = (canonical.find("## Page " + str(pages[index + 1]["page"]) + "\n", start)
                       if index + 1 < len(pages) else len(canonical))
                part = canonical[start:end if end >= 0 else len(canonical)]
                native.append(part.split("[OCR reading]", 1)[0].rstrip())
            canonical = "\n\n".join(native)
            has_pdf_ocr = not bool(canonical)
        ocr_derived = extraction.get("ocr_word_confidence") is not None or has_pdf_ocr
        if (row.get("quality") == "ok" and canonical and not ocr_derived
                and row.get("content_status") not in {"navigation_only", "image_content"}):
            harvested.append((row.get("url", ""), dict(row, content=canonical)))
    return harvested


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
                               allow_render=mode != "never" and body.profile != "fast",
                               render_first=mode == "always",
                               raw=want_html, links=want_links,
                               fresh=body.fresh, cache_mode=body.cache_mode,
                               max_age=body.max_age, wait_for=body.wait_for,
                               render_delay=body.render_delay,
                               headed_fallback=body.headed_fallback or body.profile == "thorough",
                               public_only=body.public_only, focus=body.focus,
                               evidence_namespace=body.evidence_namespace,
                               ocr_language=body.ocr_language, ocr_mode=body.ocr_mode,
                               document_mode=body.document_mode,
                               page_start=body.page_start,
                               page_end=body.page_end, row_start=body.row_start,
                               row_end=body.row_end, sheet=body.sheet,
                               max_cell_chars=body.max_cell_chars,
                               recovery=body.recovery))
    # Indexed AFTER the response, not during it. Embedding costs ~250ms a page
    # and the caller should not wait for work they did not ask for.
    # Not indexed when links were kept: the corpus is prose to match
    # against later, and this output has markdown link syntax woven
    # through it. Feeding it in makes every future match slightly worse.
    background.add_task(index_fetched, _harvest(rows))
    return [compact_row(row) for row in rows] if body.response_format == "concise" else rows


def _job_read(body, url):
    mode = _render_mode(body.render)
    row = _extract_row(url, body.max_chars, allow_ocr=True,
                       allow_render=mode != "never" and body.profile != "fast",
                       render_first=mode == "always", raw=body.format == "html" or body.raw,
                       links=body.format == "links" or body.links,
                       fresh=body.fresh, cache_mode=body.cache_mode, max_age=body.max_age,
                       wait_for=body.wait_for, render_delay=body.render_delay,
                       headed_fallback=body.headed_fallback or body.profile == "thorough",
                       public_only=body.public_only, focus=body.focus,
                       evidence_namespace=body.evidence_namespace, ocr_language=body.ocr_language,
                       ocr_mode=body.ocr_mode, document_mode=body.document_mode,
                       page_start=body.page_start, page_end=body.page_end,
                       row_start=body.row_start, row_end=body.row_end, sheet=body.sheet,
                       max_cell_chars=body.max_cell_chars, recovery=body.recovery)
    index_fetched(_harvest([row]))
    return compact_row(row) if body.response_format == "concise" else row


@app.post("/jobs/fetch")
def start_fetch_job(body: FetchJobBody):
    try:
        identifier = jobs().submit(body.evidence_namespace,
                                   body.model_dump(exclude={"operation_id"}), body.operation_id,
                                   lambda url: _job_read(body, url), _FETCH_POOL)
        return jobs().get(body.evidence_namespace, identifier)
    except JobError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@app.post("/jobs/read")
def read_fetch_job(body: JobReadBody):
    try:
        return jobs().get(body.evidence_namespace, body.job_id, body.cursor, body.limit)
    except JobError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@app.post("/jobs/cancel")
def cancel_fetch_job(body: JobReadBody):
    try:
        return jobs().cancel(body.evidence_namespace, body.job_id)
    except JobError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@app.post("/jobs/resume")
def resume_fetch_job(body: JobReadBody):
    def reader(payload):
        payload = dict(payload, evidence_namespace=body.evidence_namespace)
        saved = FetchBody(**payload)
        return lambda url: _job_read(saved, url)
    try:
        return jobs().resume(body.evidence_namespace, body.job_id, reader, _FETCH_POOL)
    except JobError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@app.post("/site/crawl")
def crawl_site(body: SiteBody):
    from .site import crawl
    result = crawl(body.urls, lambda url: _extract_row(
        url, 120000, raw=True, public_only=body.public_only, page_budget=30,
        evidence_namespace=body.evidence_namespace, recovery="manual",
        allow_render=body.render != "never", render_first=body.render == "always"),
        max_pages=body.max_pages, max_depth=body.max_depth, path_prefix=body.path_prefix)
    result["workflow"] = {"next_actions": [
        {"tool": "read_document", "endpoint": "/documents/read",
         "arguments": {"document_id": row["document_id"]},
         "reason": "Inspect retained evidence before synthesizing site findings."}
        for row in result["sources"] if row.get("document_id")][:6]}
    return result


@app.post("/documents/structure")
def document_structure(body: StructureBody):
    from .structure import select
    record = documents().get(body.evidence_namespace, body.document_id)
    if record is None:
        raise HTTPException(404, "document_missing_or_expired")
    return select(record, offset=body.offset, limit=body.limit, focus=body.focus)


def _source_artifact(record, namespace, public_only):
    """Acquire source bytes on demand, verifying the retained source version."""
    metadata = record["metadata"]
    artifact = documents().get_artifact(namespace, metadata.get("artifact_id", ""))
    if artifact is not None:
        return artifact
    expected = (
        metadata.get("file_sha256")
        or metadata.get("source_sha256")
        or metadata.get("extraction", {}).get("source_sha256")
    )
    if not expected:
        raise HTTPException(
            status_code=410, detail="source_bytes_missing_and_no_version_hash; refetch URL"
        )
    captured = []
    fetcher.fetch_and_extract(
        record["url"],
        cache=None,
        max_chars=1,
        allow_ocr=False,
        allow_render=False,
        public_only=public_only,
        ocr_mode="never",
        source_sink=lambda blob, filename: captured.append((blob, filename)),
    )
    if not captured:
        raise HTTPException(
            status_code=410,
            detail="source_bytes_unavailable; capture the source through browser download",
        )
    blob, filename = captured[-1]
    import hashlib

    if hashlib.sha256(blob).hexdigest() != expected:
        raise HTTPException(
            status_code=409, detail="source_version_changed; fetch current source before inspection"
        )
    identifier = documents().put_artifact(namespace, filename, blob)
    metadata["artifact_id"] = identifier
    documents().put(namespace, record["url"], record["text"], metadata)
    return documents().get_artifact(namespace, identifier)


@app.post("/documents/read")
def read_document(body: DocumentReadBody):
    record = documents().get(body.evidence_namespace, body.document_id)
    if record is None:
        raise HTTPException(status_code=404, detail="document_missing_or_expired")
    text = record.pop("text")
    metadata = record.pop("metadata")
    needs_parse = (body.reparse or body.row_start != 1 or body.row_end is not None
                   or body.sheet or body.max_cell_chars is not None or body.page_start != 1
                   or body.page_end is not None or body.ocr_mode != "auto" or body.ocr_language
                   or body.document_mode != "auto")
    if needs_parse:
        from . import formats
        artifact = _source_artifact({**record, "text": text, "metadata": metadata},
                                    body.evidence_namespace, body.public_only)
        try:
            options = body.model_dump()
            kind = formats.kind_of(artifact["data"], artifact["filename"])
            text, extraction = formats.read_blob(artifact["data"], kind, fetcher.CACHE_CHARS,
                allow_ocr=body.ocr_mode != "never", options=options)
            metadata.update(extraction=extraction, warnings=extraction.get("warnings", []),
                            source_partial=extraction.get("partial", False))
            record.update(documents().put(body.evidence_namespace, record["url"], text, metadata))
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = {**metadata, **record, "document_chars": len(text)}
    if body.focus:
        selected, evidence = passage_excerpt(text, body.focus, body.max_chars)
        row.update(content=selected, evidence=evidence, focus=body.focus,
                   focus_status="term_matches" if evidence else "no_term_matches",
                   truncated=len(selected) < len(text), next_offset=None)
    else:
        end = min(len(text), body.offset + body.max_chars)
        row.update(content=text[body.offset:end], offset=body.offset,
                   truncated=end < len(text), next_offset=end if end < len(text) else None)
    row["workflow"] = guidance(row, offset=body.offset, focused=bool(body.focus))
    return compact_row(row) if body.response_format == "concise" else row


@app.post("/documents/image")
def document_image(body: DocumentImageBody):
    import io

    from PIL import Image
    record = documents().get(body.evidence_namespace, body.document_id)
    if record is None:
        raise HTTPException(status_code=404, detail="document_missing_or_expired")
    artifact = _source_artifact(record, body.evidence_namespace, body.public_only)
    from . import formats
    kind = formats.kind_of(artifact["data"], artifact["filename"])
    try:
        if kind == "pdf":
            import pymupdf
            with pymupdf.open(stream=artifact["data"], filetype="pdf") as pdf:
                if body.page > len(pdf):
                    raise ValueError("page_out_of_range")
                page = pdf[body.page - 1]
                if page.rect.width * page.rect.height * (200 / 72) ** 2 > 40_000_000:
                    raise ValueError("image_pixel_limit")
                pix = page.get_pixmap(dpi=200)
                image = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        elif kind == "image":
            image = Image.open(io.BytesIO(artifact["data"]))
            if body.page > getattr(image, "n_frames", 1):
                raise ValueError("page_out_of_range")
            image.seek(body.page - 1)
            if image.width * image.height > 40_000_000:
                raise ValueError("image_pixel_limit")
            image = image.convert("RGB")
        else:
            raise ValueError("image_view_requires_pdf_or_raster_image")
        original_size = image.size
        if image.width * image.height > 40_000_000:
            raise ValueError("image_pixel_limit")
        if body.crop:
            left, top, right, bottom = body.crop
            if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
                raise ValueError("crop_out_of_range")
            image = image.crop(body.crop)
        image.thumbnail((body.max_dimension, body.max_dimension))
        output = io.BytesIO()
        image.save(output, format="PNG")
        if output.tell() > 12_000_000:
            raise ValueError("image_output_too_large; use a crop")
        return {"document_id": body.document_id, "source_sha256": artifact["file_sha256"],
                "page": body.page, "original_size": original_size, "output_size": image.size,
                "crop": body.crop, "mime_type": "image/png",
                "image_b64": base64.b64encode(output.getvalue()).decode()}
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
    if body.operation_id and not body.session:
        raise HTTPException(status_code=422,
                            detail="operation_id requires an explicit named session")
    has_navigation = bool(body.url) or any(
        step.action.lower() == "goto" and bool(step.url) for step in body.steps
    )
    if not body.session:
        if has_navigation:
            # Navigation starts a workflow. Persist it automatically so the
            # caller can inspect or interact with the same page in a later
            # request instead of being handed an unusable null session ID.
            body.session = f"auto-{secrets.token_hex(8)}"
        elif body.steps:
            raise HTTPException(
                status_code=422,
                detail=(
                    "session is required for stateful drive steps; navigate first "
                    "and reuse the returned session.id"
                ),
            )

    payload = body.model_dump(exclude={"evidence_namespace", "ocr_language"})
    try:
        result = fs.browser_drive(payload)
        for step in result.get("steps", []):
            data = step.get("data")
            if (step.get("action") == "network" and step.get("ok")
                    and isinstance(data, dict) and isinstance(data.get("content"), str)):
                metadata = {"quality": "ok", "content_type": data.get("content_type", ""),
                            "http_status": data.get("status"),
                            "source_partial": bool(data.get("truncated")),
                            "acquisition": {"method": "browser_network_response"},
                            "warnings": ["Captured application response; HTTP status and "
                                         "content must be assessed before using its claims."]}
                data.update(documents().put(body.evidence_namespace, data["url"],
                                             data["content"], metadata))
                data["workflow"] = guidance({**metadata, **data})
            if step.get("action") != "download" or not isinstance(data, dict):
                continue
            encoded = data.pop("download_b64", None)
            if encoded is None:
                continue
            from . import formats
            try:
                blob = base64.b64decode(encoded, validate=True)
                data["artifact_id"] = documents().put_artifact(
                    body.evidence_namespace, data.get("filename", "download"), blob)
                data["capture_succeeded"] = True
                data["file_sha256"] = __import__("hashlib").sha256(blob).hexdigest()
                kind = formats.kind_of(blob, data.get("filename", ""))
                if not kind:
                    raise ValueError("unsupported_download_format")
                text, extraction = formats.read_blob(blob, kind, fetcher.CACHE_CHARS,
                    options={"ocr_language": body.ocr_language,
                             "filename": data.get("filename", "download")})
                data.update(content=text, content_type=kind, extraction=extraction,
                            file_sha256=__import__("hashlib").sha256(blob).hexdigest(),
                            warnings=extraction.get("warnings", []))
                data.update(documents().put(body.evidence_namespace,
                    data.get("source_url", result.get("final", {}).get("url", "")), text,
                    {"filename": data.get("filename"), "extraction": extraction,
                     "file_sha256": data["file_sha256"], "artifact_id": data["artifact_id"]}))
                data["workflow"] = guidance(data)
            except Exception as exc:
                if data.get("artifact_id"):
                    data.update(documents().put(body.evidence_namespace,
                        data.get("source_url", result.get("final", {}).get("url", "")), "",
                        {"artifact_id": data["artifact_id"], "file_sha256": data.get("file_sha256"),
                         "filename": data.get("filename"),
                         "warnings": ["File captured; text conversion failed. "
                                      "Inspect PDF/image pixels or retry parsing."]}))
                step.update(ok=False, reason="download_parse_failed:" + str(exc)[:150])
                result["ok"] = False
        return result
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
        # Coverage is the default: selected scanned sources can use OCR.
        # Callers may explicitly disable it when their task does not need it.
        sf_mode = _render_mode(body.render)
        extracted = _extract_row(row.get("url", ""), body.max_chars,
                                 allow_ocr=body.ocr_mode != "never",
                                 ocr_mode=body.ocr_mode, document_mode=body.document_mode,
                                 ocr_language=body.ocr_language,
                                 page_budget=fetcher.PAGE_BUDGET_BULK,
                                 allow_render=sf_mode != "never",
                                 render_first=sf_mode == "always",
                                 raw=body.raw, fresh=body.fresh, cache_mode=body.cache_mode,
                                 max_age=body.max_age, public_only=True,
                                 evidence_namespace=body.evidence_namespace)
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
        if body.categories not in {"", "news", "academic"}:
            raise HTTPException(status_code=422, detail="invalid research category")
        queries = research_engine.queries_for(body.question, body.queries or None)
        def search_one(query):
            try:
                rows, meta, _ = _ranked(SearchBody(
                    query=query, limit=8, language=body.language,
                    fresh=body.fresh, categories=body.categories,
                    profile=body.profile, engines=body.engines))
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
                read_budget = max(body.max_chars, min(fetcher.CACHE_CHARS, 1000000))
                row = _extract_row(item["url"], read_budget,
                                   allow_ocr=True,
                                   page_budget=fetcher.PAGE_BUDGET_BULK,
                                   fresh=body.fresh, public_only=True,
                                   evidence_namespace=body.evidence_namespace, recovery="manual")
            except Exception as exc:
                row = {"url": item["url"], "quality": "failed", "content": "",
                       "failure_reason": type(exc).__name__}
            if body.follow_assets and row.get("content_status") == "image_content":
                asset_attempts = []
                for asset in row.get("assets", [])[:2]:
                    if asset.get("kind") not in {"image", "document"}:
                        continue
                    try:
                        attachment = _extract_row(asset["url"], read_budget, allow_ocr=True,
                            fresh=body.fresh, public_only=True,
                            evidence_namespace=body.evidence_namespace)
                        asset_attempts.append({"url": asset["url"],
                                               "quality": attachment.get("quality")})
                        if attachment.get("quality") == "ok" and attachment.get("content"):
                            attachment.update(parent_url=item["url"], asset_attempts=asset_attempts)
                            row = attachment
                            break
                    except Exception as exc:
                        asset_attempts.append({"url": asset["url"], "error": type(exc).__name__})
                row["asset_attempts"] = asset_attempts
            content = row.get("content", "")
            selected_content, evidence = passage_excerpt(content, body.question, body.max_chars)
            row["content"] = selected_content
            row["full_extraction_chars"] = len(content)
            row["truncated"] = len(content) > len(selected_content)
            return {**item, **row, "requested_url": item["url"],
                    "title": row.get("title") or item["title"],
                    "evidence": evidence}

        sources, skipped, fingerprints = [], [], []
        with ThreadPoolExecutor(max_workers=3) as pool:
            pending = selected[:body.max_sources]
            offset = len(pending)
            while pending:
                for item in pool.map(read, pending):
                    if (item.get("quality") == "ok" and item.get("content")
                            and item.get("content_status") not in {
                                "image_content", "navigation_only"}):
                        fingerprint = research_engine.content_shingles(item["content"])
                        duplicate_of = research_engine.duplicate_source(
                            fingerprint, fingerprints)
                        if duplicate_of:
                            skipped.append({"url": item["url"],
                                            **({"requested_url": item["requested_url"]}
                                               if item.get("requested_url", item["url"])
                                               != item["url"] else {}),
                                            "reason": "duplicate_content",
                                            "duplicate_of": duplicate_of})
                        else:
                            sources.append(item)
                            fingerprints.append((item["url"], fingerprint))
                    else:
                        skipped.append({"url": item["url"],
                                            **({"requested_url": item["requested_url"]}
                                               if item.get("requested_url", item["url"])
                                               != item["url"] else {}),
                                        "reason": item.get("failure_reason")
                                        or (item.get("content_status") if item.get("content_status")
                                            in {"image_content", "navigation_only"}
                                            else "empty_content")})
                if len(sources) >= body.max_sources or offset >= len(selected):
                    break
                pending = selected[offset:offset + body.max_sources - len(sources)]
                offset += len(pending)
        sources = sources[:body.max_sources]
        for index, item in enumerate(sources, 1):
            item["id"] = "S%d" % index
        background.add_task(index_fetched, _harvest(sources))
        coverage = research_engine.coverage_ledger(queries, searches, sources, skipped)
        if body.response_format == "concise":
            sources = [compact_row(row) for row in sources]
        return {"coverage": coverage, "question": body.question, "queries": telemetry,
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
def corpus_search(q: str, limit: int = 10, floor: float | None = None,
                  mode: Literal["auto", "semantic", "lexical"] = "auto"):
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
        hits = shared_corpus().search(q, limit=max(1, min(limit, 50)), floor=floor, mode=mode)
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
