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
from typing import Literal
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

from fastapi import FastAPI, HTTPException
from patchright.async_api import async_playwright
from pydantic import BaseModel, ConfigDict, Field

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
            remaining = max(0.1, ENGINE_TIMEOUT + 2 - (time.monotonic() - started))
            done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED,
                                         timeout=remaining)
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
        session_reaper = asyncio.create_task(_reap_drive_sessions())
        try:
            yield
        finally:
            watcher.cancel()
            session_reaper.cancel()
            await asyncio.gather(watcher, session_reaper, return_exceptions=True)
            await _close_all_drive_sessions()
            await app.state.browser.close()


app = FastAPI(title="Dethrottled browser search worker", lifespan=lifespan)


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)


# ---------------------------------------------------------------------------
# /drive - scripted control of the same warm, headed browser
#
# The search worker discovers URLs. This drives the browser that already lives
# here: navigate, click, fill, wait, read, screenshot. It exists so a caller
# that has to *interact* with a page can ask over HTTP instead of reaching
# around the container to launch Playwright itself -- which means the display,
# the browser build, and the headed/stealth configuration stay in one place
# instead of being rediscovered (and mis-set) by every caller.
#
# Deliberately NOT a general remote-control surface. A closed set of actions, a
# hard step ceiling, a wall-clock deadline, its own concurrency gate, and every
# step's outcome reported. A step that fails says why and stops the run; it
# never silently continues and never reports success it did not observe.
# ---------------------------------------------------------------------------
DRIVE_SEMAPHORE = asyncio.Semaphore(2)
DRIVE_QUEUE_TIMEOUT = 10.0
MAX_STEPS = 40
MAX_DRIVE_SESSIONS = int(os.environ.get("DETHROTTLED_DRIVE_MAX_SESSIONS", "8"))
DRIVE_SESSION_TTL = int(os.environ.get("DETHROTTLED_DRIVE_SESSION_TTL", "1800"))
DRIVE_SESSIONS: dict[str, dict] = {}
DRIVE_SESSIONS_LOCK = asyncio.Lock()

# Actions this worker will perform, and nothing else.
DRIVE_ACTIONS = (
    "goto", "click", "fill", "type", "press", "select", "check", "uncheck", "hover",
    "wait", "wait_for", "text", "html", "attr", "count", "snapshot", "url", "title",
)
SCREENSHOT_MODES = ("never", "failure", "canary", "always")
INTERACTIVE_SELECTOR = (
    "a,button,input,textarea,select,[role],[contenteditable=true],[tabindex]"
)


class DriveStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, max_length=20)
    selector: str = Field(default="", max_length=1000)
    value: str = Field(default="", max_length=4000)
    url: str = Field(default="", max_length=2048)
    ms: int = Field(default=1000, ge=0, le=30000)
    delay_ms: int = Field(default=0, ge=0, le=1000)
    name: str = Field(default="", max_length=200)
    index: int = Field(default=0, ge=0, le=500)
    limit: int = Field(default=100, ge=1, le=200)


class DriveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Optional first navigation; steps may also carry their own goto.
    url: str = Field(default="", max_length=2048)
    steps: list[DriveStep] = Field(default_factory=list, max_length=MAX_STEPS)
    # Whole-run budget. Individual actions also have their own ceiling; this is
    # the backstop so one slow selector cannot hold a browser forever.
    timeout_ms: int = Field(default=45000, ge=1000, le=180000)
    # A named session retains cookies, local storage and its current page.
    # Empty means an ephemeral context that is closed after this request.
    session: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9._-]*$")
    close_session: bool = False
    allowed_hosts: list[str] = Field(default_factory=list, max_length=32)
    canaries: list[str] = Field(default_factory=list, max_length=20)
    include_events: bool = True
    # bool remains accepted for clients written against v1: true=always,
    # false=never. New callers should use the explicit modes.
    screenshot: bool | Literal["never", "failure", "canary", "always"] = "failure"
    screenshot_full_page: bool = False


def _screenshot_mode(value) -> str:
    if value is True:
        return "always"
    if value is False:
        return "never"
    return value


def _host_allowed(url: str, allowed_hosts: list[str]) -> bool:
    if not allowed_hosts:
        return True
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in ("http", "https") or not host:
        return False
    for raw in allowed_hosts:
        pattern = raw.lower().strip().rstrip(".")
        if pattern.startswith("*."):
            root = pattern[2:]
            if host == root or host.endswith("." + root):
                return True
        elif host == pattern:
            return True
    return False


def _new_event_store() -> dict[str, deque]:
    return {name: deque(maxlen=100) for name in
            ("dialogs", "console", "page_errors", "request_failures", "http_errors")}


def _install_event_capture(page, events: dict[str, deque]) -> None:
    async def dismiss(dialog):
        events["dialogs"].append({"type": dialog.type, "message": dialog.message[:1000]})
        try:
            await dialog.dismiss()
        except Exception:
            pass

    page.on("dialog", lambda dialog: asyncio.create_task(dismiss(dialog)))
    page.on("console", lambda msg: events["console"].append({
        "type": msg.type, "text": msg.text[:2000]}))
    page.on("pageerror", lambda exc: events["page_errors"].append(str(exc)[:2000]))
    page.on("requestfailed", lambda req: events["request_failures"].append({
        "url": req.url[:2048], "method": req.method, "reason": str(req.failure)[:500]}))
    page.on("response", lambda response: events["http_errors"].append({
        "url": response.url[:2048], "status": response.status})
        if response.status >= 400 else None)


async def _install_scope_route(page, allowed_hosts: list[str]) -> None:
    if not allowed_hosts:
        return

    async def scoped(route, request):
        if request.is_navigation_request() and request.frame == page.main_frame:
            if not _host_allowed(request.url, allowed_hosts):
                await route.abort("blockedbyclient")
                return
        await route.continue_()

    await page.route("**/*", scoped)


async def _make_drive_state(browser, allowed_hosts: list[str]) -> dict:
    context = await browser.new_context()
    page = await context.new_page()
    page.set_default_timeout(8000)
    events = _new_event_store()
    _install_event_capture(page, events)
    await _install_scope_route(page, allowed_hosts)
    return {"context": context, "page": page, "events": events,
            "allowed_hosts": list(allowed_hosts), "lock": asyncio.Lock(),
            "last_used": time.monotonic()}


async def _close_drive_state(state: dict) -> None:
    try:
        await asyncio.wait_for(state["context"].close(), timeout=5)
    except Exception:
        pass


async def _drop_drive_session(session_id: str, expected: dict | None = None) -> bool:
    async with DRIVE_SESSIONS_LOCK:
        state = DRIVE_SESSIONS.get(session_id)
        if state is None or (expected is not None and state is not expected):
            return False
        DRIVE_SESSIONS.pop(session_id, None)
    await _close_drive_state(state)
    return True


async def _close_all_drive_sessions() -> None:
    async with DRIVE_SESSIONS_LOCK:
        states = list(DRIVE_SESSIONS.values())
        DRIVE_SESSIONS.clear()
    await asyncio.gather(*(_close_drive_state(s) for s in states), return_exceptions=True)


async def _reap_drive_sessions() -> None:
    while True:
        await asyncio.sleep(min(60, max(10, DRIVE_SESSION_TTL // 4)))
        now = time.monotonic()
        async with DRIVE_SESSIONS_LOCK:
            expired = [(sid, state) for sid, state in DRIVE_SESSIONS.items()
                       if now - state["last_used"] > DRIVE_SESSION_TTL
                       and not state["lock"].locked()]
            for sid, _ in expired:
                DRIVE_SESSIONS.pop(sid, None)
        await asyncio.gather(*(_close_drive_state(s) for _, s in expired),
                             return_exceptions=True)


async def _get_drive_state(browser, body: DriveRequest) -> tuple[dict, bool]:
    if not body.session:
        return await _make_drive_state(browser, body.allowed_hosts), True
    evicted = None
    async with DRIVE_SESSIONS_LOCK:
        existing = DRIVE_SESSIONS.get(body.session)
        if existing is not None:
            if body.allowed_hosts and body.allowed_hosts != existing["allowed_hosts"]:
                raise HTTPException(409, "allowed_hosts cannot change within a session")
            existing["last_used"] = time.monotonic()
            return existing, False
        has_navigation = bool(body.url) or any(
            step.action.lower() == "goto" and bool(step.url) for step in body.steps
        )
        if not has_navigation:
            # A missing, expired, or evicted session must not masquerade as a
            # successful call against a new about:blank context. The caller
            # has lost state and needs to navigate/login again.
            raise HTTPException(
                409,
                "drive session not found; navigate first to create it, then reuse "
                "the returned session.id",
            )
        if len(DRIVE_SESSIONS) >= MAX_DRIVE_SESSIONS:
            # Generated sessions are a convenience and must not permanently
            # consume the finite pool if a caller forgets to close one. Never
            # evict an explicitly named workflow; only the least-recently-used
            # auto session is disposable.
            candidates = [
                (sid, item) for sid, item in DRIVE_SESSIONS.items()
                if sid.startswith("auto-") and not item["lock"].locked()
            ]
            if not candidates:
                raise HTTPException(429, "drive session limit reached")
            evicted_id, evicted = min(
                candidates, key=lambda pair: pair[1]["last_used"]
            )
            DRIVE_SESSIONS.pop(evicted_id, None)
        state = await _make_drive_state(browser, body.allowed_hosts)
        DRIVE_SESSIONS[body.session] = state
    if evicted is not None:
        await _close_drive_state(evicted)
    return state, False


def _events_since_start(events: dict[str, deque]) -> dict[str, list]:
    return {name: list(items) for name, items in events.items()}


async def _snapshot(page, selector: str, limit: int) -> list[dict]:
    locator = page.locator(selector or INTERACTIVE_SELECTOR)
    return await locator.evaluate_all("""(elements, limit) => elements.slice(0, limit).map((el) => {
      const text = (
        el.innerText || el.value || el.getAttribute('aria-label') || ''
      ).trim().slice(0, 240);
      const esc = (s) => String(s || '').replace(/\\\\/g, '\\\\\\\\').replace(/"/g, '\\\\"');
      let hint = el.id ? '#' + CSS.escape(el.id) : '';
      if (!hint && el.getAttribute('data-testid')) {
        hint = '[data-testid="' + esc(el.getAttribute('data-testid')) + '"]';
      }
      if (!hint && el.getAttribute('name')) {
        hint = el.tagName.toLowerCase()
          + '[name="' + esc(el.getAttribute('name')) + '"]';
      }
      return {
        tag: el.tagName.toLowerCase(), role: el.getAttribute('role') || '',
        type: el.getAttribute('type') || '',
        text, name: el.getAttribute('name') || '', id: el.id || '',
        aria_label: el.getAttribute('aria-label') || '',
        placeholder: el.getAttribute('placeholder') || '',
        href: (el.href || '').slice(0, 1000), testid: el.getAttribute('data-testid') || '',
        visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
        disabled: !!el.disabled, selector: hint
      };
    })""", limit)


async def _canary_matches(page, events: dict[str, deque], canaries: list[str]) -> list[dict]:
    if not canaries:
        return []
    title = await page.title()
    url = page.url
    try:
        body_text = (await page.locator("body").inner_text(timeout=1000))[:20000]
    except Exception:
        body_text = ""
    event_text = {name: str(list(items)) for name, items in events.items()}
    found = []
    for canary in canaries:
        channels = []
        if canary in title:
            channels.append("title")
        if canary in url:
            channels.append("url")
        if canary in body_text:
            channels.append("visible_text")
        channels.extend(name for name, text in event_text.items() if canary in text)
        if channels:
            found.append({"canary": canary, "channels": channels,
                          "execution_signal": any(c in channels for c in
                                                  ("title", "dialogs", "console", "page_errors"))})
    return found


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


async def _drive(state: dict, body: DriveRequest) -> dict:
    """Run a bounded sequence against an ephemeral or named persistent page.

    Every step is wrapped: its outcome is recorded whether it succeeds or
    throws, and the run stops at the first failure rather than pushing on with
    a page that is no longer in the state the caller assumed.
    """
    started = time.monotonic()
    deadline = started + body.timeout_ms / 1000.0
    results: list[dict] = []
    page = state["page"]
    events = state["events"]
    for items in events.values():
        items.clear()

    def locator(step):
        return page.locator(step.selector).nth(step.index)

    async def _run(action: str, coro_factory) -> dict:
        step = {"action": action, "ok": False, "reason": None,
                "elapsed_ms": 0, "data": None}
        t = time.monotonic()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            step["reason"] = "run_deadline_exceeded"
            step["elapsed_ms"] = 0
            return step
        try:
            step["data"] = await asyncio.wait_for(coro_factory(), timeout=remaining)
            step["ok"] = True
        except asyncio.TimeoutError:
            step["reason"] = "run_deadline_exceeded"
        except asyncio.CancelledError:
            step["reason"] = "cancelled"
            raise
        except Exception as exc:
            step["reason"] = type(exc).__name__ + ": " + str(exc)[:160]
        step["elapsed_ms"] = int((time.monotonic() - t) * 1000)
        return step

    async def navigate(url: str, timeout: int):
        allowed = state["allowed_hosts"]
        if allowed and not _host_allowed(url, allowed):
            raise ValueError("navigation outside allowed_hosts")
        response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        return {"url": page.url, "status": response.status if response else None}

    if body.url:
        results.append(await _run("goto", lambda: navigate(
            body.url, min(30000, body.timeout_ms))))

    for s in body.steps:
        if results and not results[-1]["ok"]:
            break
        action = s.action.lower()
        if action == "goto":
            async def call(s=s):
                return await navigate(s.url, min(30000, s.ms or 20000))
        elif action == "click":
            async def call(s=s):
                await locator(s).click(timeout=s.ms or 8000)
                return True
        elif action == "fill":
            async def call(s=s):
                target = locator(s)
                await target.fill(s.value, timeout=s.ms or 8000)
                await target.dispatch_event("change")
                return True
        elif action == "type":
            async def call(s=s):
                await locator(s).press_sequentially(s.value, delay=s.delay_ms,
                                                    timeout=s.ms or 8000)
                return True
        elif action == "press":
            async def call(s=s):
                target = locator(s) if s.selector else page.locator("body")
                await target.press(s.value or "Enter", timeout=s.ms or 8000)
                return True
        elif action == "select":
            async def call(s=s):
                return await locator(s).select_option(s.value, timeout=s.ms or 8000)
        elif action == "check":
            async def call(s=s):
                await locator(s).check(timeout=s.ms or 8000)
                return True
        elif action == "uncheck":
            async def call(s=s):
                await locator(s).uncheck(timeout=s.ms or 8000)
                return True
        elif action == "hover":
            async def call(s=s):
                await locator(s).hover(timeout=s.ms or 8000)
                return True
        elif action == "wait":
            async def call(s=s):
                await asyncio.sleep(min(s.ms, 30000) / 1000.0)
                return True
        elif action == "wait_for":
            async def call(s=s):
                state_name = s.value or "visible"
                if state_name not in ("attached", "detached", "visible", "hidden"):
                    raise ValueError(
                        "wait_for value must be attached, detached, visible, or hidden"
                    )
                await page.wait_for_selector(s.selector, state=state_name,
                                             timeout=s.ms or 8000)
                return True
        elif action == "text":
            async def call(s=s):
                target = locator(s) if s.selector else page.locator("body")
                return (await target.inner_text(timeout=s.ms or 8000))[:16000]
        elif action == "html":
            async def call(s=s):
                target = locator(s) if s.selector else page.locator("html")
                return (await target.evaluate("el => el.outerHTML"))[:20000]
        elif action == "attr":
            async def call(s=s):
                if not s.name:
                    raise ValueError("attr requires name")
                return await locator(s).get_attribute(s.name, timeout=s.ms or 8000)
        elif action == "count":
            async def call(s=s):
                return await page.locator(s.selector).count()
        elif action == "snapshot":
            async def call(s=s):
                return await _snapshot(page, s.selector, s.limit)
        elif action == "url":
            async def call():
                return page.url
        elif action == "title":
            call = page.title
        else:
            results.append({"action": action, "ok": False, "reason": "unknown_action",
                            "elapsed_ms": 0, "data": None})
            break
        results.append(await _run(action, call))
        if results[-1]["ok"] and state["allowed_hosts"]:
            if page.url != "about:blank" and not _host_allowed(page.url, state["allowed_hosts"]):
                results[-1].update(ok=False, reason="navigation_outside_allowed_hosts")

    matches = await _canary_matches(page, events, body.canaries)
    ok = bool(results) and all(r["ok"] for r in results)
    out = {
        "ok": ok,
        "steps": results,
        "final": {"url": page.url, "title": await page.title()},
        "session": {"id": body.session or None, "persistent": bool(body.session),
                    "closed": False, "ttl_seconds": DRIVE_SESSION_TTL if body.session else 0},
        "canary_matches": matches,
        "service_s": round(time.monotonic() - started, 3),
    }
    if body.include_events:
        out["events"] = _events_since_start(events)
    mode = _screenshot_mode(body.screenshot)
    capture = mode == "always" or (mode == "failure" and not ok) or (mode == "canary" and matches)
    if capture:
        try:
            png = await page.screenshot(full_page=body.screenshot_full_page)
            out["screenshot_b64"] = base64.b64encode(png).decode()
        except Exception as exc:
            out["screenshot_error"] = type(exc).__name__ + ": " + str(exc)[:120]
    state["last_used"] = time.monotonic()
    return out


@app.post("/drive")
async def drive(body: DriveRequest):
    if not body.url and not body.steps and not (body.session and body.close_session):
        raise HTTPException(422, "nothing to do: supply url and/or steps")
    if any(not h or len(h) > 253 or "/" in h or ":" in h for h in body.allowed_hosts):
        raise HTTPException(422, "allowed_hosts entries must be hostnames or *.hostnames")
    if any(not c or len(c) > 200 for c in body.canaries):
        raise HTTPException(422, "canaries must contain 1-200 characters")
    unknown = sorted({s.action.lower() for s in body.steps
                      if s.action.lower() not in DRIVE_ACTIONS})
    if unknown:
        # Refuse before a browser is borrowed. A typo'd action is a caller
        # error, and the honest place to say so is here, not after spinning up
        # a page and reporting a failure deep in the sequence.
        raise HTTPException(422, "unknown action(s): %s; supported: %s"
                            % (", ".join(unknown), ", ".join(DRIVE_ACTIONS)))
    try:
        await asyncio.wait_for(DRIVE_SEMAPHORE.acquire(), timeout=DRIVE_QUEUE_TIMEOUT)
    except TimeoutError:
        STATS["drive_queue_timeout"] += 1
        raise HTTPException(429, "drive queue timeout") from None
    try:
        if body.session and body.close_session and not body.url and not body.steps:
            closed = await _drop_drive_session(body.session)
            return {"ok": True, "steps": [], "session": {"id": body.session,
                    "persistent": True, "closed": closed}, "canary_matches": [],
                    "service_s": 0.0}
        state, ephemeral = await _get_drive_state(app.state.browser, body)
        try:
            async with state["lock"]:
                result = await _drive(state, body)
                if body.close_session and body.session:
                    await _drop_drive_session(body.session, expected=state)
                    result["session"]["closed"] = True
        finally:
            if ephemeral:
                await _close_drive_state(state)
        STATS["drive_requests"] += 1
        if result.get("ok"):
            STATS["drive_success"] += 1
        return result
    finally:
        DRIVE_SEMAPHORE.release()
