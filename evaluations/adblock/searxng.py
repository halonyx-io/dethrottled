"""Actual pinned SearXNG curl_cffi boundary, with local redirect controls."""

import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from searx.network.client import AsyncClient
from searx.plugins import dethrottled_adblock as adblock
from searx.plugins.dethrottled_guard import install_adblock

hits = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        hits.append(self.path)
        self.send_response(302 if self.path == "/redirect" else 200)
        if self.path == "/redirect":
            self.send_header("Location", "https://a.google-analytics.com/blocked")
        self.end_headers()
        self.wfile.write(b"Fact allocation is 7341 tonnes")


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
adblock.FILTER.load()
assert len(adblock.FILTER.rules) > 200000
install_adblock()


async def run():
    client = AsyncClient()
    try:
        response = await client.get(f"http://127.0.0.1:{server.server_port}/content")
        assert "7341" in response.text
        try:
            await client.get(f"http://127.0.0.1:{server.server_port}/redirect")
        except adblock.AdblockBlocked:
            blocked = True
        else:
            blocked = False
        return {
            "passed": blocked and hits == ["/content", "/redirect"],
            "hits": hits,
            "status": adblock.FILTER.status(),
            "architecture": os.uname().machine,
        }
    finally:
        await client.aclose()


try:
    report = asyncio.run(run())
    Path("/lab/results/x86_64-searxng.json").write_text(json.dumps(report, indent=2) + "\n")
    assert report["passed"]
    print(json.dumps(report))
finally:
    adblock.FILTER.stop()
    server.shutdown()
