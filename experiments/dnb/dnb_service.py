"""Experimental shared Patchright acquisition + upstream Crawl4AI extraction.

Not a general replacement for Crawl4AI's API: accept only the contract used by
Dethrottled 1.7.1. Existing search/drive handlers and lifecycle remain unchanged.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import Counter
from contextlib import asynccontextmanager
from contextvars import ContextVar
from functools import partial
from pathlib import Path
from urllib.parse import urlparse

import service as browser
from context_pool import ContextPool
from dethrottled_adblock_proxy import Gate
from dethrottled_delegation import verify as verify_delegation
from extraction_pool import ExtractionFailure, ExtractionPool
from fastapi import HTTPException, Request
from lifecycle import cleanup, until_disconnect
from navigation_guard import enable as enable_navigation
from navigation_guard import install as install_navigation
from network_policy import Scope, install_drive_policy, memory_pressure, pinned_connect
from operation_store import (
    OperationConflict,
    OperationState,
    OperationStore,
)
from pydantic import BaseModel, ConfigDict, Field
from session_owners import OwnerMismatch, SessionOwners, StoreUnavailable

enable_navigation(browser.browser_api)
DRIVE_POLICY = ContextVar("drive_asset_policy", default=(None, ""))
install_drive_policy(browser, Gate, asset_policy=DRIVE_POLICY.get)

app = browser.app
RENDER_SLOTS = asyncio.Semaphore(2)
COUNTS = Counter()
ALLOW_INTERNAL = os.getenv("DNB_ALLOW_INTERNAL_URLS", "false").lower() == "true"
MAX_HTML = 8 * 1024 * 1024

PUBLIC_KEY = os.getenv("DNB_TRUST_PUBLIC_KEY", "")
EXTRACTORS = ExtractionPool()
WAITING = 0
DRIVE_INFLIGHT = 0
OPERATIONS = {}

_STATE_DIR = Path(
    os.getenv(
        "DETHROTTLED_DNB_STATE_DIR",
        str(Path(os.getenv("DETHROTTLED_DATA_DIR", str(Path.home() / ".cache/dethrottled"))) / "dnb"),
    )
)
try:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_OWNERS = SessionOwners(_STATE_DIR / "owners.sqlite")
except (OSError, StoreUnavailable):
    # Keep crawl/read available; drive with a verified identity fails closed.
    SESSION_OWNERS = None
try:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    OPERATION_STORE = OperationStore(_STATE_DIR / "operations.sqlite")
except (OSError, StoreUnavailable):
    OPERATION_STORE = None


DEFAULT_POLICY = Scope(not ALLOW_INTERNAL)
CURRENT_POLICY = ContextVar("dnb_network_policy", default=DEFAULT_POLICY)


async def create_state():
    network = CURRENT_POLICY.get()
    gate = Gate(
        connector=partial(
            pinned_connect, public_only=network.public_only, allowed_hosts=network.egress
        )
    )
    context = None
    try:
        proxy = await gate.start()
        render_browser = getattr(app.state, "crawl_browser", None) or app.state.browser
        context = await render_browser.new_context(accept_downloads=True, proxy=proxy)
        page = await context.new_page()
        await install_navigation(context, network, gate.events)
        return {
            "context": context,
            "page": page,
            "allowed_hosts": list(network.navigation_hosts),
            "public_only": network.public_only,
            "events": browser._new_event_store(),
            "responses": [],
            "network_gate": gate,
        }
    except BaseException:
        if context:
            await context.close()
        await gate.close()
        raise


async def close_state(state):
    async def dispose():
        try:
            await state["context"].close()
        finally:
            if state.get("network_gate"):
                await state["network_gate"].close()

    await cleanup(dispose())


POOL = ContextPool(create_state, close_state, pressure=memory_pressure)
ORIGINAL_LIFESPAN = app.router.lifespan_context


@asynccontextmanager
async def lifespan(application):
    if PUBLIC_KEY:
        from pathlib import Path

        import jwt  # noqa: F401 -- validate required verifier dependency before readiness.
        from cryptography.hazmat.primitives.serialization import load_pem_public_key

        deadline = time.monotonic() + 30
        while not Path(PUBLIC_KEY).exists() and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        load_pem_public_key(Path(PUBLIC_KEY).read_bytes())
    async with ORIGINAL_LIFESPAN(application):

        async def reap():
            while True:
                await asyncio.sleep(10)
                await POOL.reap()

        task = asyncio.create_task(reap())
        try:
            await EXTRACTORS.warm()
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await POOL.shutdown()
            await EXTRACTORS.close()


app.router.lifespan_context = lifespan


def principal(request):
    return getattr(request.state, "dnb_claims", None) if request else None


def policy(request, url=""):
    claims = principal(request)
    if not claims:
        public = not ALLOW_INTERNAL
        host = urlparse(url).hostname or ""
        return Scope(public, () if public else (host,) if host else (), None, host)
    public = claims["public_only"]
    hosts = tuple(sorted(set(h.lower() for h in claims["allowed_hosts"])))
    if any(not re.fullmatch(r"(?:\*\.)?[a-z0-9.-]{1,253}", host) for host in hosts):
        raise HTTPException(422, "invalid network scope")
    if not public and not ALLOW_INTERNAL:
        raise HTTPException(403, "internal targets disabled by worker policy")
    assets = claims.get("asset_hosts")
    assets = tuple(sorted(set(h.lower() for h in assets))) if assets is not None else None
    if assets and any(not re.fullmatch(r"(?:\*\.)?[a-z0-9.-]{1,253}", h) for h in assets):
        raise HTTPException(422, "invalid asset scope")
    host = urlparse(url).hostname or ""
    if not hosts and not public and host:
        hosts = (host,)
    return Scope(public, hosts, assets, host)


def pool_key(request: Request | None, url: str, browser_config=None):
    claims = principal(request)
    if not claims:
        if request and request.headers.get("x-dnb-owner"):
            raise HTTPException(403, "untrusted_owner_headers")
        return None
    if not claims["session"] or not claims["scope"]:
        return None
    parsed = urlparse(url)
    origin = (
        parsed.scheme,
        parsed.hostname,
        parsed.port or (443 if parsed.scheme == "https" else 80),
    )
    config = (
        bool((browser_config or {}).get("headless", True)),
        os.getenv("DETHROTTLED_BROWSER_GRAPHICS", "auto"),
    )
    return (
        claims["sub"],
        claims["session"],
        claims["scope"],
        origin,
        policy(request, url),
        config,
        claims["page_mode"],
    )


async def authorize(request, body, path="/crawl"):
    if request is None:
        return None
    forbidden = {
        "x-dnb-owner",
        "x-dnb-session",
        "x-dnb-scope",
        "x-dnb-page",
        "x-dnb-public-only",
        "x-dnb-allowed-hosts",
        "x-dnb-operation-id",
    }
    if any(name in request.headers for name in forbidden):
        raise retry_error("untrusted_owner_headers", 403, False)
    token = request.headers.get("x-dnb-delegation")
    if not token:
        if path == "/drive" and PUBLIC_KEY:
            raise retry_error("delegation_required", 403, False)
        return None
    if not PUBLIC_KEY:
        raise retry_error("delegation_verifier_unavailable", 503, True)
    try:
        claims = verify_delegation(token, body, PUBLIC_KEY, path=path)
    except Exception as exc:
        # No token, claim or key content in the error. Verification fails closed.
        raise retry_error("invalid_delegation", 403, False) from exc
    request.state.dnb_claims = claims
    return claims


@asynccontextmanager
async def render_state(key):
    if key is None:
        # Anonymous renders have no retained state or shared identity.
        ephemeral = ContextPool(create_state, close_state, maximum=1)
        try:
            async with ephemeral.lease("ephemeral") as pair:
                yield pair
        finally:
            await ephemeral.shutdown()
        return
    async with POOL.lease(key) as (state, reused):
        if reused and key[-1] == "fresh":
            # Keep the same owner's storage, but discard the previous DOM and
            # all popups. A fresh context is never reassigned to another owner.
            old_pages = list(state["context"].pages)
            state["page"] = await state["context"].new_page()
            for page in old_pages:
                await page.close()
        for events in state["events"].values():
            events.clear()
        state["responses"].clear()
        try:
            yield state, reused
        except BaseException:
            raise  # Pool discards the context; do not mask the original failure.
        else:
            for page in list(state["context"].pages):
                if page != state["page"]:
                    await page.close()
            # Release the source DOM and its timers after capture. Keep the
            # same owner's tab/context/storage warm, not a live website running.
            await state["page"].goto("about:blank", wait_until="commit", timeout=1000)


class TypedConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    params: dict = Field(default_factory=dict)


class CrawlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    urls: list[str] = Field(min_length=1, max_length=1)
    browser_config: TypedConfig = Field(
        default_factory=lambda: TypedConfig(type="BrowserConfig", params={"headless": True})
    )
    crawler_config: TypedConfig = Field(
        default_factory=lambda: TypedConfig(type="CrawlerRunConfig", params={})
    )


def options(body: CrawlRequest) -> dict:
    if (
        body.browser_config.type != "BrowserConfig"
        or body.crawler_config.type != "CrawlerRunConfig"
    ):
        raise HTTPException(422, "unsupported config type")
    b, c = body.browser_config.params, body.crawler_config.params
    if set(b) - {"headless"} or ("headless" in b and not isinstance(b["headless"], bool)):
        raise HTTPException(422, "unsupported browser options")
    if set(c) - {
        "cache_mode",
        "check_robots_txt",
        "page_timeout",
        "delay_before_return_html",
        "wait_for",
    }:
        raise HTTPException(422, "unsupported crawler options")
    if c.get("cache_mode", "bypass") != "bypass" or c.get("check_robots_txt", False) is not False:
        raise HTTPException(422, "prototype requires bypass and robots policy owned by API")
    timeout = c.get("page_timeout", 20000)
    delay = c.get("delay_before_return_html", 0.5)
    wait = c.get("wait_for", "")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, int)
        or not 100 <= timeout <= 30000
        or isinstance(delay, bool)
        or not isinstance(delay, (float, int))
        or not 0 <= delay <= 5
        or not isinstance(wait, str)
        or len(wait) > 1000
        or (wait and not wait.startswith("css:"))
    ):
        raise HTTPException(422, "invalid bounded render options")
    return {"timeout": timeout, "delay": delay, "wait": wait.removeprefix("css:")}


def extract(url: str, html: str) -> dict:
    # Direct imports remain available to extraction contract tests.
    from html_extract import extract as implementation

    return implementation(url, html)


def valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return (
            len(url) <= 2048
            and parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
            and bool(parsed.port or 80)
        )
    except ValueError:
        return False


@app.get("/dnb/status")
async def dnb_status():
    try:
        owner_count = SESSION_OWNERS.count() if SESSION_OWNERS is not None else None
    except StoreUnavailable:
        owner_count = "unavailable"
    try:
        operation_count = (
            OPERATION_STORE.count() if OPERATION_STORE is not None else None
        )
    except StoreUnavailable:
        operation_count = "unavailable"
    return {
        "prototype": True,
        "reference": "1.7.1",
        "browser": "shared-headed-patchright",
        "crawl_browser_separate": bool(getattr(app.state, "crawl_browser", None)),
        "crawl_browser_headless": bool(
            getattr(app.state, "crawl_browser_headless", False)
        ),
        "extractor": "crawl4ai-0.9.5",
        "counts": dict(COUNTS),
        "render_slots": 2,
        "waiting": WAITING,
        "active": 2 - RENDER_SLOTS._value,
        "drive_inflight": DRIVE_INFLIGHT,
        "drive_sessions": len(browser.DRIVE_SESSIONS),
        "session_owners": owner_count,
        "operations": operation_count,
        "extraction": {
            "workers": len(EXTRACTORS.processes),
            "active": EXTRACTORS.size - EXTRACTORS.available.qsize(),
            "counts": dict(EXTRACTORS.counts),
        },
        "pool": {
            "enabled": bool(PUBLIC_KEY),
            "contexts": len(POOL.entries),
            "maximum": POOL.maximum,
            "ttl_seconds": POOL.ttl,
        },
        "internal_urls_allowed": ALLOW_INTERNAL,
        "compatibility": "Dethrottled crawl subset; not full Crawl4AI API",
    }


async def _crawl(body: CrawlRequest, request: Request = None):
    config = options(body)
    url = body.urls[0]
    if not valid_url(url):
        raise HTTPException(422, "expected HTTP(S) URL without credentials")
    key = pool_key(request, url, body.browser_config.params)
    if policy(request, url).public_only and not await browser._public_network_target(url):
        raise HTTPException(403, "non-public target")
    network_policy = policy(request, url)
    started = time.monotonic()
    global WAITING
    if memory_pressure():
        raise retry_error("render_memory_pressure", 503, True)
    if WAITING >= 4:
        raise retry_error("render_queue_full", 503, True)
    WAITING += 1
    try:
        await asyncio.wait_for(RENDER_SLOTS.acquire(), timeout=5)
    except TimeoutError:
        COUNTS["busy"] += 1
        raise retry_error("render_capacity_busy", 503, True) from None
    finally:
        WAITING -= 1
    state = None
    policy_token = CURRENT_POLICY.set(network_policy)
    try:
        async with render_state(key) as (state, reused):
            # Timeout covers context creation, navigation, waits and HTML capture.
            async with asyncio.timeout(config["timeout"] / 1000 + config["delay"] + 2):
                page = state["page"]
                responses = []

                def capture(response):
                    if (
                        response.request.is_navigation_request()
                        and response.request.frame == page.main_frame
                    ):
                        responses.append(response)

                page.on("response", capture)
                navigation = await browser._navigate(
                    state,
                    browser.DriveRequest(navigation_wait="domcontentloaded"),
                    url,
                    config["timeout"],
                    started + config["timeout"] / 1000,
                )
                page.remove_listener("response", capture)
                response = responses[-1] if responses else None
                if config["wait"]:
                    await page.locator(config["wait"]).first.wait_for(
                        state="attached", timeout=config["timeout"]
                    )
                if config["delay"]:
                    await asyncio.sleep(config["delay"])
                final_url = page.url
                status = navigation["status"]
                headers = await response.all_headers() if response else {}
                html = await page.content()
                if len(html.encode("utf-8")) > MAX_HTML:
                    raise ValueError("render_html_too_large")
            result = await EXTRACTORS.run(final_url, html)
            result.update(
                url=final_url,
                html=html,
                status_code=status,
                response_headers=headers,
                access=navigation["access"],
                navigation_recovery=navigation.get("recovery"),
                adblock={
                    "blocked": [
                        event
                        for event in getattr(state["context"], "_dethrottled_adblock_events", [])
                        if event["at"] >= started
                    ][-20:]
                },
                dnb={
                    "requested_headless": body.browser_config.params.get("headless", True),
                    "effective_headless": False,
                    "context_reused": reused,
                    "page_mode": key[-1] if key else "anonymous",
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                },
            )
            if navigation["access"]["status"] in {"challenge", "login_required"}:
                result.update(success=False, error_message=navigation["access"]["reason"])
            if status and status >= 400:
                events = state["network_gate"].events
                reason = events[-1].get("reason") if events else None
                result.update(success=False, error_message=reason or f"http_{status}")
            if not result["success"] and "error_message" not in result:
                result["error_message"] = "empty_extracted_content"
            COUNTS["success" if result["success"] else "failed"] += 1
            return {"success": result["success"], "results": [result]}
    except TimeoutError:
        raise retry_error("browser_timeout", 504, False) from None
    except ExtractionFailure as exc:
        raise retry_error(exc.code, exc.status, exc.retryable) from None
    except HTTPException as exc:
        if exc.status_code in {409, 429, 503} and isinstance(exc.detail, str):
            code = (
                "render_session_busy"
                if exc.status_code == 409
                else "render_memory_pressure"
                if "memory pressure" in exc.detail
                else "render_pool_busy"
            )
            raise retry_error(code, exc.status_code, True) from None
        raise
    except Exception as exc:
        COUNTS["failed"] += 1
        return {
            "success": False,
            "results": [
                {
                    "success": False,
                    "url": url,
                    "error_message": (
                        str(state["network_gate"].events[-1]["reason"])
                        if state
                        and state.get("network_gate")
                        and state["network_gate"].events
                        and "reason" in state["network_gate"].events[-1]
                        else str(exc)[:500] or type(exc).__name__
                    ),
                    "dnb": {"elapsed_ms": round((time.monotonic() - started) * 1000, 2)},
                }
            ],
        }
    finally:
        CURRENT_POLICY.reset(policy_token)
        RENDER_SLOTS.release()


def retry_error(code, status, retryable):
    return HTTPException(
        status,
        {"code": code, "retryable": retryable, "retry_after_seconds": 1 if retryable else None},
        headers={"Retry-After": "1"} if retryable else None,
    )


@app.post("/crawl")
async def crawl(body: CrawlRequest, request: Request = None):
    # Only read operations are handled here; drive's operation journal remains
    # responsible for mutation replay protection.
    options(body)
    if not valid_url(body.urls[0]):
        raise HTTPException(422, "expected HTTP(S) URL without credentials")
    claims = await authorize(request, await request.json() if request else body.model_dump())
    key = pool_key(request, body.urls[0], body.browser_config.params)
    operation = claims["jti"] if claims and key else ""
    if len(operation) > 128 or (operation and key is None):
        raise retry_error("operation_requires_scoped_identity", 422, False)
    operation_key = (key, operation) if operation else None
    if operation_key and operation_key in OPERATIONS:
        same = OPERATIONS[operation_key] == body.model_dump_json()
        raise retry_error("operation_in_progress" if same else "operation_conflict", 409, same)
    if operation_key:
        OPERATIONS[operation_key] = body.model_dump_json()

    async def run():
        # Includes context creation and queue wait, not only navigation.
        config = options(body)
        budget = config["timeout"] / 1000 + config["delay"] + EXTRACTORS.timeout + 10
        try:
            async with asyncio.timeout(budget):
                return await _crawl(body, request)
        except TimeoutError:
            raise retry_error("render_deadline", 504, False) from None

    def disconnected_error():
        COUNTS["disconnected"] += 1
        return retry_error("client_disconnected", 499, False)

    try:
        return await until_disconnect(request, run(), disconnected_error)
    finally:
        if operation_key:
            OPERATIONS.pop(operation_key, None)


from starlette.responses import JSONResponse  # noqa: E402


class WorkerBoundary:
    """Bound input without BaseHTTPMiddleware obscuring http.disconnect."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        length = headers.get(b"content-length", b"")

        async def oversized():
            return await JSONResponse(
                {"detail": {"code": "request_too_large", "retryable": False}},
                status_code=413,
                headers={"Connection": "close"},
            )(scope, receive, send)

        if length.isdigit() and int(length) > 1024**2:
            return await oversized()
        data = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                COUNTS["disconnected_before_body"] += 1
                return
            if message["type"] != "http.request":
                continue
            data.extend(message.get("body", b""))
            if len(data) > 1024**2:
                return await oversized()
            if not message.get("more_body", False):
                break
        if scope.get("path") == "/drive":
            try:
                body = __import__("json").loads(data)
                if not isinstance(body, dict):
                    raise ValueError("JSON object required")
                request = Request(scope)
                claims = await authorize(request, body, path="/drive")
                if claims and (
                    body.get("public_only", False) != claims["public_only"]
                    or body.get("allowed_hosts", []) != claims["allowed_hosts"]
                    or body.get("session", "") != claims["session"]
                ):
                    raise retry_error("delegation_policy_mismatch", 403, False)
            except HTTPException as exc:
                return await JSONResponse(
                    {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
                )(scope, receive, send)
            except (ValueError, TypeError):
                return await JSONResponse({"detail": "invalid JSON"}, status_code=422)(
                    scope, receive, send
                )
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(data), "more_body": False}
            # Forward the real disconnect channel after replaying the body.
            return await receive()

        return await self.app(scope, replay, send)


app.add_middleware(WorkerBoundary)


# Preserve drive's bounded action vocabulary and existing mutation journal.
# Only the request lifecycle changes: disconnects stop active work, and unknown
# mutation outcomes remain non-replayable under the same operation ID.
ORIGINAL_DRIVE = browser.drive
ORIGINAL_DRIVE_STEPS = browser._drive
browser._close_drive_state = close_state


async def drive_steps(state, body):
    try:
        return await ORIGINAL_DRIVE_STEPS(state, body)
    except asyncio.CancelledError:
        if body.session:
            await browser._drop_drive_session(body.session, expected=state)
        raise


browser._drive = drive_steps


async def bounded_drive(body, request):
    claims = principal(request)
    durable_session = bool(body.session) and not body.session.startswith(
        ("auto-read-", "auto-reader-")
    )
    if claims and durable_session:
        if SESSION_OWNERS is None:
            raise retry_error("session_owner_store_unavailable", 503, True)
        try:
            SESSION_OWNERS.claim(body.session, claims["sub"])
        except OwnerMismatch:
            raise retry_error("session_owner_mismatch", 403, False) from None
        except StoreUnavailable:
            raise retry_error("session_owner_store_unavailable", 503, True) from None
    # A retry must not allocate a fresh persistent browser session merely to
    # discover that its mutation outcome is already completed or unknown.
    if body.operation_id and body.session:
        prior = browser.DRIVE_OPERATIONS.get((body.session, body.operation_id))
        if prior:
            fingerprints = {
                browser._operation_fingerprint(body),
                browser._operation_fingerprint(body, normalize=False),
            }
            if prior["fingerprint"] not in fingerprints:
                raise retry_error("operation_id_payload_conflict", 409, False)
            if prior["state"] == "running":
                raise retry_error("drive_operation_in_progress", 409, True)
            try:
                replay = browser._operation_lookup(body)
                if replay is not None:
                    return replay
            except HTTPException as exc:
                raise retry_error(str(exc.detail), exc.status_code, False) from None

    global DRIVE_INFLIGHT
    if DRIVE_INFLIGHT >= 6:
        raise retry_error("drive_queue_full", 429, True)

    durable_op = bool(claims and durable_session and body.operation_id)
    if durable_op:
        if OPERATION_STORE is None:
            raise retry_error("operation_store_unavailable", 503, True)
        fingerprints = [
            browser._operation_fingerprint(body),
            browser._operation_fingerprint(body, normalize=False),
        ]
        try:
            existing = OPERATION_STORE.begin(
                claims["sub"], body.session, body.operation_id, fingerprints
            )
        except OperationConflict:
            raise retry_error("operation_id_payload_conflict", 409, False) from None
        except StoreUnavailable:
            raise retry_error("operation_store_unavailable", 503, True) from None
        if existing is not None:
            if existing.state == OperationState.COMPLETED and existing.result:
                try:
                    return json.loads(existing.result)
                except (TypeError, ValueError):
                    raise retry_error("operation_result_unreadable", 503, True) from None
            if existing.state == OperationState.RUNNING:
                raise retry_error("drive_operation_in_progress", 409, True)
            raise retry_error("drive_outcome_unknown", 409, False)

    DRIVE_INFLIGHT += 1

    async def run():
        try:
            async with asyncio.timeout(body.timeout_ms / 1000 + browser.DRIVE_QUEUE_TIMEOUT + 5):
                return await ORIGINAL_DRIVE(body)
        except TimeoutError:
            raise retry_error("drive_deadline", 504, False) from None
        except HTTPException as exc:
            if isinstance(exc.detail, str):
                raise retry_error(
                    exc.detail, exc.status_code, exc.status_code in {429, 503}
                ) from None
            raise

    assets = claims.get("asset_hosts") if claims else None
    initial = urlparse(body.url).hostname or next(
        (
            urlparse(step.url).hostname
            for step in body.steps
            if step.action.lower() == "goto" and step.url
        ),
        "",
    )
    token = DRIVE_POLICY.set((tuple(assets) if assets is not None else None, initial))
    try:
        result = await until_disconnect(
            request, run(), lambda: retry_error("drive_outcome_unknown", 499, False)
        )
    except BaseException:
        if durable_op:
            try:
                OPERATION_STORE.mark_unknown(
                    claims["sub"], body.session, body.operation_id
                )
            except StoreUnavailable:
                COUNTS["operation_store_failure"] += 1
        raise
    else:
        if durable_op:
            try:
                OPERATION_STORE.complete(
                    claims["sub"], body.session, body.operation_id, result
                )
            except StoreUnavailable:
                # The mutation succeeded; keep the in-memory result for this
                # process and never replay a restart-time "running" row.
                COUNTS["operation_store_failure"] += 1
    finally:
        DRIVE_POLICY.reset(token)
        DRIVE_INFLIGHT -= 1
    if body.close_session and claims and durable_session:
        if SESSION_OWNERS is not None:
            try:
                SESSION_OWNERS.release(body.session)
            except StoreUnavailable:
                # The drive succeeded and the browser closed the session; keep the
                # binding rather than risk unbinding a checkpoint another owner
                # could then claim.
                COUNTS["session_owner_release_failed"] += 1
        if OPERATION_STORE is not None:
            try:
                OPERATION_STORE.release_session(claims["sub"], body.session)
            except StoreUnavailable:
                COUNTS["operation_store_failure"] += 1
    return result


for route in app.routes:
    if getattr(route, "path", None) == "/drive":
        route.dependant.call = bounded_drive
        route.dependant.request_param_name = "request"
