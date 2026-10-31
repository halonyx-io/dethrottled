"""Bounded bearer-authenticated public surface for local dethrottled."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import secrets
import socket
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dethrottled_access import CLAIMS, REQUEST_ID, AccessMiddleware
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

BACKEND = os.getenv('MCP_BACKEND_URL', 'http://127.0.0.1:8787')
TOKEN_FILE = Path('/etc/halonyx-api-gateway/token-hashes.json')
MAX_BODY = 262_144
MAX_URLS = 10
MAX_QUERY = 500
SLOTS = asyncio.Semaphore(8)
POST_PATHS = {
    '/documents/read', '/documents/image', '/documents/structure', '/site/crawl',
    '/jobs/fetch', '/jobs/read', '/jobs/cancel', '/jobs/resume',
    '/drive',
    '/extract',
    '/extract-with-links',
    '/fetch',
    '/research',
    '/search',
    '/v2/search',
    '/search-and-extract',
    '/search-and-fetch',
}
GET_PATHS = {
    '/corpus/search',
    '/corpus/stats',
    '/openapi.json',
    '/ready',
    '/stats',
    '/v2/capabilities',
    '/v2/status',
}
FETCH_PATHS = {'/jobs/fetch', '/fetch', '/extract', '/extract-with-links'}
SEARCH_PATHS = {'/search', '/v2/search', '/search-and-fetch', '/search-and-extract'}


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(AccessMiddleware)


def token_namespace(request: Request) -> str | None:
    claims = CLAIMS.get()
    return claims["namespace"] if claims else None


def private_session_id(namespace: str, session: str) -> str:
    digest = hashlib.sha256(session.encode()).hexdigest()[:32]
    prefix = 'auto-a' if session.startswith('auto-') else 'a'
    return f'{prefix}{namespace[:12]}-{digest}'


def public_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
            return False
        if parsed.username or parsed.password or parsed.fragment:
            return False
        if parsed.port not in {None, 80, 443}:
            return False
        hostname = parsed.hostname.rstrip('.').lower()
        if hostname in {'localhost', 'localhost.localdomain'} or hostname.endswith(
            ('.localhost', '.local', '.lan', '.home', '.internal')
        ):
            return False
        addresses = socket.getaddrinfo(
            hostname, parsed.port or (443 if parsed.scheme == 'https' else 80),
            type=socket.SOCK_STREAM)
        return bool(addresses) and all(
            ipaddress.ip_address(row[4][0]).is_global for row in addresses)
    except (ValueError, OSError, UnicodeError):
        return False


def public_hostname(value: str) -> bool:
    if not isinstance(value, str):
        return False
    hostname = value.strip().lower().rstrip('.')
    if hostname.startswith('*.'):
        hostname = hostname[2:]
    if not hostname or '/' in hostname or ':' in hostname:
        return False
    return public_url('https://' + hostname)


def hostname_allowed(url: str, allowed_hosts: list[str]) -> bool:
    try:
        host = (urlsplit(url).hostname or '').lower().rstrip('.')
    except ValueError:
        return False
    for raw in allowed_hosts:
        pattern = raw.lower().strip().rstrip('.')
        if pattern.startswith('*.'):
            root = pattern[2:]
            if host == root or host.endswith('.' + root):
                return True
        elif host == pattern:
            return True
    return False


def validate_drive(payload: dict) -> str | None:
    steps = payload.get('steps', [])
    if not isinstance(steps, list) or len(steps) > 40 or any(
            not isinstance(step, dict) for step in steps):
        return 'invalid drive steps'
    allowed_hosts = payload.get('allowed_hosts', [])
    if not isinstance(allowed_hosts, list) or len(allowed_hosts) > 32 or any(
            not public_hostname(host) for host in allowed_hosts):
        return 'public allowed_hosts required'
    navigation_urls = []
    if payload.get('url'):
        navigation_urls.append(payload['url'])
    navigation_urls.extend(
        step.get('url') for step in steps
        if step.get('action', '').lower() == 'goto' and step.get('url')
    )
    if any(not isinstance(url, str) or len(url) > 2048 or not public_url(url)
           for url in navigation_urls):
        return 'public HTTP(S) navigation URLs required'
    if navigation_urls and not allowed_hosts:
        allowed_hosts = sorted({urlsplit(url).hostname.lower() for url in navigation_urls})
        payload['allowed_hosts'] = allowed_hosts
    if any(not hostname_allowed(url, allowed_hosts) for url in navigation_urls):
        return 'navigation URL must match allowed_hosts'
    return None


async def upstream(
    method: str,
    path: str,
    payload: dict | None = None,
    params: list[tuple[str, str]] | None = None,
    session_alias: tuple[str, str] | None = None,
) -> Response:
    try:
        await asyncio.wait_for(SLOTS.acquire(), timeout=0.1)
    except asyncio.TimeoutError:
        return JSONResponse({'error': 'busy'}, status_code=429, headers={'Retry-After': '5'})
    try:
        timeout = 240.0
        if path == '/drive' and payload:
            timeout = max(timeout, float(payload.get('timeout_ms', 45_000)) / 1000 + 20)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.request(
                method, BACKEND + path, json=payload, params=params,
                headers={"X-Request-ID": REQUEST_ID.get()}
            )
        content = response.content
        if session_alias and response.headers.get('content-type', '').startswith(
                'application/json'):
            try:
                data = response.json()
                session = data.get('session') if isinstance(data, dict) else None
                if isinstance(session, dict) and session.get('id') == session_alias[0]:
                    session['id'] = session_alias[1]
                    content = json.dumps(data, separators=(',', ':')).encode()
            except ValueError:
                pass
        return Response(content, status_code=response.status_code,
                        media_type='application/json', headers={'Cache-Control': 'no-store'})
    except httpx.HTTPError:
        return JSONResponse({'error': 'backend unavailable'}, status_code=502)
    finally:
        SLOTS.release()


@app.get('/health')
def health():
    return {'status': 'ok', 'service': 'halonyx-api-gateway'}


@app.api_route('/{path:path}', methods=['GET', 'POST'])
async def dispatch(path: str, request: Request):
    route = '/' + path
    namespace = token_namespace(request)
    if namespace is None:
        return JSONResponse({'error': 'unauthorized'}, status_code=401,
                            headers={'WWW-Authenticate': 'Bearer'})
    if request.method == 'GET':
        if route not in GET_PATHS:
            return JSONResponse({'error': 'not found'}, status_code=404)
        if route == '/corpus/search':
            query = request.query_params.get('q', '')
            if not 0 < len(query.strip()) <= MAX_QUERY:
                return JSONResponse({'error': 'invalid query'}, status_code=400)
        return await upstream('GET', route, params=list(request.query_params.multi_items()))
    if route not in POST_PATHS:
        return JSONResponse({'error': 'not found'}, status_code=404)
    body = await request.body()
    if not body or len(body) > MAX_BODY:
        return JSONResponse({'error': 'invalid body size'}, status_code=413)
    try:
        payload = json.loads(body)
    except ValueError:
        return JSONResponse({'error': 'invalid JSON'}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({'error': 'JSON object required'}, status_code=400)
    if route in SEARCH_PATHS | {'/research'}:
        query = payload.get('question' if route == '/research' else 'query')
        if not isinstance(query, str) or not 0 < len(query.strip()) <= MAX_QUERY:
            return JSONResponse({'error': 'invalid query'}, status_code=400)
        if route in SEARCH_PATHS and 'limit' in payload and (
                type(payload['limit']) is not int or not 1 <= payload['limit'] <= 10):
            return JSONResponse({'error': 'invalid limit'}, status_code=400)
        if route == '/research':
            queries = payload.get('queries', [])
            if (not isinstance(queries, list) or len(queries) > 3 or
                    any(not isinstance(q, str) or not 0 < len(q.strip()) <= MAX_QUERY
                        for q in queries)):
                return JSONResponse({'error': 'invalid research queries'}, status_code=400)
            sources = payload.get('max_sources', 6)
            chars = payload.get('max_chars', 5000)
            if (type(sources) is not int or not 1 <= sources <= 6 or
                    type(chars) is not int or not 500 <= chars <= 6000):
                return JSONResponse({'error': 'invalid research limits'}, status_code=400)
    elif route in FETCH_PATHS | {'/site/crawl'}:
        urls = payload.get('urls')
        if not isinstance(urls, list) or not 1 <= len(urls) <= MAX_URLS:
            return JSONResponse({'error': 'invalid URLs'}, status_code=400)
        if any(not isinstance(url, str) or len(url) > 2048 or not public_url(url) for url in urls):
            return JSONResponse({'error': 'public HTTP(S) URLs required'}, status_code=400)
    elif route == '/drive':
        payload = dict(payload, public_only=True, evidence_namespace=namespace)
        error = validate_drive(payload)
        if error:
            return JSONResponse({'error': error}, status_code=400)
        logical_session = payload.get('session', '')
        navigation = bool(payload.get('url')) or any(
            step.get('action', '').lower() == 'goto' and step.get('url')
            for step in payload.get('steps', [])
        )
        if not logical_session and navigation:
            logical_session = f'auto-{secrets.token_hex(8)}'
        elif not logical_session and payload.get('steps'):
            return JSONResponse({
                'detail': (
                    'session is required for stateful drive steps; navigate first '
                    'and reuse the returned session.id'
                )
            }, status_code=422)
        if logical_session:
            internal_session = private_session_id(namespace, logical_session)
            payload = dict(payload)
            payload['session'] = internal_session
            return await upstream(
                'POST', route, payload,
                session_alias=(internal_session, logical_session),
            )
    if route in FETCH_PATHS or route in {'/documents/read', '/documents/image', '/site/crawl'}:
        payload = dict(payload, public_only=True)
    if route in FETCH_PATHS or route in {
            '/documents/read', '/documents/image', '/documents/structure', '/site/crawl',
            '/jobs/read', '/jobs/cancel', '/jobs/resume', '/research',
            '/search-and-fetch', '/search-and-extract'}:
        payload = dict(payload, evidence_namespace=namespace)
    return await upstream('POST', route, payload)
