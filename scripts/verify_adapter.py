"""Real MCP transport contracts against a deterministic local HTTP backend."""
import asyncio
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from pathlib import Path

import httpx
from dethrottled_version import __version__
from dethrottled_workflow import INSTRUCTIONS
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

IDENTITY = {'version': 'older-backend-fixture'}


class Backend(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def answer(self, value):
        data = json.dumps(value).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.answer(dict(IDENTITY))

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path == '/search':
            self.answer([{'url': f'https://example.org/{i}', 'title': f'Source {i}',
                          'echo_domains': payload.get('domains', []),
                          'echo_excluded': payload.get('exclude_domains', []),
                          'snippet': 'Known fact: 7341 tonnes.\nQuoted "evidence" — café.'}
                         for i in range(payload['limit'])])
        elif self.path == '/v2/search':
            outcome, degraded = {
                'partial': ('partial_results', True), 'empty': ('no_results', False),
                'down': ('unavailable', True), 'unknown': ('indeterminate', True),
            }[payload['query']]
            rows = ([{'url': 'https://example.org/first'},
                     {'url': 'https://example.org/second'}] if outcome == 'partial_results' else [])
            self.answer({'results': rows, 'status': 'ok' if rows else 'no_results_or_degraded',
                         'outcome': outcome, 'degraded': degraded,
                         'attempts': [{'provider': 'web', 'status': 'http_429' if degraded
                                      else 'no_results', 'retry_after_seconds': 30}]})
        elif self.path == '/research':
            self.answer({'echo_domains': payload.get('domains', []),
                         'sources': [{'id': f'S{i}', 'content': '7341 tonnes'}
                                     for i in range(payload['max_sources'])]})
        elif self.path == '/search-and-fetch':
            self.answer({'echo_domains': payload.get('domains', [])})
        elif self.path == '/drive':
            self.answer({'ok': True, 'steps': [], 'screenshot_b64':
                         'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jHHsAAAAASUVORK5CYII='})
        elif self.path == '/fetch':
            self.answer([{'content': 'X' * (payload['max_chars'] - 13) + '7341 tonnes!!',
                          'echo_selectors': payload.get('selectors', {})}])
        elif self.path == '/site/crawl':
            self.answer({'mode': payload.get('mode'),
                         'max_discovery_requests': payload.get('max_discovery_requests')})
        elif self.path == '/jobs/fetch':
            self.answer({'selectors': payload.get('selectors'),
                         'response_format': payload.get('response_format')})
        else:
            self.answer({'ok': True})


async def verify(url, rest_url, token, registry):
    headers = {'Authorization': 'Bearer ' + token}
    async with httpx.AsyncClient(base_url=url) as http:
        health = (await http.get('/health')).json()
        assert health['version'] == __version__
        assert health['sdk_version'] == '1.30.0'
        assert health['backend']['status'] == 'mismatch'
        assert (await http.post('/mcp', json={})).status_code == 401
        async with streamablehttp_client(url + '/mcp', headers=headers) as (read, write, _):
            async with ClientSession(read, write) as client:
                init = await client.initialize()
                assert init.serverInfo.version == __version__, init.serverInfo
                assert init.instructions and 'read_document' in init.instructions
                assert init.instructions == INSTRUCTIONS
                listing = await client.list_tools()
                assert len(listing.tools) == 21
                assert any(t.name == 'document_status' for t in listing.tools)
                for name in ('fetch', 'research', 'read_document'):
                    tool = next(t for t in listing.tools if t.name == name)
                    assert tool.inputSchema['properties']['response_format']['default'] == 'concise'
                drive = next(t for t in listing.tools if t.name == 'drive')
                assert all(s in json.dumps(drive.inputSchema) for s in
                           ['scroll', 'read_state', 'expand_details'])
                extra = await client.call_tool('capabilities', {'unexpected': True})
                assert extra.isError and 'extra' in str(extra.content).lower()
                private = await client.call_tool('fetch', {'urls': ['http://127.0.0.1/']})
                assert private.isError
                assert 'public HTTP(S) URLs are required' in str(private.content)
                rows = await client.call_tool('search', {'query': 'fixture', 'limit': 15})
                assert not rows.isError and len(rows.content) == 15
                assert rows.structuredContent is None  # Preserve the legacy list contract.
                for query, expected, degraded in [
                        ('partial', 'partial_results', True), ('empty', 'no_results', False),
                        ('down', 'unavailable', True), ('unknown', 'indeterminate', True)]:
                    diagnosed = await client.call_tool('search', {
                        'query': query, 'diagnostics': True})
                    assert not diagnosed.isError
                    # search returns Any: the SDK preserves its JSON-text envelope.
                    envelope = (diagnosed.structuredContent or
                                json.loads(diagnosed.content[0].text))
                    assert envelope['outcome'] == expected and envelope['degraded'] == degraded
                    assert envelope['status'] == ('ok' if query == 'partial'
                                                   else 'no_results_or_degraded')
                    assert envelope['attempts'][0]['retry_after_seconds'] == 30
                    assert [r['url'] for r in envelope['results']] == (
                        ['https://example.org/first', 'https://example.org/second']
                        if query == 'partial' else [])
                values = [json.loads(block.text) for block in rows.content]
                assert values[-1]['url'] == 'https://example.org/14'
                assert all('7341 tonnes' in v['snippet'] and '\n' in v['snippet'] for v in values)
                assert all(block.text == json.dumps(value, ensure_ascii=False,
                           separators=(',', ':')) for block, value in zip(rows.content, values))
                compact_bytes = sum(len(b.text.encode()) for b in rows.content[:8])
                pretty_bytes = sum(len(json.dumps(v, ensure_ascii=False, indent=2).encode())
                                   for v in values[:8])
                assert compact_bytes < pretty_bytes
                filtered = await client.call_tool('search', {
                    'query': 'fixture', 'domains': ['example.org'],
                    'exclude_domains': ['ads.example.org'], 'limit': 1})
                assert not filtered.isError
                forwarded = json.loads(filtered.content[0].text)
                assert forwarded['echo_domains'] == ['example.org']
                assert forwarded['echo_excluded'] == ['ads.example.org']
                selected_search = await client.call_tool('search_and_fetch', {
                    'query': 'fixture', 'domains': ['example.org']})
                assert not selected_search.isError
                assert json.loads(selected_search.content[0].text)['echo_domains'] == [
                    'example.org']
                structured = await client.call_tool('capabilities', {})
                assert structured.structuredContent['version'] == 'older-backend-fixture'
                assert json.loads(structured.content[0].text) == structured.structuredContent
                large = await client.call_tool('fetch', {'urls': ['https://93.184.216.34/'],
                                                       'max_chars': 200000})
                assert not large.isError
                assert '7341 tonnes' in json.loads(large.content[0].text)['content']
                selected = await client.call_tool('fetch', {
                    'urls': ['https://93.184.216.34/'],
                    'selectors': {'title': {'selector': 'h1'}}})
                assert not selected.isError
                assert json.loads(selected.content[0].text)['echo_selectors'] == {
                    'title': {'selector': 'h1'}}
                mapped = await client.call_tool('crawl_site', {
                    'urls': ['https://93.184.216.34/'], 'mode': 'map',
                    'max_discovery_requests': 2})
                assert not mapped.isError and mapped.structuredContent == {
                    'mode': 'map', 'max_discovery_requests': 2}
                queued = await client.call_tool('start_fetch_job', {
                    'urls': ['https://93.184.216.34/'],
                    'selectors': {'title': {'selector': 'h1'}}, 'response_format': 'concise'})
                assert not queued.isError and queued.structuredContent == {
                    'selectors': {'title': {'selector': 'h1'}}, 'response_format': 'concise'}
                research = await client.call_tool('research', {
                    'question': 'fixture evidence', 'max_sources': 20, 'max_chars': 120000,
                    'queries': [f'facet {i}' for i in range(10)], 'domains': ['example.org']})
                assert not research.isError and len(research.structuredContent['sources']) == 20
                assert research.structuredContent['echo_domains'] == ['example.org']
                pixels = await client.call_tool('drive', {
                    'session': 'fixture-pixels', 'allowed_hosts': ['93.184.216.34'],
                    'steps': [], 'screenshot': 'always'})
                assert not pixels.isError
                assert any(b.type == 'image' for b in pixels.content)
                assert 'screenshot_b64' not in pixels.structuredContent
                excessive = await client.call_tool('search', {'query': 'fixture', 'limit': 16})
                assert excessive.isError
        async with httpx.AsyncClient(base_url=rest_url, headers=headers) as rest:
            search = await rest.post('/search', json={'query': 'fixture', 'limit': 15})
            assert search.status_code == 200 and len(search.json()) == 15
            research = await rest.post('/research', json={
                'question': 'fixture evidence', 'max_sources': 20, 'max_chars': 120000,
                'queries': [f'facet {i}' for i in range(10)]})
            assert research.status_code == 200 and len(research.json()['sources']) == 20
            too_many = await rest.post('/search', json={'query': 'fixture', 'limit': 16})
            assert too_many.status_code == 400
            private = await rest.post('/fetch', json={'urls': ['http://127.0.0.1/']})
            assert private.status_code == 400
        # Catch a backend replacement without restarting the bridge.
        IDENTITY['version'] = __version__
        await asyncio.sleep(10.1)
        assert (await http.get('/health')).json()['backend']['status'] == 'match'
        replacement = registry.with_suffix('.new')
        replacement.write_text(json.dumps({'tokens': []}))
        replacement.replace(registry)
        assert (await http.post('/mcp', headers=headers, json={})).status_code == 401
        print(json.dumps({'passed': True, 'application_version': __version__,
                          'sdk_version': health['sdk_version'], 'tools': len(listing.tools),
                          'strict_arguments': True, 'private_targets_rejected': True,
                          'authentication_and_revocation': True, 'search_results': 15,
                          'research_sources': 20, 'research_facets': 10,
                          'large_read_fact': True, 'backend_mismatch_then_match': True,
                          'rest_coverage_and_policy': True, 'native_images_preserved': True,
                          'compact_bytes_8_rows': compact_bytes,
                          'equivalent_pretty_bytes_8_rows': pretty_bytes}))


def main():
    lock = Path(__file__).with_name('requirements.txt')
    pins = [line.split('==') for line in lock.read_text().splitlines() if '==' in line]
    assert pins and all(version(name) == pinned for name, pinned in pins)
    subprocess.run([sys.executable, '-m', 'pip', 'check'], check=True,
                   capture_output=True, text=True)
    with tempfile.TemporaryDirectory(prefix='adapter-verification-') as directory:
        root = Path(directory)
        token = secrets.token_urlsafe(32)
        registry = root / 'tokens.json'
        registry.write_text(json.dumps({'tokens': [{
            'sha256': hashlib.sha256(token.encode()).hexdigest(),
            'scopes': ['web', 'drive', 'corpus']}]}))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        backend = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
        threading.Thread(target=backend.serve_forever, daemon=True).start()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            rest_port = sock.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        rest_url = f'http://127.0.0.1:{rest_port}'
        env = dict(os.environ, DETHROTTLED_TOKEN_REGISTRY=str(registry),
                   DETHROTTLED_ADMISSION_DB=str(root / 'admission.sqlite'),
                   MCP_BACKEND_URL=f'http://127.0.0.1:{backend.server_port}',
                   MCP_ALLOWED_HOSTS='127.0.0.1:*,localhost:*')
        with (root / 'server.log').open('w+') as log:
            process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'server:app',
                                        '--host', '127.0.0.1', '--port', str(port)],
                                       env=env, stdout=log, stderr=log)
            rest_process = subprocess.Popen([
                sys.executable, '-m', 'uvicorn', 'public_gateway:app',
                '--host', '127.0.0.1', '--port', str(rest_port)],
                env=env, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    try:
                        if all(httpx.get(base + '/health', timeout=1).status_code == 200
                               for base in [url, rest_url]):
                            break
                    except httpx.HTTPError:
                        pass
                    if process.poll() is not None:
                        raise RuntimeError('adapter exited before readiness')
                    time.sleep(.1)
                else:
                    raise RuntimeError('adapter readiness timeout')
                asyncio.run(verify(url, rest_url, token, registry))
                log.flush()
                assert 'backend identity mismatch' in (root / 'server.log').read_text()
            except BaseException:
                log.seek(0)
                print(log.read(), file=sys.stderr)
                raise
            finally:
                process.terminate()
                process.wait(timeout=15)
                rest_process.terminate()
                rest_process.wait(timeout=15)
                backend.shutdown()


if __name__ == '__main__':
    main()
