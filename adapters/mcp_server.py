from __future__ import annotations

import contextvars
import hashlib
import ipaddress
import json
import os
import secrets
import socket
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

import httpx
from dethrottled_access import CLAIMS, REQUEST_ID, AccessMiddleware, require_scope
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse

# The bridge and dethrottled run on szbox. Keep the fallback local too, so a
# missing EnvironmentFile cannot silently send research to the old Q6A host.
MCP_BACKEND_URL = os.getenv("MCP_BACKEND_URL", "http://127.0.0.1:8787").rstrip("/")
KEYS_PATH = Path(os.getenv("MCP_KEYS_PATH", "/etc/dethrottled-mcp/keys.json"))
REQUEST_TIMEOUT = float(os.getenv("MCP_REQUEST_TIMEOUT", "90"))
MAX_URLS = int(os.getenv("MCP_MAX_URLS", "10"))
MAX_RESULTS = int(os.getenv("MCP_MAX_RESULTS", "10"))
MAX_CHARS = int(os.getenv("MCP_MAX_CHARS", "120000"))
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv(
        "MCP_ALLOWED_HOSTS",
        "127.0.0.1:*,localhost:*,[::1]:*,api.halonyx.io,api.halonyx.io:*",
    ).split(",")
    if host.strip()
]


class AuthError(Exception):
    pass


MCP_KEY_NAMESPACE = contextvars.ContextVar("mcp_key_namespace", default="local")


def _check_bearer(scope: dict[str, Any]) -> tuple[str, str]:
    claims = CLAIMS.get()
    if claims is None:
        raise AuthError("missing verified identity")
    return claims["label"], claims["namespace"]


class BearerAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path == "/health":
            response = JSONResponse({"status": "ok", "service": "dethrottled-mcp"})
            await response(scope, receive, send)
            return

        if scope.get("method") == "OPTIONS":
            response = JSONResponse({"status": "ok"})
            await response(scope, receive, send)
            return

        try:
            label, namespace = _check_bearer(scope)
            scope["mcp_key_label"] = label
        except AuthError as exc:
            response = JSONResponse(
                {"error": "unauthorized", "detail": str(exc)},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        token = MCP_KEY_NAMESPACE.set(namespace)
        try:
            await self.app(scope, receive, send)
        finally:
            MCP_KEY_NAMESPACE.reset(token)


def _bounded_int(value: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or int(value) != value or not minimum <= int(value) <= maximum:
        raise ValueError(f"value must be between {minimum} and {maximum}")
    return int(value)


def _bounded_urls(urls: list[str]) -> list[str]:
    clean = [url.strip() for url in urls if isinstance(url, str) and url.strip()]
    if not clean:
        raise ValueError("at least one URL is required")
    if len(clean) > MAX_URLS:
        raise ValueError(f"at most {MAX_URLS} URLs are supported")
    if any(not _public_url(url) for url in clean):
        raise ValueError("public HTTP(S) URLs are required")
    return clean


def _public_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        if parsed.username or parsed.password or parsed.fragment:
            return False
        if parsed.port not in {None, 80, 443}:
            return False
        hostname = parsed.hostname.rstrip(".").lower()
        if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(
            (".localhost", ".local", ".lan", ".home", ".internal")
        ):
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        return bool(addresses) and all(
            ipaddress.ip_address(row[4][0]).is_global for row in addresses
        )
    except (ValueError, OSError, UnicodeError):
        return False


def _public_hostname(value: str) -> bool:
    if not isinstance(value, str):
        return False
    hostname = value.strip().lower().rstrip(".")
    if hostname.startswith("*."):
        hostname = hostname[2:]
    if not hostname or "/" in hostname or ":" in hostname:
        return False
    return _public_url("https://" + hostname)


def _hostname_allowed(url: str, allowed_hosts: list[str]) -> bool:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    for raw in allowed_hosts:
        pattern = raw.lower().strip().rstrip(".")
        if pattern.startswith("*."):
            root = pattern[2:]
            if host == root or host.endswith("." + root):
                return True
        elif host == pattern:
            return True
    return False


def _private_session_id(namespace: str, session: str) -> str:
    digest = hashlib.sha256(session.encode()).hexdigest()[:32]
    prefix = "auto-m" if session.startswith("auto-") else "m"
    return f"{prefix}{namespace[:12]}-{digest}"


def _backend_result(response):
    if response.status_code == 422:
        detail = response.json().get("detail", [])
        if isinstance(detail, list):
            detail = "; ".join(
                ".".join(map(str, item.get("loc", []))) + ": " + item.get("msg", "invalid")
                for item in detail if isinstance(item, dict))
        raise ValueError("Invalid tool input: " + str(detail)[:1000])
    if response.status_code >= 400:
        try:
            detail = response.json()
        except ValueError:
            detail = {"detail": "backend request failed"}
        raise ValueError(json.dumps({"http_status": response.status_code,
            "detail": detail, "retry_after": response.headers.get("Retry-After")})[:2000])
    return response.json()


async def _backend_get(path: str, params: dict[str, Any] | None = None) -> Any:
    require_scope("corpus" if path.startswith("/corpus/") else "web")
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, trust_env=False) as client:
        response = await client.get(f"{MCP_BACKEND_URL}{path}", params=params,
                                    headers={"X-Request-ID": REQUEST_ID.get()})
        return _backend_result(response)


async def _backend_post(
    path: str,
    payload: dict[str, Any],
    timeout: float | None = None,
) -> Any:
    require_scope("drive" if path == "/drive" else "web")
    if path in {"/fetch", "/extract-with-links", "/drive", "/jobs/fetch"}:
        payload = dict(payload, public_only=True)
    if path in {"/fetch", "/extract-with-links", "/research", "/search-and-fetch",
                "/documents/read", "/documents/image", "/jobs/fetch", "/jobs/read",
                "/jobs/cancel", "/drive"}:
        payload = dict(payload, evidence_namespace=CLAIMS.get()["namespace"])
    if path in {"/fetch", "/extract-with-links", "/research", "/search-and-fetch"}:
        timeout = max(timeout or REQUEST_TIMEOUT, 240)
    async with httpx.AsyncClient(
        timeout=timeout or REQUEST_TIMEOUT, trust_env=False
    ) as client:
        response = await client.post(f"{MCP_BACKEND_URL}{path}", json=payload,
                                     headers={"X-Request-ID": REQUEST_ID.get()})
        return _backend_result(response)


mcp = FastMCP(
    "dethrottled MCP",
    # engine_*, not web_*: OpenClaw ships built-in web_search and web_fetch, and
    # a same-named MCP tool is a needless collision in an agent's tool list.
    # Named for the role rather than the backend, so repointing this bridge does
    # not make every tool name wrong again.
    instructions=(
        "Search, read, research, corpus, diagnostics, and a stateful browser "
        "driver over one self-hosted web engine. Use search to discover, "
        "fetch to read, research for cited evidence, and drive only when a "
        "real page must be operated. Drive supports persistent sessions, "
        "structured DOM snapshots, bounded actions, and execution canaries. "
        "Prefer snapshots and event telemetry to screenshots. Public tools "
        "accept public HTTP(S) targets only."
    ),
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(allowed_hosts=ALLOWED_HOSTS),
)




@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def search(
    query: str,
    limit: int = 10,
    fresh: bool = False,
    rank: bool = False,
    corpus: int = 0,
    recency: float = 0.0,
    categories: str = "",
    language: str = "",
    profile: Literal["fast", "web", "balanced", "thorough", "news", "academic"] = "web",
    engines: str = "",
    ranking: Literal["source", "bm25", "fusion"] = "source",
    prefer_domains: list[str] | None = None,
    diagnostics: bool = False,
    cache_mode: Literal["use", "refresh", "bypass"] = "use",
    max_age: float | None = None,
) -> Any:
    """Find pages. Returns ranked results with url, title and snippet.

    Use web for general discovery, news for reporting, academic for papers,
    or thorough for web plus Mwmbl. Prefer search then selected fetches when
    source authority matters; search_and_fetch combines discovery and reading.
    """
    return await _backend_post("/v2/search" if diagnostics else "/search", {
        "query": query,
        "limit": _bounded_int(limit, 1, MAX_RESULTS),
        "fresh": fresh,
        "rank": rank,
        "corpus": _bounded_int(corpus, 0, 20),
        "recency": recency,
        "categories": categories,
        "language": language,
        "profile": profile, "engines": engines, "cache_mode": cache_mode, "max_age": max_age,
        "ranking": ranking, "prefer_domains": prefer_domains or [],
    })


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def fetch(
    urls: list[str],
    max_chars: int = 12000,
    format: Literal["text", "links", "html"] = "text",
    render: Literal["auto", "always", "never"] = "auto",
    fresh: bool = False,
    cache_mode: Literal["use", "refresh", "bypass"] = "use",
    max_age: float | None = None,
    wait_for: str = "",
    render_delay: Annotated[float, Field(ge=0, le=5)] = 0.5,
    headed_fallback: bool = False,
    focus: str = "",
    response_format: Literal["detailed", "concise"] = "detailed",
    ocr_language: str = "",
    ocr_mode: Literal["auto", "always", "never"] = "auto",
    page_start: Annotated[int, Field(ge=1)] = 1,
    page_end: Annotated[int | None, Field(ge=1)] = None,
    row_start: Annotated[int, Field(ge=1)] = 1,
    row_end: Annotated[int | None, Field(ge=1)] = None,
    sheet: str = "",
    max_cell_chars: Annotated[int | None, Field(ge=1, le=1000000)] = None,
) -> Any:
    """Read pages you already have URLs for.

    Known URLs can skip search. focus selects passages relevant to a question
    while retaining a versioned document_id for follow-up reads. page_start/end
    select PDF pages; ocr_language selects installed Tesseract language data.
    OCR and partial-read warnings must be preserved when answering.

    format  text  article prose (default)
            links prose with anchors kept as markdown, for link discovery
            html  the source, if you intend to parse it yourself
    render  auto   use a browser only if the cheaper tiers fail (default)
            always for a page you know needs JavaScript
            never  stay on the fast tiers when latency matters more than reach
    """
    return await _backend_post("/fetch", {
        "urls": _bounded_urls(urls),
        "max_chars": _bounded_int(max_chars, 1, MAX_CHARS),
        "format": format,
        "render": render,
        "fresh": fresh,
        "cache_mode": cache_mode, "max_age": max_age, "wait_for": wait_for,
        "render_delay": render_delay, "headed_fallback": headed_fallback,
        "focus": focus, "response_format": response_format, "ocr_language": ocr_language,
        "page_start": page_start, "page_end": page_end, "ocr_mode": ocr_mode,
        "row_start": row_start, "row_end": row_end, "sheet": sheet,
        "max_cell_chars": max_cell_chars,
    })


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def extract_with_links(
    urls: list[str],
    max_chars: int = 12000,
    render: Literal["auto", "always", "never"] = "auto",
    fresh: bool = False,
) -> Any:
    """Read public URLs while retaining resolved outbound links."""
    return await _backend_post("/extract-with-links", {
        "urls": _bounded_urls(urls),
        "max_chars": _bounded_int(max_chars, 1, MAX_CHARS),
        "render": render,
        "fresh": fresh,
    })


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def search_and_fetch(
    query: str,
    limit: int = 5,
    max_chars: int = 3000,
    rank: bool = False,
    render: Literal["auto", "always", "never"] = "auto",
    fresh: bool = False,
    ocr_mode: Literal["auto", "always", "never"] = "auto",
    ocr_language: str = "",
    profile: Literal["fast", "web", "balanced", "thorough", "news", "academic"] = "web",
    engines: str = "",
    ranking: Literal["source", "bm25", "fusion"] = "source",
    prefer_domains: list[str] | None = None,
    cache_mode: Literal["use", "refresh", "bypass"] = "use",
    max_age: float | None = None,
) -> Any:
    """Find pages and read them in one call.

    The usual shape of a research step, and cheaper than search-then-fetch
    because the engine reads only the results its ranking kept.
    """
    return await _backend_post("/search-and-fetch", {
        "query": query,
        "limit": _bounded_int(limit, 1, MAX_RESULTS),
        "max_chars": _bounded_int(max_chars, 1, MAX_CHARS),
        "rank": rank,
        "render": render,
        "fresh": fresh, "ocr_mode": ocr_mode, "ocr_language": ocr_language,
        "profile": profile, "engines": engines, "ranking": ranking,
        "prefer_domains": prefer_domains or [], "cache_mode": cache_mode, "max_age": max_age,
    })


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def research(
    question: str,
    queries: list[str] | None = None,
    max_sources: int = 6,
    max_chars: int = 5000,
    fresh: bool = False,
    follow_assets: bool = True,
    categories: Literal["", "news", "academic"] = "",
    response_format: Literal["detailed", "concise"] = "detailed",
) -> dict[str, Any]:
    """Gather cited sources and relevant excerpts across multiple searches.

    Returns an evidence bundle for the caller to assess and synthesize. No
    model writes a report. Optional queries are additional research facets.
    """
    if len(queries or []) > 3:
        raise ValueError("at most three research facets are supported")
    return await _backend_post("/research", {
        "question": question,
        "queries": queries or [],
        "max_sources": _bounded_int(max_sources, 1, 6),
        "max_chars": _bounded_int(max_chars, 500, 6000),
        "fresh": fresh, "follow_assets": follow_assets,
        "categories": categories, "response_format": response_format,
    })


class BrowserStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["goto", "click", "fill", "type", "press", "select", "check", "uncheck",
                    "hover", "wait", "wait_for", "text", "html", "attr", "count", "snapshot",
                    "url", "title", "download"]
    selector: str = Field(default="", max_length=1000)
    value: str = Field(default="", max_length=4000)
    url: str = Field(default="", max_length=2048)
    ms: int = Field(default=1000, ge=0, le=30000)
    delay_ms: int = Field(default=0, ge=0, le=1000)
    name: str = Field(default="", max_length=200)
    index: int = Field(default=0, ge=0, le=500)
    limit: int = Field(default=100, ge=1, le=200, description="Snapshot element limit")
    max_chars: int | None = Field(default=None, ge=1, le=120000,
                                 description="Text/HTML output limit; preserves existing defaults")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                      idempotentHint=False, openWorldHint=True))
async def drive(
    steps: list[BrowserStep] | None = None,
    session: str = "",
    url: str = "",
    allowed_hosts: list[str] | None = None,
    canaries: list[str] | None = None,
    screenshot: Literal["never", "failure", "canary", "always"] = "failure",
    screenshot_full_page: bool = False,
    include_events: bool = True,
    close_session: bool = False,
    timeout_ms: Annotated[int, Field(ge=1000, le=180000)] = 45000,
    operation_id: str = "",
    ocr_language: str = "",
) -> dict[str, Any]:
    """Operate a stateful browser using bounded steps and structured evidence.

    Use one session per target. If navigation omits a name, reuse the returned
    session.id for later snapshot/click/fill/read calls. Set allowed_hosts on
    the first navigation. screenshot is never, failure, canary, or always. A
    fill emits input and change. Close the session when done. Only public
    HTTP(S) navigation is accepted.
    """
    if operation_id and not session:
        raise ValueError("operation_id requires an explicit named session")
    clean_steps = [step.model_dump(exclude_none=True) if isinstance(step, BrowserStep)
                   else step for step in (steps or [])]
    if len(clean_steps) > 40 or any(not isinstance(step, dict) for step in clean_steps):
        raise ValueError("steps must contain at most 40 objects")
    hosts = allowed_hosts or []
    if len(hosts) > 32 or any(not _public_hostname(host) for host in hosts):
        raise ValueError("allowed_hosts must contain public hostnames")
    navigation_urls = ([url] if url else []) + [
        str(step.get("url")) for step in clean_steps
        if str(step.get("action", "")).lower() == "goto" and step.get("url")
    ]
    if navigation_urls and not hosts:
        raise ValueError("allowed_hosts is required for public browser navigation")
    if any(not _public_url(item) for item in navigation_urls):
        raise ValueError("public HTTP(S) navigation URLs are required")
    if any(not _hostname_allowed(item, hosts) for item in navigation_urls):
        raise ValueError("navigation URL must match allowed_hosts")
    if screenshot not in {"never", "failure", "canary", "always"}:
        raise ValueError("invalid screenshot mode")
    bounded_timeout = _bounded_int(timeout_ms, 1000, 180000)
    if not session and navigation_urls:
        session = f"auto-{secrets.token_hex(8)}"
    elif not session and clean_steps:
        raise ValueError(
            "session is required for stateful drive steps; navigate first "
            "and reuse the returned session.id"
        )
    internal_session = (
        _private_session_id(MCP_KEY_NAMESPACE.get(), session) if session else ""
    )
    payload = {
        "steps": clean_steps,
        "session": internal_session,
        "url": url,
        "allowed_hosts": hosts,
        "canaries": (canaries or [])[:20],
        "screenshot": screenshot,
        "screenshot_full_page": screenshot_full_page,
        "include_events": include_events,
        "close_session": close_session,
        "timeout_ms": bounded_timeout,
        "operation_id": operation_id, "ocr_language": ocr_language,
    }
    result = await _backend_post(
        "/drive", payload, timeout=max(REQUEST_TIMEOUT, bounded_timeout / 1000 + 20)
    )
    if session and isinstance(result, dict):
        returned_session = result.get("session")
        if isinstance(returned_session, dict) and returned_session.get("id") == internal_session:
            returned_session["id"] = session
    return result


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def read_document(document_id: str, focus: str = "", offset: int = 0,
                        max_chars: Annotated[int, Field(ge=1, le=120000)] = 12000,
                        response_format: Literal["detailed", "concise"] = "detailed",
                        reparse: bool = False, row_start: int = 1, row_end: int | None = None,
                        sheet: str = "", max_cell_chars: int | None = None,
                        page_start: int = 1, page_end: int | None = None,
                        ocr_mode: Literal["auto", "always", "never"] = "auto",
                        ocr_language: str = ""
                        ) -> dict[str, Any]:
    """Reopen retained source evidence without another origin request.

    Use focus for a new question or offset/next_offset to continue reading.
    The document hash identifies the retained version, not current web freshness.
    """
    return await _backend_post("/documents/read", {"document_id": document_id,
        "focus": focus, "offset": offset, "max_chars": max_chars,
        "response_format": response_format, "reparse": reparse, "row_start": row_start,
        "row_end": row_end, "sheet": sheet, "max_cell_chars": max_cell_chars,
        "page_start": page_start, "page_end": page_end, "ocr_mode": ocr_mode,
        "ocr_language": ocr_language})


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def view_document_image(document_id: str, page: int = 1,
                              crop: tuple[int,int,int,int] | None = None,
                              max_dimension: int = 2400) -> CallToolResult:
    """Inspect retained PDF/image pixels to verify OCR, charts and numeric tables.

    Requires source bytes retained by a browser download. Crop coordinates refer
    to the original rendered image before scaling; PDF pages render at 200 DPI.
    """
    result = await _backend_post("/documents/image", {"document_id": document_id,
        "page": page, "crop": crop, "max_dimension": max_dimension})
    pixels = result.pop("image_b64")
    return CallToolResult(content=[TextContent(type="text",text=json.dumps(result)),
                                  ImageContent(type="image",data=pixels,mimeType="image/png")])


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def start_fetch_job(urls: list[str], operation_id: str = "", focus: str = "",
                           render: Literal["auto", "always", "never"] = "auto",
                           max_chars: Annotated[int, Field(ge=1, le=120000)] = 12000,
                           wait_for: str = "", fresh: bool = False,
                           ocr_language: str = "", page_start: int = 1,
                           ocr_mode: Literal["auto", "always", "never"] = "auto",
                           page_end: int | None = None,
                           headed_fallback: bool = False,
                           row_start: int = 1, row_end: int | None = None, sheet: str = "",
                           max_cell_chars: int | None = None) -> dict[str, Any]:
    """Start durable page reads and receive sources as they finish via read_fetch_job.

    Reuse an operation_id only for retrying the identical request. Continue
    polling to read every source; an early useful source need not end coverage.
    """
    return await _backend_post("/jobs/fetch", {"urls": _bounded_urls(urls),
        "operation_id": operation_id, "focus": focus, "render": render,
        "max_chars": max_chars, "wait_for": wait_for, "fresh": fresh,
        "ocr_language": ocr_language, "page_start": page_start, "page_end": page_end,
        "ocr_mode": ocr_mode,
        "headed_fallback": headed_fallback, "row_start": row_start,
        "row_end": row_end, "sheet": sheet, "max_cell_chars": max_cell_chars})


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def read_fetch_job(job_id: str, cursor: int = 0) -> dict[str, Any]:
    """Read new completed sources; reuse next_cursor and respect poll_after_ms.

    Results persist for 24 hours across client disconnects. A server restart
    marks unfinished jobs interrupted; already completed sources remain readable.
    """
    return await _backend_post("/jobs/read", {"job_id": job_id, "cursor": cursor})


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True))
async def cancel_fetch_job(job_id: str) -> dict[str, Any]:
    """Stop scheduling new reads. In-flight network/OCR calls may still finish."""
    return await _backend_post("/jobs/cancel", {"job_id": job_id})


@mcp.tool()
async def corpus_search(query: str, limit: int = 5, floor: float | None = None,
                        mode: Literal["auto", "semantic", "lexical"] = "auto") -> Any:
    """Search passages already stored in the local semantic corpus."""
    params: dict[str, Any] = {"q": query, "limit": _bounded_int(limit, 1, 50), "mode": mode}
    if floor is not None:
        params["floor"] = float(floor)
    return await _backend_get("/corpus/search", params)


@mcp.tool()
async def corpus_stats() -> dict[str, Any]:
    """Return local corpus page and passage counts."""
    return await _backend_get("/corpus/stats")


@mcp.tool()
async def ready() -> dict[str, Any]:
    """Return search-source readiness, distinct from process liveness."""
    return await _backend_get("/ready")


@mcp.tool()
async def capabilities() -> dict[str, Any]:
    """List installed search, read, browser-drive, and extraction capabilities."""
    return await _backend_get("/v2/capabilities")


@mcp.tool()
async def status() -> dict[str, Any]:
    """Return configured components, providers, and profiles."""
    return await _backend_get("/v2/status")


@mcp.tool()
async def stats() -> dict[str, Any]:
    """Return cache, fetch-tier, budget, and domain-health counters."""
    return await _backend_get("/stats")












app = AccessMiddleware(BearerAuthMiddleware(mcp.streamable_http_app()))
