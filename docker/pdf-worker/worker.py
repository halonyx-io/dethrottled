"""PDF worker for the dethrottled stack: HTML in, PDF out.

Why this exists. crawl4ai's own /pdf endpoint takes only a URL and prints with
Playwright's defaults (Letter paper, CSS @page rules ignored), which loses A4
and the running page footers a briefing needs.
This worker prints with the CSS page size honoured, using the Chromium already in this image.

What it can and cannot do, so it is safe to leave open to the whole LAN:
  * it renders ONLY the HTML it is handed; it is never given a URL to fetch
  * the browser context is offline and has JavaScript off: HTML cannot reach a network or run
  * the browser starts for each request and closes afterward; none is left between PDFs
  * one render at a time; a body larger than MAX_BODY is refused

    POST /pdf   {"html": "<!doctype html>...", "format": "A4"}   ->  application/pdf
    GET  /health
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from playwright.sync_api import sync_playwright

PORT = int(os.environ.get("PDF_WORKER_PORT", "8788"))
MAX_BODY = 20_000_000
FORMATS = {"A4", "A3", "Letter", "Legal"}
LOCK = threading.Lock()


def render(html: str, fmt: str) -> bytes:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        )
        try:
            context = browser.new_context(java_script_enabled=False, offline=True)
            page = context.new_page()
            page.route("**/*", lambda route: route.abort())
            page.set_content(html, wait_until="load", timeout=30_000)
            page.emulate_media(media="print")
            return page.pdf(format=fmt, print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "pdf-worker/1"

    def log_message(self, fmt, *args):
        # Never log request bodies; one line per render is logged below.
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            return self._send(200, {"ok": True, "service": "pdf-worker"})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/pdf":
            return self._send(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return self._send(413, {"error": "body must be 1 byte to %d bytes" % MAX_BODY})
        try:
            body = json.loads(self.rfile.read(length))
            html, fmt = body["html"], body.get("format", "A4")
            if not isinstance(html, str) or fmt not in FORMATS:
                raise ValueError("html must be a string and format one of %s" % sorted(FORMATS))
        except (ValueError, KeyError, TypeError) as exc:
            return self._send(400, {"error": str(exc)[:200]})
        started = time.time()
        if not LOCK.acquire(timeout=120):
            return self._send(503, {"error": "busy"})
        try:
            pdf = render(html, fmt)
        except Exception as exc:
            print("render failed: %s: %s" % (type(exc).__name__, str(exc)[:200]), flush=True)
            return self._send(500, {"error": "render failed: %s" % type(exc).__name__})
        finally:
            LOCK.release()
        print("rendered %d KB html -> %d KB pdf in %.1fs" % (
            length // 1024, len(pdf) // 1024, time.time() - started), flush=True)
        self._send(200, pdf, "application/pdf")


if __name__ == "__main__":
    print("pdf-worker listening on :%d" % PORT, flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
