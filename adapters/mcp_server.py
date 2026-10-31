from __future__ import annotations

import contextvars
import hashlib
import ipaddress
import os
import secrets
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from dethrottled_access import CLAIMS, REQUEST_ID, AccessMiddleware, require_scope
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

# The bridge and dethrottled run on szbox. Keep the fallback local too, so a
# missing EnvironmentFile cannot silently send research to the old Q6A host.
MCP_BACKEND_URL = os.getenv("MCP_BACKEND_URL", "http://127.0.0.1:8787").rstrip("/")
KEYS_PATH = Path(os.getenv("MCP_KEYS_PATH", "/etc/dethrottled-mcp/keys.json"))
REQUEST_TIMEOUT = float(os.getenv("MCP_REQUEST_TIMEOUT", "90"))
MAX_URLS = int(os.getenv("MCP_MAX_URLS", "10"))
MAX_RESULTS = int(os.getenv("MCP_MAX_RESULTS", "10"))
MAX_CHARS = int(os.getenv("MCP_MAX_CHARS", "50000"))
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
    response.raise_for_status()
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
    if path in {"/fetch", "/extract-with-links", "/drive"}:
        payload = dict(payload, public_only=True)
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




@mcp.tool()
async def search(
    query: str,
    limit: int = 10,
    fresh: bool = False,
    rank: bool = False,
    corpus: int = 0,
    recency: float = 0.0,
    categories: str = "",
    language: str = "",
    profile: str = "web",
    engines: str = "",
    ranking: str = "source",
    prefer_domains: list[str] | None = None,
    diagnostics: bool = False,
    cache_mode: str = "use",
    max_age: float | None = None,
) -> Any:
    """Find pages. Returns ranked results with url, title and snippet.

    To read the results as well, prefer search_and_fetch: one call instead of
    two, and the engine reads only what its own ranking kept.
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


@mcp.tool()
async def fetch(
    urls: list[str],
    max_chars: int = 12000,
    format: str = "text",
    render: str = "auto",
    fresh: bool = False,
    cache_mode: str = "use",
    max_age: float | None = None,
    wait_for: str = "",
    render_delay: float = 0.5,
    headed_fallback: bool = False,
) -> Any:
    """Read pages you already have URLs for.

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
    })


@mcp.tool()
async def extract_with_links(
    urls: list[str],
    max_chars: int = 12000,
    render: str = "auto",
    fresh: bool = False,
) -> Any:
    """Read public URLs while retaining resolved outbound links."""
    return await _backend_post("/extract-with-links", {
        "urls": _bounded_urls(urls),
        "max_chars": _bounded_int(max_chars, 1, MAX_CHARS),
        "render": render,
        "fresh": fresh,
    })


@mcp.tool()
async def search_and_fetch(
    query: str,
    limit: int = 5,
    max_chars: int = 3000,
    rank: bool = False,
    render: str = "auto",
    fresh: bool = False,
    profile: str = "web",
    engines: str = "",
    ranking: str = "source",
    prefer_domains: list[str] | None = None,
    cache_mode: str = "use",
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
        "fresh": fresh,
        "profile": profile, "engines": engines, "ranking": ranking,
        "prefer_domains": prefer_domains or [], "cache_mode": cache_mode, "max_age": max_age,
    })


@mcp.tool()
async def research(
    question: str,
    queries: list[str] | None = None,
    max_sources: int = 6,
    max_chars: int = 5000,
    fresh: bool = False,
) -> Any:
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
        "fresh": fresh,
    })


@mcp.tool()
async def drive(
    steps: list[dict[str, Any]] | None = None,
    session: str = "",
    url: str = "",
    allowed_hosts: list[str] | None = None,
    canaries: list[str] | None = None,
    screenshot: str = "failure",
    screenshot_full_page: bool = False,
    include_events: bool = True,
    close_session: bool = False,
    timeout_ms: int = 45000,
) -> Any:
    """Operate a stateful browser using bounded steps and structured evidence.

    Use one session per target. If navigation omits a name, reuse the returned
    session.id for later snapshot/click/fill/read calls. Set allowed_hosts on
    the first navigation. screenshot is never, failure, canary, or always. A
    fill emits input and change. Close the session when done. Only public
    HTTP(S) navigation is accepted.
    """
    clean_steps = steps or []
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
    }
    result = await _backend_post(
        "/drive", payload, timeout=max(REQUEST_TIMEOUT, bounded_timeout / 1000 + 20)
    )
    if session and isinstance(result, dict):
        returned_session = result.get("session")
        if isinstance(returned_session, dict) and returned_session.get("id") == internal_session:
            returned_session["id"] = session
    return result


@mcp.tool()
async def corpus_search(query: str, limit: int = 5, floor: float | None = None,
                        mode: str = "auto") -> Any:
    """Search passages already stored in the local semantic corpus."""
    params: dict[str, Any] = {"q": query, "limit": _bounded_int(limit, 1, 50), "mode": mode}
    if floor is not None:
        params["floor"] = float(floor)
    return await _backend_get("/corpus/search", params)


@mcp.tool()
async def corpus_stats() -> Any:
    """Return local corpus page and passage counts."""
    return await _backend_get("/corpus/stats")


@mcp.tool()
async def ready() -> Any:
    """Return search-source readiness, distinct from process liveness."""
    return await _backend_get("/ready")


@mcp.tool()
async def capabilities() -> Any:
    """List installed search, read, browser-drive, and extraction capabilities."""
    return await _backend_get("/v2/capabilities")


@mcp.tool()
async def status() -> Any:
    """Return configured components, providers, and profiles."""
    return await _backend_get("/v2/status")


@mcp.tool()
async def stats() -> Any:
    """Return cache, fetch-tier, budget, and domain-health counters."""
    return await _backend_get("/stats")












app = AccessMiddleware(BearerAuthMiddleware(mcp.streamable_http_app()))
