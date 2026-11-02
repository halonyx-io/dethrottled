"""Real Chromium search extraction, aggregation and pagination without Internet."""
import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
        if query.get('q') == ['blocked'] and page > 1:
            self.send_error(403)
            return
        count = 55 if parsed.path == '/large' else 8 if query.get('q') == ['cap'] else 10
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
            small = await service._race(browser, 'fixture', 1)
            assert small['ok'] and len(small['results']) == 1
            REQUESTS.clear()
            capped_race = await service._race(browser, 'fixture', 50)
            assert capped_race['ok'] and 3 <= len(capped_race['results']) <= 10
            assert all(number == 1 for _, number in REQUESTS)
            assert all(r['engine'].startswith('ddg') for r in capped_race['results'])
            print(json.dumps({'passed': True, 'ddg_cap': len(primary),
                              'supplement_cap': len(secondary),
                              'race_request50_returned': len(capped_race['results']),
                              'automatic_pagination': False,
                              'small_request_rows': len(small['results'])}))
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
