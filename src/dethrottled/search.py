#!/usr/bin/env python3
"""Keyless discovery through a private browser worker, news RSS, and SearXNG.

SearXNG's scraped general-web engines can silently return unrelated results.
The browser worker handles general web discovery with direct DDGS as fallback.
Google News RSS supplies headlines only; a bounded Bing News lookup must
resolve each headline to a publisher URL before it can enter the result pool.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse

import feedparser
import requests

from . import paths as _paths
from .fetch import USER_AGENT, canonical_url

# Empty by default: a SearXNG instance is something you host, and pointing at
# somebody else's public one is both rude and unreliable. Unset, the two RSS
# sources carry the search on their own.
SEARXNG_URL = os.environ.get("DETHROTTLED_SEARXNG_URL", "").rstrip("/")

# In October 2026, local SearXNG Bing returned unrelated Outlook, Vietnam-food
# and Malaysian employer-login results for unrelated queries. Yahoo returned
# protocol errors. Keep the news engines; direct DDGS handles general web.
# Free engines still rot, so failures are logged and rested.
# Engines that have just refused us, and when. Persisted, because the process
# that learns an engine is blocked is usually not the one that pays for asking
# it next.
_HEALTH_TTL = int(os.environ.get("DETHROTTLED_ENGINE_REST_SECONDS", "1800"))
_DEAD_ENGINES = {}


def _health_path():
    return Path(os.environ.get(
        "DETHROTTLED_ENGINE_HEALTH",
        _paths.data_dir() / "engine-health.json"))


# Engine health is read, modified and written back, from request threads.
#
# FastAPI runs a sync route in a threadpool, so this file is touched
# concurrently in production and was doing so unsynchronised. Measured under 32
# threads recording 1,280 failures: the final count was ZERO. Not merely lost
# updates -- `write_text` truncates before it writes, so a reader landing
# mid-write got invalid JSON, fell back to an empty dict, and wrote that empty
# dict back over everything.
#
# The lock serialises the read-modify-write; the temp-file rename makes every
# write atomic, so a reader sees either the old file or the new one and never
# half of either.
_health_lock = threading.Lock()


def _load_health() -> dict:
    try:
        return json.loads(_health_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_health(health: dict) -> None:
    try:
        path = _health_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(health, indent=1, sort_keys=True),
                       encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def _rested(engines: str, *, namespace: str = "") -> str:
    """The configured engines, minus any that refused us recently.

    Rested rather than removed. Rate limits and CAPTCHAs lift, so an engine is
    skipped for half an hour and then tried again; a permanently dead one just
    fails again and is rested again, which costs one request every half hour
    rather than one per search.
    """
    health, now = _load_health(), time.time()
    wanted = [e.strip() for e in engines.split(",") if e.strip()]
    if not wanted:
        return ""

    def last_failure(engine):
        key = f"{namespace}:{engine}" if namespace else engine
        return float((health.get(key) or {}).get("at", 0))

    alive = [e for e in wanted
             if now - last_failure(e) > _HEALTH_TTL]
    # Never rest the last one standing: a wrong health record must not be able
    # to turn every search into an empty result. If all are rested, retry only
    # the one whose failure is oldest; retrying ALL of them defeats resting.
    return ",".join(alive or [min(wanted, key=last_failure)])


def _record_failure(name: str, reason: str, *, namespace: str = "") -> None:
    """Note that an engine refused us. Held under the lock end to end, because
    read-then-write is only safe if nothing can interleave between the two."""
    with _health_lock:
        health = _load_health()
        key = f"{namespace}:{name}" if namespace else name
        health[key] = {"at": time.time(), "reason": str(reason)[:80],
                       "fails": int((health.get(key) or {}).get("fails", 0)) + 1}
        _save_health(health)


DEFAULT_ENGINES = os.environ.get(
    "DETHROTTLED_SEARXNG_ENGINES",
    "duckduckgo news,bing news")

# Engine families, for a bundle that wants more than the default web and news.
# A scientific or technical subject gets far more from crossref and openalex
# than from another news aggregator; a market question gets nothing from either.
ENGINE_GROUPS = {
    "web": "bing,yahoo",
    "news": "google news,bing news,duckduckgo news,reuters",
    "academic": "arxiv,crossref,openalex,semantic scholar",
}

GOOGLE_NEWS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
BING_NEWS = "https://www.bing.com/news/search?q={q}&format=RSS"

MAX_GNEWS_RESOLUTIONS = int(os.environ.get("DETHROTTLED_GNEWS_RESOLVE", "3"))
# A cap on *attempts*, not successes. If Bing cannot resolve any headline,
# success-only accounting otherwise issues one lookup for every Google result.
MAX_GNEWS_LOOKUPS = int(os.environ.get("DETHROTTLED_GNEWS_LOOKUPS", "4"))

_GN_SUFFIX = re.compile(r"\s+-\s+[^-]{2,40}$")
_TAGS = re.compile(r"<[^>]+>")

# Browser-ish UA for the news RSS endpoints specifically; both serve degraded
# or empty feeds to obviously-automated agents. Article fetching still uses the
# identifiable USER_AGENT from fetch.py.
RSS_UA = ("Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/128.0 Safari/537.36")


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _norm(**kw) -> dict:
    url = kw.get("url", "")
    return {
        "title": kw.get("title", ""),
        "url": url,
        "snippet": kw.get("snippet", ""),
        "content": kw.get("content", ""),
        "publishedDate": kw.get("published", ""),
        "engine": kw.get("engine", ""),
        "source": kw.get("source") or _domain(url),
    }


def _unwrap_bing(link: str) -> str:
    """Recover the publisher URL from a Bing News apiclick redirector."""
    try:
        params = parse_qs(urlparse(link).query)
        target = (params.get("url") or [""])[0]
        if target.startswith("http"):
            return target
    except Exception:
        pass
    return link


def searxng(query: str, *, max_items: int = 8, categories: str = "",
            engines: str = "", timeout: int = 40, cache=None,
            language=None) -> list:
    if not SEARXNG_URL:
        return []
    engines = _rested(engines or DEFAULT_ENGINES, namespace="searxng")
    if cache is not None:
        hit = cache.get("search", "sx", query, engines, categories, max_items,
                        language)
        if hit is not None:
            return hit

    params = {"q": query, "format": "json", "engines": engines}
    if categories:
        params["categories"] = categories
    # Worth as much as translating the query. A French query without it returns
    # 66 rows and 28 useful; with it, 108 and 57, and twice as many of them on
    # Moroccan domains.
    if language:
        params["language"] = language

    rows = []
    try:
        response = requests.get(SEARXNG_URL + "/search", params=params,
                                timeout=timeout, headers={"User-Agent": USER_AGENT})
        if response.status_code == 200:
            payload = response.json()
            # Free engines block self-hosted instances routinely, and SearXNG
            # answers 200 with fewer results rather than failing. That is how
            # DuckDuckGo went from half this pool to nothing without anybody
            # noticing. Reported once per engine per process, because it is a
            # standing condition rather than an event.
            for entry in (payload.get("unresponsive_engines") or []):
                name = entry[0] if entry else "?"
                reason = entry[1] if len(entry) > 1 else "unresponsive"
                _record_failure(name, reason, namespace="searxng")
                if name not in _DEAD_ENGINES:
                    _DEAD_ENGINES[name] = reason
                    print("  [dethrottled] engine %r is not answering: %s "
                          "(resting it for %d min)"
                          % (name, reason, _HEALTH_TTL // 60), flush=True)
            for item in (payload.get("results") or [])[:max_items]:
                if item.get("url"):
                    rows.append(_norm(
                        title=item.get("title", ""), url=item["url"],
                        snippet=item.get("content", ""),
                        published=item.get("publishedDate") or "",
                        engine=item.get("engine", "searxng")))
    except Exception:
        rows = []

    if cache is not None and rows:
        cache.put("search", "sx", query, engines, categories, max_items,
                  language, value=rows)
    return rows


def bing_news(query: str, *, max_items: int = 8, timeout: int = 25, cache=None) -> list:
    if cache is not None:
        hit = cache.get("search", "bnews", query, max_items)
        if hit is not None:
            return hit
    rows = []
    try:
        response = requests.get(BING_NEWS.format(q=quote_plus(query)),
                                timeout=timeout, headers={"User-Agent": RSS_UA})
        if response.status_code == 200:
            for entry in feedparser.parse(response.content).entries[:max_items]:
                url = _unwrap_bing(entry.get("link", ""))
                title = entry.get("title", "")
                if not url or not title or "bing.com" in _domain(url):
                    continue
                rows.append(_norm(
                    title=title, url=url,
                    snippet=_TAGS.sub(" ", entry.get("summary", ""))[:600],
                    published=entry.get("published", ""), engine="bing-news"))
    except Exception:
        rows = []
    if cache is not None and rows:
        cache.put("search", "bnews", query, max_items, value=rows)
    return rows


def google_news_headlines(query: str, *, max_items: int = 8, timeout: int = 25,
                          cache=None) -> list:
    """Headlines only. Links are unusable; see the module docstring."""
    if cache is not None:
        hit = cache.get("search", "gnews", query, max_items)
        if hit is not None:
            return hit
    rows = []
    try:
        response = requests.get(GOOGLE_NEWS.format(q=quote_plus(query)),
                                timeout=timeout, headers={"User-Agent": RSS_UA})
        if response.status_code == 200:
            for entry in feedparser.parse(response.content).entries[:max_items]:
                title = entry.get("title", "")
                if not title:
                    continue
                publisher = (entry.get("source", {}) or {}).get("title", "")
                match = _GN_SUFFIX.search(title)
                if match and not publisher:
                    publisher = match.group(0).lstrip(" -").strip()
                title = _GN_SUFFIX.sub("", title).strip()
                rows.append({"title": title, "publisher": publisher,
                             "published": entry.get("published", "")})
    except Exception:
        rows = []
    if cache is not None and rows:
        cache.put("search", "gnews", query, max_items, value=rows)
    return rows


def _title_key(text: str) -> str:
    words = [w for w in re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).split()
             if len(w) > 2]
    return " ".join(words[:8])


# Domains the free sources surface constantly that carry no supply-chain
# information: portfolio aggregators, stock-tip mills, and outright accidents
# (incometax.gov.in matched an early run on generic vocabulary alone).
JUNK_DOMAINS = {
    "incometax.gov.in", "247wallst.com", "fool.com", "investorplace.com",
    "zacks.com", "benzinga.com", "marketbeat.com", "tipranks.com",
    "simplywall.st", "stocktwits.com", "insidermonkey.com", "gurufocus.com",
    "barchart.com", "investing.com", "tradingview.com",
}


def rank(rows: list, prefer: set | None = None) -> list:
    """Order results so good publishers survive truncation.

    Free sources skew hard toward syndication: one measured pool came back 52
    secondary to 4 reputable, dominated by a single financial-news aggregator
    mirroring everyone else. That matters whenever you care WHO said something
    rather than merely that it was said -- an aggregator-heavy pool is a pool
    of echoes, and an echo cannot be cited.

    Ranking here is a cheap counterweight: preferred domains first, junk last,
    original order preserved within each band. Both lists are yours to supply;
    see JUNK_DOMAINS for the only opinion shipped by default, and why.
    """
    prefer = {d.lower() for d in (prefer or set())}

    def band(row):
        domain = _domain(row.get("url", ""))
        if domain in JUNK_DOMAINS:
            return 2
        if domain in prefer or any(domain.endswith("." + p) for p in prefer):
            return 0
        return 1

    return [row for _b, row in sorted(
        ((band(r), r) for r in rows), key=lambda pair: pair[0])]


# How many reputable domains to sweep when the pool comes back thin, and the
# share below which the sweep fires. Kept small on purpose: every sweep query
# is another hit on scraped SERP engines, and those CAPTCHA out under load.
SWEEP_DOMAINS = int(os.environ.get("DETHROTTLED_SWEEP_DOMAINS", "4"))
SWEEP_THRESHOLD = float(os.environ.get("DETHROTTLED_SWEEP_THRESHOLD", "0.35"))


def reputable_sweep(query: str, domains: list, *, max_per_domain: int = 3,
                    cache=None) -> list:
    """Ask specific trusted publishers directly, with `site:` scoping.

    This exists because of a measured failure, not a hunch. Free sources find
    the right stories but usually surface them through syndication, so a pool
    that looks healthy by row count can contain almost nothing citable.

    Fixing the attribution instead was tried first and does not work: of eight
    blocked syndicator pages, ZERO declared a canonical URL pointing back at
    the original. They self-canonicalise and present the content as their own,
    so there is nothing to follow.

    So the pool has to change rather than the labelling. `site:`-scoped SearXNG
    queries against known-good publishers returned 18 on-target results where
    Bing News RSS managed 3.
    """
    rows = []
    for domain in domains[:SWEEP_DOMAINS]:
        try:
            found = searxng("%s site:%s" % (query, domain),
                            max_items=max_per_domain, cache=cache)
        except Exception:
            continue
        for row in found:
            # site: is a hint, not a guarantee -- engines honour it loosely.
            if _domain(row.get("url", "")).endswith(domain):
                rows.append(row)
    return rows


# ── general web search ───────────────────────────────────────────────────────
#
# Added because the original three sources were two news feeds and an optional
# SearXNG, which means a reference question ("okapi bm25 ranking function")
# returned whatever a news site happened to publish about the subject. A news
# feed is a bad way to answer a question that is not news.
#
# `ddgs` bundles scrapers for a dozen engines behind one pure-Python dependency
# (no wheels to build, so a Raspberry Pi installs it as fast as a laptop). Not
# all of them work. Measured over 12 queries from one residential-class IP:
#
#     engine       results  median ms  unique domains  answered  failures
#     bing              72       3057              20      9/12         3
#     google            48        325              24      6/12         6
#     duckduckgo        32         96              13      4/12         8
#     brave             32        246               6      4/12         8
#     startpage         16       1359               7      2/12        10
#     mojeek/yahoo/wiki  0          -               0      0/12        12
#
# mojeek, yahoo and wikipedia failed EVERY query, and still failed with a four
# second gap between requests -- so those are hard blocks, not rate limits, and
# no amount of politeness recovers them. They are not in the default list.
#
# duckduckgo and bing are the two that answer reliably, and duckduckgo at 96ms
# is by a distance the fastest source in the whole stack. The rest are left
# available but off, because an engine that fails two queries in three costs a
# timeout every time it is asked.
WEB_ENGINES = [e.strip() for e in os.environ.get(
    "DETHROTTLED_WEB_ENGINES", "google,auto").split(",") if e.strip()]

WEB_TIMEOUT = int(os.environ.get("DETHROTTLED_WEB_TIMEOUT", "20"))
BROWSER_SEARCH_URL = os.environ.get("DETHROTTLED_BROWSER_SEARCH_URL", "").rstrip("/")
DRIVE_SESSION_TTL = int(os.environ.get("DETHROTTLED_DRIVE_SESSION_TTL", "1800"))
DRIVE_MAX_SESSIONS = int(os.environ.get("DETHROTTLED_DRIVE_MAX_SESSIONS", "8"))

# The actions the private browser worker will perform. The worker is the
# enforcer and owns the same list in its service.py; this copy exists so the
# API can advertise the capability without a live round-trip to a status route.
# A caller reading /v2/capabilities gets the truth whether or not the worker is
# answering at that instant.
DRIVE_ACTIONS = (
    "goto", "click", "fill", "type", "press", "select", "check", "uncheck", "hover",
    "wait", "wait_for", "text", "html", "attr", "count", "snapshot", "url", "title",
)


class BrowserWorkerError(RuntimeError):
    """The private browser worker refused or could not be reached.

    Carries the worker's own HTTP status so the API can pass a 4xx back to the
    caller unchanged instead of laundering every worker refusal into a 502.
    """

    def __init__(self, status: int | None, detail):
        self.status = status
        self.detail = detail if detail is not None else "browser worker error"
        super().__init__("browser worker refused (%s): %s" % (status, self.detail))
# The three discovery sources wait on unrelated network services. Reuse a
# bounded pool across API requests instead of creating three new threads per
# call; consume futures in the original source order to preserve ranking and
# deduplication semantics.
_SOURCE_POOL = ThreadPoolExecutor(max_workers=12, thread_name_prefix="search-source")


def browser_search(query: str, *, max_items: int = 8, cache=None,
                   diagnostics: dict | None = None) -> list:
    """Use the private Compose browser worker for validated web discovery.

    A failed, overloaded, or absent worker returns no rows so the existing
    keyless DDGS path can carry the request. Document reading remains in the
    normal Dethrottled fetch pipeline.
    """
    if not BROWSER_SEARCH_URL:
        if diagnostics is not None:
            diagnostics.update(status="not_configured", attempts=[])
        return []
    if cache is not None:
        hit = cache.get("search", "browser", query, max_items)
        if hit is not None:
            if diagnostics is not None:
                diagnostics.update(status="cached", attempts=[])
            return hit
    try:
        response = requests.post(BROWSER_SEARCH_URL + "/search",
                                 json={"query": query}, timeout=11)
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("browser response is not an object")
        detail = payload.get("detail") if isinstance(payload.get("detail"), dict) else {}
        if diagnostics is not None:
            diagnostics.update(status="ok" if response.ok else "http_" + str(response.status_code),
                               attempts=payload.get("attempts") or detail.get("attempts") or [],
                               elapsed_ms=int(1000 * float(payload.get("service_s") or 0)))
        response.raise_for_status()
        if not payload.get("ok"):
            return []
        rows = []
        for item in payload.get("results", [])[:max_items]:
            url = str(item.get("url") or "")
            parsed = urlparse(url)
            title = str(item.get("title") or "").strip()
            snippet = str(item.get("snippet") or "").strip()
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                continue
            if len(title) < 10 or len(snippet) < 25:
                continue
            rows.append(_norm(title=title, url=url, snippet=snippet,
                              engine="web-browser-" + str(payload.get("engine") or "unknown")))
        if cache is not None and rows:
            cache.put("search", "browser", query, max_items, value=rows)
        return rows
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        if diagnostics is not None and "status" not in diagnostics:
            diagnostics.update(status=type(exc).__name__, attempts=[])
        return []


def browser_drive(payload: dict, *, timeout: int | None = None) -> dict:
    """Drive the private browser worker: navigate, click, fill, read.

    The worker owns the one warm, headed, stealth browser. This hands a bounded
    scripted sequence to it and returns the worker's own step-by-step report.

    Deliberately different from browser_search(): that path treats the worker
    as an optional discovery source and degrades to no rows when it is absent.
    This one is a request to *do work*, so an absent or failing worker is a
    raised error, not an empty result. A caller asking a browser to click
    something must never be told "ok, nothing happened".
    """
    if not BROWSER_SEARCH_URL:
        raise BrowserWorkerError(None, "browser worker not configured "
                                 "(DETHROTTLED_BROWSER_SEARCH_URL is unset)")
    try:
        if timeout is None:
            timeout = max(90, int(payload.get("timeout_ms", 45000) / 1000) + 15)
        response = requests.post(BROWSER_SEARCH_URL + "/drive",
                                 json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise BrowserWorkerError(None, "browser worker unreachable: %s" % exc) from exc
    if response.status_code >= 400:
        detail = None
        try:
            body = response.json()
            detail = body.get("detail") if isinstance(body, dict) else body
        except ValueError:
            detail = response.text[:300]
        raise BrowserWorkerError(response.status_code, detail)
    out = response.json()
    if not isinstance(out, dict):
        raise BrowserWorkerError(None, "browser worker response is not an object")
    return out


def web_search(query: str, *, max_items: int = 8, cache=None,
               engines=None, diagnostics: dict | None = None) -> list:
    """General web results, keyless, via whichever engines still answer.

    Each engine is rested by the same health machinery the SearXNG engines
    use: one that refuses is skipped for half an hour and then retried, so a
    block costs one request per engine per half hour rather than one per
    search.

    Never fatal. `ddgs` is an optional dependency; without it this returns
    nothing and the RSS sources carry the search exactly as they did before.
    """
    # Explicit engine selections keep their old meaning for callers that
    # benchmark or request particular DDGS backends.
    if engines is None:
        found = browser_search(query, max_items=max_items, cache=cache,
                               diagnostics=diagnostics)
        if found:
            return found
    try:
        from ddgs import DDGS
    except ImportError:
        return []

    wanted = engines or WEB_ENGINES
    alive = [e for e in wanted if e in _rested(",".join(wanted), namespace="web").split(",")]
    rows = []
    for engine in alive:
        if cache is not None:
            hit = cache.get("search", "web", engine, query, max_items)
            if hit is not None:
                rows.extend(hit)
                continue
        try:
            found = DDGS().text(query, backend=engine, max_results=max_items)
        except Exception as exc:
            _record_failure(engine, type(exc).__name__, namespace="web")
            continue
        got = []
        for row in found or []:
            url = row.get("href") or row.get("url") or ""
            if not url:
                continue
            got.append({
                "url": url,
                "title": (row.get("title") or "").strip(),
                "snippet": (row.get("body") or row.get("description") or "").strip(),
                "publishedDate": row.get("date") or "",
                "engine": "web-%s" % engine,
            })
        if cache is not None and got:
            cache.put("search", "web", engine, query, max_items, value=got)
        rows.extend(got)
    return rows


def _blend_news(rows: list) -> list:
    """Give explicit news searches web context and two independent news slots.

    Browser web results otherwise fill the whole short result window before
    the news sources are reached. Preserve each source's ranking and the full
    result pool; only interleave their existing rows. If a source is empty,
    the other sources fill its slots.
    """
    web, bing, other_news = deque(), deque(), deque()
    for row in rows:
        engine = row.get("engine", "")
        if engine.startswith("web-"):
            web.append(row)
        elif engine == "bing-news":
            bing.append(row)
        else:
            other_news.append(row)
    mixed = []
    while web or bing or other_news:
        for source in (web, bing, other_news):
            if source:
                mixed.append(source.popleft())
    return mixed


def search(query: str, *, max_items: int = 8, categories: str = "",
           cache=None, log_fn=None, prefer_domains=None, language=None) -> tuple:
    """Query every free source and merge. Returns (rows, meta)."""
    started = time.time()
    seen, seen_titles, merged, per_source = set(), set(), [], {}

    def add(rows, tag):
        added = 0
        for row in rows:
            url = row.get("url", "")
            # Canonical, so one article is one row whatever query string or
            # mobile host it arrived under.
            key = canonical_url(url)
            if not key or key in seen:
                continue

            # And one story is one row however many sites carried it. A live
            # run returned a Reuters wire piece from Channel News Asia, Yahoo
            # Finance and US News: three real URLs, one article. The length
            # guard is why "Home" and "News" do not collapse unrelated sites --
            # they reduce to a single short word.
            title = _title_key(row.get("title", ""))
            if len(title) >= 25:
                if title in seen_titles:
                    continue
                seen_titles.add(title)

            seen.add(key)
            merged.append(row)
            added += 1
        per_source[tag] = per_source.get(tag, 0) + added

    browser_diagnostics = {}
    web_future = _SOURCE_POOL.submit(
        web_search, query, max_items=max_items, cache=cache,
        diagnostics=browser_diagnostics)
    bing_future = _SOURCE_POOL.submit(
        bing_news, query, max_items=max_items, cache=cache)
    searx_future = _SOURCE_POOL.submit(
        searxng, query, max_items=max_items * 2, categories=categories,
        cache=cache, language=language)
    add(web_future.result(), "web")
    add(bing_future.result(), "bing-news")
    add(searx_future.result(), "searxng")

    # Google News is discovery only: resolve a bounded number of headlines it
    # surfaced that nothing else did, then drop the rest rather than emit URLs
    # that cannot be fetched.
    # search() returns at most 2*max_items rows. With a full, non-junk pool
    # and no preferred domains, Google News can only append rows beyond that
    # return window. Avoid a headline fetch and up to four Bing resolutions
    # that no caller could see. Keep the path for thin or preference-ranked
    # pools, where it can genuinely add coverage.
    usable_count = sum(_domain(r.get("url", "")) not in JUNK_DOMAINS for r in merged)
    if usable_count >= max_items * 2 and not prefer_domains:
        per_source["gnews-resolved"] = "skipped_full_pool"
    else:
        resolved, looked_up = 0, 0
        known = {_title_key(r.get("title", "")) for r in merged}
        for headline in google_news_headlines(query, max_items=max_items, cache=cache):
            if resolved >= MAX_GNEWS_RESOLUTIONS or looked_up >= MAX_GNEWS_LOOKUPS:
                break
            key = _title_key(headline["title"])
            if not key or key in known:
                continue
            looked_up += 1
            found = bing_news(headline["title"], max_items=2, cache=cache)
            if found:
                add(found[:1], "gnews-resolved")
                known.add(key)
                resolved += 1

    merged = [r for r in merged if _domain(r.get("url", "")) not in JUNK_DOMAINS]

    # Self-tuning: only sweep when the pool is actually short of trusted
    # publishers, so a healthy query costs nothing extra and a thin one gets
    # help. Rotating the domain list by query keeps one publisher from
    # absorbing every sweep across a run.
    swept = 0
    prefer = sorted({str(d).lower() for d in (prefer_domains or [])})
    if prefer and merged:
        strong = sum(1 for r in merged
                     if any(_domain(r.get("url", "")).endswith(p) for p in prefer))
        if (strong / len(merged)) < SWEEP_THRESHOLD:
            offset = abs(hash(query)) % len(prefer)
            rotated = prefer[offset:] + prefer[:offset]
            for row in reputable_sweep(query, rotated, cache=cache):
                key = row.get("url", "").split("?")[0].rstrip("/")
                if key and key not in seen:
                    seen.add(key)
                    merged.append(row)
                    swept += 1
            per_source["reputable-sweep"] = swept

    merged = rank(merged, prefer_domains)
    if categories.strip().lower() == "news":
        merged = _blend_news(merged)
    dropped = 0

    meta = {
        "ok": bool(merged),
        "count": len(merged),
        # Recorded rather than omitted. A source that is switched off and a
        # source that answered with nothing are identical in a count of zero,
        # and a caller reading this to decide whether an empty result is
        # trustworthy needs to tell those apart.
        "per_source": (per_source if SEARXNG_URL
                       else dict(per_source, searxng="not_configured")),
        "browser_search": browser_diagnostics,
        "junk_dropped": dropped,
        "swept": swept,
        "elapsed_ms": int((time.time() - started) * 1000),
        "cost": "free",
    }
    if log_fn:
        log_fn("    free-search '%s': %d results %s"
               % (query[:44], len(merged), per_source))
    return merged[: max_items * 2], meta


# A probe query, not a real one. It must return results every day of the year
# in every locale, or a healthy stack reports itself down in a quiet week.
PROBE_QUERY = os.environ.get("DETHROTTLED_PROBE_QUERY", "technology")


def health(timeout: int = 20) -> dict:
    report = {"ok": False, "searxng": False, "bing_news": False,
              "searxng_configured": bool(SEARXNG_URL), "detail": ""}
    if not SEARXNG_URL:
        report["detail"] = "searxng not configured; "
    try:
        if not SEARXNG_URL:
            raise RuntimeError("not configured")
        response = requests.get(
            SEARXNG_URL + "/search",
            params={"q": PROBE_QUERY, "format": "json",
                    "engines": DEFAULT_ENGINES},
            timeout=timeout, headers={"User-Agent": USER_AGENT})
        report["searxng"] = response.status_code == 200 and bool(
            response.json().get("results"))
    except Exception as exc:
        # += rather than =: an unconfigured SearXNG has already said so, and
        # overwriting that with "unreachable" reports a missing setting as a
        # broken service, which sends you looking in the wrong place.
        if SEARXNG_URL:
            report["detail"] += "searxng unreachable (%s); " % type(exc).__name__

    try:
        report["bing_news"] = bool(bing_news(PROBE_QUERY, max_items=2,
                                             timeout=timeout))
    except Exception:
        pass

    report["ok"] = report["searxng"] or report["bing_news"]
    report["detail"] += "searxng=%s bing-news=%s (no API keys, no quotas)" % (
        report["searxng"], report["bing_news"])
    return report
