"""Real Chromium search extraction, aggregation and pagination without Internet."""
import ast
import asyncio
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import service
from patchright.async_api import async_playwright

REQUESTS = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        page = int(query.get('page', ['1'])[0])
        REQUESTS.append((parsed.path, page))
        if query.get('q') == ['rate-limited']:
            self.send_response(429)
            self.send_header('Retry-After', '120')
            self.end_headers()
            return
        if query.get('q') == ['blocked'] and page > 1:
            self.send_error(403)
            return
        count = (int(query['q'][0][-1]) if query.get('q', [''])[0] in {'sparse1', 'sparse2'}
                 else 0 if query.get('q') == ['empty'] else
                 55 if parsed.path == '/large' else 8 if query.get('q') == ['cap'] else 10)
        rows = ''.join(
            f'<a class="result-link" href="https://example.org{parsed.path}/{page}/{i}">'
            f'Source evidence number {i}</a><div class="result-snippet">'
            f'Known allocation fact 7341 tonnes, evidence record {i}.</div>' for i in range(count))
        next_page = (f'<form action="{parsed.path}" method="get">'
                     f'<input name="q" value="{query.get("q", ["fixture"])[0]}">'
                     f'<input name="page" value="{page + 1}">'
                     '<input type="submit" value="Next Page"></form>')
        if page >= 3 and query.get('q') != ['cap']:
            next_page = ''
        data = ('<html><body>' + rows + next_page + '</body></html>').encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


async def verify(base):
    os.environ.setdefault('DISPLAY', ':99')
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)
        try:
            service.ENGINES = {name: (f'{base}/{name}?q=', 'a.result-link', '.result-snippet')
                               for name in service.ENGINES}
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(base + '/large')
            primary = await service._extract(page, 'ddg-lite', 'fixture', 50)
            assert len(primary) == 10
            secondary = await service._extract(page, 'bing', 'fixture', 50)
            assert len(secondary) == 3
            REQUESTS.clear()
            capped = await service._engine(context, 'bing', 'cap', 0, 50)
            assert capped['pages'] == 1 and len(capped['results']) == 3
            assert all(number == 1 for _, number in REQUESTS)
            await context.close()
            REQUESTS.clear()
            limited = await service._race(browser, 'rate-limited', 10)
            assert not limited['ok'] and not limited['results']
            assert any(a.get('retry_after_seconds') == 120 for a in limited['attempts']), limited
            limited_requests = len(REQUESTS)
            assert limited_requests <= 2  # Already-started parallel work cannot be unsent.
            assert service._retry_after('invalid') == 0
            assert service._retry_after('NaN') == 0
            assert service._retry_after('inf') == 0
            assert service._retry_after('0') == 0
            assert service._retry_after('Fri, 01 Jan 2100 00:00:00 GMT') == 86400
            baseline = []
            if os.environ.get('BASELINE_SERVICE_SOURCE'):
                tree = ast.parse(Path(os.environ['BASELINE_SERVICE_SOURCE']).read_text())
                saved = {name: getattr(service, name) for name in ('_engine', '_usable')}
                selected = [node for node in tree.body
                            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and node.name in saved]
                try:
                    exec(compile(ast.Module(body=selected, type_ignores=[]),
                                 '<baseline-browser-functions>', 'exec'), service.__dict__)
                    for count in (1, 2):
                        started = time.perf_counter()
                        result = await service._race(browser, f'sparse{count}', 10)
                        baseline.append({'available_sources': count, 'ok': result['ok'],
                                         'returned': len(result['results']),
                                         'seconds': time.perf_counter() - started})
                        assert not result['ok']
                finally:
                    for name, value in saved.items():
                        setattr(service, name, value)
            REQUESTS.clear()
            small = await service._race(browser, 'fixture', 1)
            assert small['ok'] and len(small['results']) == 1
            sparse_counts, sparse_timings = [], []
            for count in (1, 2):
                started = time.perf_counter()
                sparse = await service._race(browser, f'sparse{count}', 10)
                sparse_timings.append(time.perf_counter() - started)
                assert sparse['ok'] and len(sparse['results']) == count
                sparse_counts.append(count)
            assert not service._usable([])
            assert not service._usable([{'snippet': 'short'}])
            original_race = service._race

            async def refusal(*args):
                return {'ok': False, 'service_s': 1.25,
                        'attempts': [{'engine': 'ddg-lite', 'status': 202, 'count': 0,
                                      'reason': 'TimeoutError: private query in exception'}]}

            service._race = refusal
            service.app.state.browser = browser
            try:
                for _ in range(22):
                    try:
                        await service.search(service.SearchRequest(query='private fixture'))
                    except service.HTTPException as exc:
                        assert exc.status_code == 503
                        assert exc.detail['service_s'] == 1.25
                    else:
                        raise AssertionError('Empty/refused discovery must not succeed')
                metrics = await service.metrics()
                assert len(metrics['recent_failures']) == 20
                assert 'private' not in json.dumps(metrics['recent_failures'])
                assert service.ACTIVE == service.WAITING == 0
            finally:
                service._race = original_race
            REQUESTS.clear()
            capped_race = await service._race(browser, 'fixture', 50)
            assert capped_race['ok'] and 3 <= len(capped_race['results']) <= 10
            assert all(number == 1 for _, number in REQUESTS)
            assert all(r['engine'].startswith('ddg') for r in capped_race['results'])
            print(json.dumps({'passed': True, 'ddg_cap': len(primary),
                              'supplement_cap': len(secondary),
                              'race_request50_returned': len(capped_race['results']),
                              'automatic_pagination': False,
                              'small_request_rows': len(small['results']),
                              'sparse_counts': sparse_counts,
                              'retry_after_requests': limited_requests,
                              'retry_after_preserved': True,
                              'sparse_seconds': sparse_timings, 'baseline': baseline}))
        finally:
            await browser.close()


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        asyncio.run(verify(f'http://127.0.0.1:{server.server_port}'))
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
