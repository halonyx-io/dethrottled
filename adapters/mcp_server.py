from __future__ import annotations

import contextvars
import hashlib
import ipaddress
import json
import logging
import os
import secrets
import socket
import time
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

import httpx
from dethrottled_access import (
    CLAIMS,
    REQUEST_ID,
    AccessMiddleware,
    automatic_session,
    require_scope,
)
from dethrottled_version import __version__ as ADAPTER_VERSION
from dethrottled_workflow import INSTRUCTIONS as AGENT_WORKFLOW
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse

# Keep the default backend local; Compose supplies its private service address.
MCP_BACKEND_URL = os.getenv("MCP_BACKEND_URL", "http://127.0.0.1:8787").rstrip("/")
KEYS_PATH = Path(os.getenv("MCP_KEYS_PATH", "/etc/dethrottled-mcp/keys.json"))
REQUEST_TIMEOUT = float(os.getenv("MCP_REQUEST_TIMEOUT", "90"))
MAX_URLS = int(os.getenv("MCP_MAX_URLS", "10"))
MAX_RESULTS = min(15, int(os.getenv("MCP_MAX_RESULTS", "15")))
MAX_CHARS = int(os.getenv("MCP_MAX_CHARS", "1000000"))
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv(
        "MCP_ALLOWED_HOSTS",
        "127.0.0.1:*,localhost:*,[::1]:*",
    ).split(",")
    if host.strip()
]


SDK_VERSION = package_version("mcp")


_BACKEND_IDENTITY = {}
_BACKEND_IDENTITY_AT = 0.0


async def backend_identity():
    global _BACKEND_IDENTITY, _BACKEND_IDENTITY_AT
    now = time.monotonic()
    if _BACKEND_IDENTITY and now - _BACKEND_IDENTITY_AT < 10:
        return _BACKEND_IDENTITY
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            response = await client.get(MCP_BACKEND_URL + "/health")
            response.raise_for_status()
            observed = response.json().get("version")
            if not isinstance(observed, str) or not observed:
                raise ValueError("missing backend version")
        result = {"version": observed,
                  "status": "match" if observed == ADAPTER_VERSION else "mismatch"}
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
        result = {"version": None, "status": "unavailable", "reason": type(exc).__name__}
    if result != _BACKEND_IDENTITY and result["status"] != "match":
        logging.getLogger(__name__).warning(
            "MCP backend identity %s: adapter=%s backend=%s", result["status"],
            ADAPTER_VERSION, result.get("version"))
    _BACKEND_IDENTITY, _BACKEND_IDENTITY_AT = result, now
    return result


class BackendIdentityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            original_receive = receive

            async def receive():
                message = await original_receive()
                if message["type"] == "lifespan.startup":
                    await backend_identity()
                return message
        await self.app(scope, receive, send)


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
            response = JSONResponse({"status": "ok", "service": "dethrottled-mcp",
                                     "version": ADAPTER_VERSION, "sdk_version": SDK_VERSION,
                                     "backend": await backend_identity()})
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
    shared_read = automatic_session(namespace, session)
    if shared_read:
        return shared_read
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
    if path in {"/fetch", "/extract-with-links", "/drive", "/jobs/fetch", "/site/crawl",
                "/documents/read", "/documents/image"}:
        payload = dict(payload, public_only=True)
    if path in {"/fetch", "/extract-with-links", "/research", "/search-and-fetch",
                "/documents/read", "/documents/image", "/jobs/fetch", "/jobs/read",
                "/jobs/cancel", "/jobs/resume", "/documents/structure", "/site/crawl", "/drive"}:
        payload = dict(payload, evidence_namespace=CLAIMS.get()["namespace"])
    if path in {"/fetch", "/extract-with-links", "/research", "/search-and-fetch"}:
        timeout = max(timeout or REQUEST_TIMEOUT,
                      600 if path in {"/research", "/search-and-fetch"} else 240)
    async with httpx.AsyncClient(
        timeout=timeout or REQUEST_TIMEOUT, trust_env=False
    ) as client:
        response = await client.post(f"{MCP_BACKEND_URL}{path}", json=payload,
                                     headers={"X-Request-ID": REQUEST_ID.get()})
        return _backend_result(response)





def _compact_tool_result(result):
    """Keep every content block and structured payload; compact JSON text only."""
    def blocks(items):
        out = []
        for block in items:
            if isinstance(block, TextContent):
                try:
                    value = json.loads(block.text)
                except (ValueError, TypeError):
                    pass
                else:
                    block = block.model_copy(update={"text": json.dumps(
                        value, ensure_ascii=False, separators=(",", ":"))})
            out.append(block)
        return out

    if isinstance(result, CallToolResult):
        return result.model_copy(update={"content": blocks(result.content)})
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
        return blocks(result[0]), result[1]
    if isinstance(result, (list, tuple)):
        return blocks(result)
    return result


class StrictFastMCP(FastMCP):
    """Validate unexpected tool arguments before the SDK can silently drop them."""
    async def call_tool(self, name, arguments):
        return _compact_tool_result(await super().call_tool(name, arguments))

    def add_tool(self, fn, *args, **kwargs):
        super().add_tool(fn, *args, **kwargs)
        name = kwargs.get("name") or (args[0] if args else None) or fn.__name__
        tool = self._tool_manager.get_tool(name)
        model = tool.fn_metadata.arg_model
        model.model_config["extra"] = "forbid"
        model.model_rebuild(force=True)
        tool.parameters = model.model_json_schema(by_alias=True)


mcp = StrictFastMCP(
    "dethrottled MCP",
    # engine_*, not web_*: OpenClaw ships built-in web_search and web_fetch, and
    # a same-named MCP tool is a needless collision in an agent's tool list.
    # Named for the role rather than the backend, so repointing this bridge does
    # not make every tool name wrong again.
    instructions=AGENT_WORKFLOW,
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(allowed_hosts=ALLOWED_HOSTS),
)


# SDK 1.x exposes version on its low-level server, not the FastMCP constructor.
# Keep the wire application identity distinct from the SDK dependency version.
mcp._mcp_server.version = ADAPTER_VERSION




@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def search(
    query: str,
    limit: Annotated[int, Field(ge=1, le=MAX_RESULTS)] = 15,
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
    max_chars: Annotated[int, Field(ge=1, le=MAX_CHARS)] = 12000,
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
    recovery: Literal["auto", "manual"] = "auto",
    ocr_language: str = "",
    document_mode: Literal["auto", "native", "layout"] = "auto",
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
    Bounded recovery is automatic; recovery=manual leaves acquisition to you.
    Follow workflow.next_actions for exact continuation/render/page/row calls.
    Detected challenges use the headed browser automatically; headed_fallback also
    requests it for other failures. Use format=html or format=links, not REST aliases.
    quality=ok is extraction success, not proof the answer exists. If truncated,
    use read_document with next_offset; for uncertain OCR inspect source pixels
    when retained, or drive/capture the source. Preserve partial-read warnings.

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
        "focus": focus, "response_format": response_format, "recovery": recovery,
        "ocr_language": ocr_language,
        "page_start": page_start, "page_end": page_end, "ocr_mode": ocr_mode,
        "document_mode": document_mode,
        "row_start": row_start, "row_end": row_end, "sheet": sheet,
        "max_cell_chars": max_cell_chars,
    })


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def extract_with_links(
    urls: list[str],
    max_chars: Annotated[int, Field(ge=1, le=MAX_CHARS)] = 12000,
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
    limit: Annotated[int, Field(ge=1, le=MAX_RESULTS)] = 5,
    max_chars: Annotated[int, Field(ge=1, le=MAX_CHARS)] = 3000,
    rank: bool = False,
    render: Literal["auto", "always", "never"] = "auto",
    fresh: bool = False,
    document_mode: Literal["auto", "native", "layout"] = "auto",
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
        "fresh": fresh, "ocr_mode": ocr_mode,
        "document_mode": document_mode, "ocr_language": ocr_language,
        "profile": profile, "engines": engines, "ranking": ranking,
        "prefer_domains": prefer_domains or [], "cache_mode": cache_mode, "max_age": max_age,
    })


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def research(
    question: str,
    queries: list[str] | None = None,
    max_sources: Annotated[int, Field(ge=1, le=20)] = 10,
    max_chars: Annotated[int, Field(ge=500, le=120000)] = 12000,
    fresh: bool = False,
    engines: str = "",
    profile: Literal["web", "balanced", "thorough", "academic", "news"] = "web",
    follow_assets: bool = True,
    categories: Literal["", "news", "academic"] = "",
    response_format: Literal["detailed", "concise"] = "detailed",
) -> dict[str, Any]:
    """Gather cited sources and relevant excerpts across multiple searches.

    Returns an evidence bundle for the caller to assess and synthesize. No
    model writes a report. Optional queries are additional research facets.
    coverage distinguishes readable evidence, unread candidates and failures.
    It never verifies answers.
    """
    if len(queries or []) > 10:
        raise ValueError("at most ten research facets are supported")
    return await _backend_post("/research", {
        "question": question,
        "queries": queries or [],
        "max_sources": _bounded_int(max_sources, 1, 20),
        "max_chars": _bounded_int(max_chars, 500, 120000),
        "fresh": fresh, "follow_assets": follow_assets, "engines": engines, "profile": profile,
        "categories": categories, "response_format": response_format,
    }, timeout=600)


class BrowserStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["goto", "click", "fill", "type", "press", "select", "check", "uncheck",
                    "hover", "wait", "wait_for", "text", "html", "attr", "count", "snapshot",
                    "url", "title", "download", "network", "checkpoint",
                    "tabs", "switch_tab", "history", "read_state", "scroll", "expand_details"]
    frame: str = Field(default="", max_length=1000,
                       description="CSS selector for an allowed iframe")
    selector: str = Field(default="", max_length=1000)
    value: str = Field(default="", max_length=4000)
    url: str = Field(default="", max_length=2048)
    ms: int = Field(default=1000, ge=0, le=30000)
    delay_ms: int = Field(default=0, ge=0, le=1000)
    name: str = Field(default="", max_length=200)
    index: int = Field(default=0, ge=0, le=500)
    limit: int = Field(default=10, ge=1, le=10, description="Snapshot/network list limit")
    max_chars: int | None = Field(default=None, ge=1, le=1000000,
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

    read_state inspects loading/details/scroll state; scroll moves up/down;
    expand_details opens up to two visible standard HTML details sections.
    Ordinary fetch uses these automatically for observed gaps; use drive for
    deliberate application-specific operations.

    Use one session per target. If navigation omits a name, reuse the returned
    session.id for later snapshot/click/fill/read calls. Set allowed_hosts on
    the first navigation, or omit it to derive hosts from validated URLs.
    Host entries omit ports. screenshot is never, failure, canary, or always. A
    fill emits input and change. Close the session when done. Only public
    HTTP(S) navigation is accepted. Use snapshot to find an export control;
    action=download with its selector captures the file and returns document_id.
    Then read_document can select PDF pages/table rows, and view_document_image
    checks source pixels. Use screenshot=always when visual evidence is needed.
    action=network lists same-host fetch/XHR responses; name=body reads a selected
    response. Set selector to its stable response_id (index is a weaker alternative),
    optionally filter its URL with value. It captures
    only responses observed since this session began, and never returns headers.
    A captured body returns document_id for read_document/inspect_document.
    action=checkpoint saves cookies/localStorage/IndexedDB/sessionStorage for restart recovery.
    Set frame to an iframe CSS selector. tabs/switch_tab handle popups; history lists outcomes.
    Reuse the session to restore its saved host scope; close_session deletes it.
    """
    if operation_id and not session:
        raise ValueError("operation_id requires an explicit named session")
    clean_steps = [step.model_dump(exclude_none=True) if isinstance(step, BrowserStep)
                   else step for step in (steps or [])]
    if len(clean_steps) > 40 or any(not isinstance(step, dict) for step in clean_steps):
        raise ValueError("steps must contain at most 40 objects")
    hosts = allowed_hosts or []
    navigation_urls = ([url] if url else []) + [
        str(step.get("url")) for step in clean_steps
        if str(step.get("action", "")).lower() == "goto" and step.get("url")
    ]
    if any(not _public_url(item) for item in navigation_urls):
        raise ValueError("public HTTP(S) navigation URLs are required")
    if navigation_urls and not hosts:
        hosts = sorted({urlsplit(item).hostname.lower() for item in navigation_urls})
    if len(hosts) > 32 or any(not _public_hostname(host) for host in hosts):
        raise ValueError("allowed_hosts must contain public hostnames without ports; "
                         "omit allowed_hosts to derive it from validated navigation URLs")
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
    # Preserve the object output contract while making pixels consumable by
    # MCP vision clients, rather than burying base64 in a text-only object.
    screenshot = result.pop("screenshot_b64", None)
    if screenshot:
        return CallToolResult(content=[
            TextContent(type="text", text=json.dumps(result, ensure_ascii=False)),
            ImageContent(type="image", data=screenshot, mimeType="image/png")],
            structuredContent=result)
    return result


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def read_document(document_id: str, focus: str = "", offset: int = 0,
                        max_chars: Annotated[int, Field(ge=1, le=1000000)] = 12000,
                        response_format: Literal["detailed", "concise"] = "detailed",
                        reparse: bool = False, row_start: int = 1, row_end: int | None = None,
                        sheet: str = "", max_cell_chars: int | None = None,
                        page_start: int = 1, page_end: int | None = None,
                        document_mode: Literal["auto", "native", "layout"] = "auto",
    ocr_mode: Literal["auto", "always", "never"] = "auto",
                        ocr_language: str = ""
                        ) -> dict[str, Any]:
    """Reopen retained source evidence without another origin request.

    Use focus for a new question or offset/next_offset to continue reading.
    Follow workflow.next_actions for later text/pages/rows. Reparse controls need
    source bytes; missing bytes are reacquired automatically if their hash still
    matches the retained version. Otherwise refetch the current source or capture
    a browser export. The document hash identifies the retained
    version, not current web freshness.
    """
    return await _backend_post("/documents/read", {"document_id": document_id,
        "focus": focus, "offset": offset, "max_chars": max_chars,
        "response_format": response_format, "reparse": reparse, "row_start": row_start,
        "row_end": row_end, "sheet": sheet, "max_cell_chars": max_cell_chars,
        "page_start": page_start, "page_end": page_end, "ocr_mode": ocr_mode,
        "document_mode": document_mode,
        "ocr_language": ocr_language})


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def view_document_image(document_id: str, page: int = 1,
                              crop: tuple[int,int,int,int] | None = None,
                              max_dimension: int = 2400) -> CallToolResult:
    """Inspect retained PDF/image pixels to verify OCR, charts and numeric tables.

    Uses captured source bytes or automatically reacquires a hashed HTTP source.
    A changed source returns a version conflict rather than misleading pixels.
    Crop coordinates refer
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
                           max_chars: Annotated[int, Field(ge=1, le=1000000)] = 12000,
                           wait_for: str = "", fresh: bool = False,
                           ocr_language: str = "", page_start: int = 1,
                           document_mode: Literal["auto", "native", "layout"] = "auto",
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
        "document_mode": document_mode,
        "headed_fallback": headed_fallback, "row_start": row_start,
        "row_end": row_end, "sheet": sheet, "max_cell_chars": max_cell_chars})


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def read_fetch_job(job_id: str, cursor: int = 0) -> dict[str, Any]:
    """Read new completed sources; reuse next_cursor and respect poll_after_ms.

    Results persist for 24 hours across client disconnects. A server restart
    marks unfinished jobs interrupted; already completed sources remain readable.
    Use resume_fetch_job when resume_available is true.
    """
    return await _backend_post("/jobs/read", {"job_id": job_id, "cursor": cursor})


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True))
async def cancel_fetch_job(job_id: str) -> dict[str, Any]:
    """Stop scheduling new reads. In-flight network/OCR calls may still finish."""
    return await _backend_post("/jobs/cancel", {"job_id": job_id})


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def resume_fetch_job(job_id: str) -> dict[str, Any]:
    """Resume an interrupted/cancelled read job, retaining completed source rows.

    Only missing source positions are fetched. This resumes reads, never browser
    mutations. Poll read_fetch_job afterward using the previous next_cursor.
    """
    return await _backend_post("/jobs/resume", {"job_id": job_id})


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def inspect_document(document_id: str, focus: str = "", offset: int = 0,
                           limit: Annotated[int, Field(ge=1, le=100)] = 30) -> dict[str, Any]:
    """Get structured retained-text blocks, exact quotes and versioned citation selectors.

    Use after fetch/read_document for precise evidence, headings and table rows.
    Offsets refer to canonical retained text, not HTML bytes or inferred geometry.
    A returned_row is an extraction ordinal, not a physical spreadsheet row.
    """
    return await _backend_post("/documents/structure", {"document_id": document_id,
        "focus": focus, "offset": offset, "limit": limit})


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def crawl_site(urls: list[str],
                     max_pages: Annotated[int, Field(ge=1, le=50)] = 10,
                     max_depth: Annotated[int, Field(ge=0, le=5)] = 2,
                     path_prefix: str = "/",
                     render: Literal["auto", "always", "never"] = "auto") -> dict[str, Any]:
    """Discover and retain linked/sitemap sources within one site and report coverage.

    Supply seed URLs from one origin, optionally a sitemap.xml. Returns document
    handles, failed sources, frontier and explicit limits; follow read_document
    to inspect evidence. Whole-site completeness is unknown even if the observed
    frontier is exhausted. Use bounded repeated runs for continuation_urls.
    """
    return await _backend_post("/site/crawl", {"urls": _bounded_urls(urls),
        "max_pages": max_pages, "max_depth": max_depth, "path_prefix": path_prefix,
        "render": render}, timeout=600)


@mcp.tool()
async def corpus_search(query: str,
                        limit: Annotated[int, Field(ge=1, le=10)] = 5, floor: float | None = None,
                        mode: Literal["auto", "semantic", "lexical", "hybrid"] = "auto",
                        domains: list[str] | None = None,
                        support: Literal["standard", "broad"] = "standard") -> Any:
    """Search public evidence. Broad support includes warned single-model candidates.

    Start with standard; when empty or incomplete, use broad to inspect possible
    cross-language matches, or rewrite/search the web. Matches do not verify answers.
    """
    params: dict[str, Any] = {"q": query, "limit": _bounded_int(limit, 1, 10), "mode": mode}
    if support != "standard":
        params["support"] = support
    if floor is not None:
        params["floor"] = float(floor)
    if domains:
        params["domains"] = ",".join(domains)
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












app = BackendIdentityMiddleware(AccessMiddleware(
    BearerAuthMiddleware(mcp.streamable_http_app())))
