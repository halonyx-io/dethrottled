"""Private, keyless browser search worker for the Dethrottled Compose stack.

One headed Chromium process, at most three active searches and three tabs per
search. Every attempt has an HTTP status or explicit failure reason. The
worker discovers URLs only; Dethrottled validates and reads the documents.
"""
from __future__ import annotations

import asyncio
import base64
import ipaddress
import os
import re
import time
from collections import Counter, deque
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

from fastapi import FastAPI, HTTPException
from patchright.async_api import async_playwright
from pydantic import BaseModel, Field

ENGINES = {
    "ddg-lite": ("https://lite.duckduckgo.com/lite/?q=", "a.result-link", ".result-snippet"),
    "ddg-html": ("https://html.duckduckgo.com/html/?q=", "a.result__a", ".result__snippet"),
    "bing": ("https://www.bing.com/search?q=", "li.b_algo h2 a", "li.b_algo .b_caption p"),
}
ORDER = ("ddg-lite", "ddg-html", "bing")
SEMAPHORE = asyncio.Semaphore(3)
STATE_LOCK = asyncio.Lock()
DDG_LOCK = asyncio.Lock()
MAX_WAITING = 6
QUEUE_TIMEOUT = 8.0
ENGINE_TIMEOUT = 6.0
STAGGER = 0.5
DDG_INTERVAL = 0.5
NEXT_DDG_START = 0.0
ACTIVE = 0
WAITING = 0
STATS = Counter()
LATENCIES = deque(maxlen=200)
FAILURE_MARKERS = (
    "unusual traffic", "verifying you're not a bot", "verify you are human",
    "captcha", "just a moment", "access denied", "automated queries",
)


def _destination(href: str) -> str | None:
    if href.startswith("//"):
        href = "https:" + href
    parts = urlparse(href)
    if parts.hostname in {"duckduckgo.com", "www.duckduckgo.com"} and parts.path == "/l/":
        href = unquote(parse_qs(parts.query).get("uddg", [""])[0])
        parts = urlparse(href)
    if parts.hostname == "www.bing.com" and parts.path.startswith("/ck/"):
        token = parse_qs(parts.query).get("u", [""])[0]
        if token.startswith("a1"):
            try:
                href = base64.urlsafe_b64decode(token[2:] + "====").decode()
                parts = urlparse(href)
            except (ValueError, UnicodeDecodeError):
                return None
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        return None
    if host == "localhost" or host.endswith(".local"):
        return None
    try:
        if not ipaddress.ip_address(host).is_global:
            return None
    except ValueError:
        pass
    if any(host == name or host.endswith("." + name) for name in
           ("duckduckgo.com", "bing.com", "google.com")):
        return None
    return href


def _site(query: str) -> str:
    match = re.search(r"(?:^|\s)site:([\w.-]+)", query, re.I)
    return match.group(1).lower().lstrip(".") if match else ""


def _valid_for_query(url: str, query: str) -> bool:
    site = _site(query)
    host = (urlparse(url).hostname or "").lower()
    return not site or host == site or host.endswith("." + site)


async def _pace_ddg():
    global NEXT_DDG_START
    async with DDG_LOCK:
        now = time.monotonic()
        if NEXT_DDG_START > now:
            await asyncio.sleep(NEXT_DDG_START - now)
        NEXT_DDG_START = time.monotonic() + DDG_INTERVAL


async def _extract(page, engine: str, query: str) -> list[dict]:
    _, selector, snippet_selector = ENGINES[engine]
    links = page.locator(selector)
    snippets = page.locator(snippet_selector)
    snippet_count = await snippets.count()
    rows, seen = [], set()
    for index in range(min(await links.count(), 12)):
        link = links.nth(index)
        title = (await link.inner_text(timeout=500)).strip()
        url = _destination(urljoin(page.url, (await link.get_attribute("href")) or ""))
        if not url or not _valid_for_query(url, query) or len(title) < 10 or url in seen:
            continue
        seen.add(url)
        try:
            snippet = ((await snippets.nth(index).inner_text(timeout=400)).strip()
                       if index < snippet_count else "")
        except Exception:
            snippet = ""
        rows.append({"title": title[:300], "url": url, "snippet": snippet[:600]})
    return rows


def _usable(rows: list[dict]) -> bool:
    return len(rows) >= 3 and sum(len(r["snippet"]) >= 25 for r in rows) >= 2


async def _engine(context, engine: str, query: str, delay: float) -> dict:
    if delay:
        await asyncio.sleep(delay)
    if engine.startswith("ddg"):
        await _pace_ddg()
    page = await context.new_page()
    started = time.monotonic()
    prefix, selector, _ = ENGINES[engine]
    attempt = {"engine": engine, "status": None, "reason": None, "results": []}
    try:
        response = await page.goto(prefix + quote_plus(query),
                                   wait_until="domcontentloaded",
                                   timeout=int(ENGINE_TIMEOUT * 1000))
        attempt["status"] = response.status if response else None
        if attempt["status"] != 200:
            attempt["reason"] = "http_" + str(attempt["status"])
            return attempt
        if "/sorry/" in page.url or "/captcha" in page.url:
            attempt["reason"] = "challenge_page"
            return attempt
        deadline = started + ENGINE_TIMEOUT
        while time.monotonic() < deadline:
            if await page.locator(selector).count() >= 3:
                attempt["results"] = await asyncio.wait_for(
                    _extract(page, engine, query), timeout=2.0)
                if _usable(attempt["results"]):
                    return attempt
            if time.monotonic() - started > 0.7:
                try:
                    body = (await page.locator("body").inner_text(timeout=500))[:1200].lower()
                except Exception:
                    body = ""
                if any(marker in body for marker in FAILURE_MARKERS):
                    attempt["reason"] = "challenge_page"
                    return attempt
            await asyncio.sleep(0.2)
        attempt["reason"] = "thin_or_unrelated_results"
    except asyncio.CancelledError:
        attempt["reason"] = "cancelled"
        raise
    except Exception as exc:
        attempt["reason"] = type(exc).__name__ + ": " + str(exc)[:100]
    finally:
        attempt["elapsed_s"] = round(time.monotonic() - started, 3)
        try:
            await asyncio.wait_for(page.close(), timeout=2.0)
        except Exception:
            pass
    return attempt


async def _race(browser, query: str) -> dict:
    started = time.monotonic()
    context = await browser.new_context()
    pending = {asyncio.create_task(_engine(context, engine, query, i * STAGGER)): engine
               for i, engine in enumerate(ORDER)}
    attempts, winner = [], None
    try:
        while pending and time.monotonic() - started < ENGINE_TIMEOUT + 2:
            done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED,
                                         timeout=max(0.1, ENGINE_TIMEOUT + 2 - (time.monotonic() - started)))
            if not done:
                break
            for task in done:
                engine = pending.pop(task)
                try:
                    attempt = task.result()
                except Exception as exc:
                    attempt = {"engine":engine,"status":None,
                               "reason":type(exc).__name__,"results":[]}
                attempts.append({k:v for k,v in attempt.items() if k != "results"} |
                                {"count":len(attempt["results"])})
                if winner is None and _usable(attempt["results"]):
                    winner = attempt
            if winner:
                break
    finally:
        cancelled = list(pending.values())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        attempts.extend({"engine": engine, "status": None,
                         "reason": "cancelled_by_winner" if winner else "race_timeout",
                         "count": 0} for engine in cancelled)
        await context.close()
    return {"ok":winner is not None,
            "engine":winner["engine"] if winner else None,
            "results":winner["results"] if winner else [],
            "attempts":attempts,
            "service_s":round(time.monotonic()-started,3)}


async def _watch_browser(app):
    while True:
        await asyncio.sleep(3)
        if not app.state.browser.is_connected():
            os._exit(1)  # Compose restart policy restores the worker.


@asynccontextmanager
async def lifespan(app):
    async with async_playwright() as playwright:
        app.state.browser = await playwright.chromium.launch(headless=False)
        watcher = asyncio.create_task(_watch_browser(app))
        try:
            yield
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
            await app.state.browser.close()


app = FastAPI(title="Dethrottled browser search worker", lifespan=lifespan)


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)


@app.get("/health")
async def health():
    if not app.state.browser.is_connected():
        raise HTTPException(503, "browser disconnected")
    return {"ok":True,"active":ACTIVE,"waiting":WAITING}


@app.get("/metrics")
async def metrics():
    return {"active":ACTIVE,"waiting":WAITING,"max_active":3,
            "max_waiting":MAX_WAITING,"counts":dict(STATS),
            "recent_latency_s":list(LATENCIES)}


@app.post("/search")
async def search(body: SearchRequest):
    global ACTIVE, WAITING
    query = body.query.strip()
    if len(query) < 2:
        raise HTTPException(422, "empty query")
    queued = time.monotonic()
    async with STATE_LOCK:
        if WAITING >= MAX_WAITING:
            STATS["queue_rejected"] += 1
            raise HTTPException(429, "browser search queue full")
        WAITING += 1
    try:
        await asyncio.wait_for(SEMAPHORE.acquire(), timeout=QUEUE_TIMEOUT)
    except TimeoutError:
        STATS["queue_timeout"] += 1
        raise HTTPException(429, "browser search queue timeout") from None
    finally:
        async with STATE_LOCK:
            WAITING -= 1
    async with STATE_LOCK:
        ACTIVE += 1
    try:
        result = await _race(app.state.browser, query)
        result["queue_s"] = round(time.monotonic() - queued - result["service_s"], 3)
        STATS["requests"] += 1
        if result["ok"]:
            STATS["success"] += 1
            STATS["winner_"+result["engine"]] += 1
        else:
            STATS["no_usable_engine"] += 1
        for attempt in result["attempts"]:
            if attempt.get("reason"):
                STATS["failure_"+str(attempt["reason"]).split(":",1)[0]] += 1
        LATENCIES.append(result["service_s"])
        if not result["ok"]:
            raise HTTPException(503, detail={"reason":"no_usable_engine",
                                             "attempts":result["attempts"]})
        return result
    finally:
        async with STATE_LOCK:
            ACTIVE -= 1
        SEMAPHORE.release()
