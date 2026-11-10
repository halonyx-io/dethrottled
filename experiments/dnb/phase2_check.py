"""Offline real-Chromium phase-2 gate. Run on an isolated internal Docker network.

The lab assigns its own container a globally classified IP; no internet route.
Only the disposable fixture certificate's SPKI is trusted by the test browser.
"""

import asyncio
import base64
import datetime
import hashlib
import json
import os
import ssl
import threading
import time
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from dethrottled_adblock_proxy import Gate
from navigation_guard import enable, install
from network_policy import Scope, pinned_connect
from patchright.async_api import async_playwright

HITS = []
ACCEPTS = []
PORT = 8443
ORIGIN = f"https://origin.test:{PORT}"
CDN = f"https://cdn.test:{PORT}"
FORBIDDEN = "https://forbidden.test:8444"
BLOCKED = "https://blocked.test:8445"


class Fixture(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        HITS.append(
            {
                "host": self.headers.get("Host"),
                "path": self.path,
                "connection": self.client_address[1],
                "origin_cookie": "origin_secret=" in self.headers.get("Cookie", ""),
            }
        )
        body, kind, extra = "", "text/html", {}
        if self.path == "/jump":
            extra["Location"] = "/hop"
        elif self.path == "/hop":
            extra["Location"] = FORBIDDEN + "/forbidden"
        elif self.path == "/private.js":
            extra["Location"] = "https://127.0.0.1:8091/private"
        elif self.path == "/page":
            extra["Set-Cookie"] = "origin_secret=not-a-real-secret; Secure; HttpOnly; SameSite=None"
            body = f'''<html><head><link rel="stylesheet" href="{CDN}/style.css"></head>
            <body><h1>Origin fact cobalt-731</h1><div id="ready"></div>
            <script src="{CDN}/app.js"></script><script src="{BLOCKED}/blocked.js"></script>
            <script src="{CDN}/private.js"></script></body></html>'''
        elif self.path == "/app.js":
            kind, body = (
                "application/javascript",
                "document.querySelector('#ready').textContent='CDN fact amber-842';",
            )
        elif self.path == "/style.css":
            kind, body = "text/css", "h1{color:rgb(0,128,128)}"
        elif self.path == "/frames":
            body = '<h1>Parent fact jade-953</h1><iframe src="/jump"></iframe>'
        elif self.path == "/popup":
            body = (
                "<button onclick=\"window.open('/jump')\">Open</button>"
                '<button id="safe" onclick="window.open(\'/safe\')">Safe</button>'
            )
        elif self.path == "/sw.js":
            kind = "application/javascript"
            body = f"""self.addEventListener('install',e=>self.skipWaiting());
            self.addEventListener('activate',e=>e.waitUntil(clients.claim()));
            self.addEventListener('fetch',e=>{{if(e.request.url.endsWith('/sw-nav'))
            e.respondWith(Response.redirect('{FORBIDDEN}/sw-forbidden'));
            if(e.request.url.endsWith('/sw-probe'))e.respondWith(fetch('{CDN}/sw-asset'));}});"""
        elif self.path == "/sw-page":
            body = """<h1>Worker fact violet-164</h1><div id="sw"></div><script>
            (async()=>{await navigator.serviceWorker.register('/sw.js');
            await navigator.serviceWorker.ready;
            if(!navigator.serviceWorker.controller)await new Promise(r=>
                navigator.serviceWorker.addEventListener('controllerchange',r,{once:true}));
            document.querySelector('#sw').textContent=await fetch('/sw-probe').then(r=>r.text());
            document.querySelector('#sw').id='swready';})()</script>"""
        else:
            body = "<h1>Safe fact silver-275</h1>"
        raw = body.encode()
        self.send_response(302 if "Location" in extra else 200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", ORIGIN)
        self.send_header("Access-Control-Allow-Credentials", "true")
        for key, value in extra.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)


class Server(ThreadingHTTPServer):
    tls = None

    def get_request(self):
        client, address = super().get_request()
        ACCEPTS.append(self.server_port)
        if self.tls:
            client.settimeout(3)
            client = self.tls.wrap_socket(client, server_side=True)
            client.settimeout(None)
        return client, address


def fixtures():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "DNB disposable fixture")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName(h)
                    for h in ["origin.test", "cdn.test", "forbidden.test", "blocked.test"]
                ]
            ),
            False,
        )
        .sign(key, hashes.SHA256())
    )
    root = Path("/tmp/phase2")
    root.mkdir(exist_ok=True)
    (root / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (root / "key.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(root / "cert.pem", root / "key.pem")
    for port in (PORT, 8444, 8445, 8091):
        server = Server(("127.0.0.1" if port == 8091 else "0.0.0.0", port), Fixture)
        server.tls = tls if port != 8091 else None
        threading.Thread(target=server.serve_forever, daemon=True).start()
    spki = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return base64.b64encode(hashlib.sha256(spki).digest()).decode()


async def run(output):
    import dethrottled_adblock as adblock

    adblock.FILTER.load()
    assert adblock.FILTER.match(BLOCKED) == "blocked.test"
    import patchright.async_api as browser_api

    enable(browser_api)
    spki = fixtures()
    checks = {}
    started = time.monotonic()
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-quic",
                "--proxy-bypass-list=<-loopback>",
                "--ignore-certificate-errors-spki-list=" + spki,
            ],
        )

        async def context(scope):
            gate = Gate(
                connector=partial(
                    pinned_connect, public_only=scope.public_only, allowed_hosts=scope.egress
                )
            )
            ctx = await browser.new_context(proxy=await gate.start())
            await install(ctx, scope, gate.events)
            return ctx, gate

        scope = Scope(True, ("origin.test",), None, "origin.test")
        ctx, gate = await context(scope)
        page = await ctx.new_page()
        await page.goto(ORIGIN + "/page", wait_until="networkidle", timeout=10000)
        assert "amber-842" in await page.inner_text("body")
        assert (
            await page.locator("h1").evaluate("(e)=>getComputedStyle(e).color")
            == "rgb(0, 128, 128)"
        )
        checks["public_cdn_js_css_and_origin_facts"] = True
        # Same-origin secure HttpOnly cookie must not be attached to CDN requests.
        assert await ctx.cookies(ORIGIN)
        assert not any(h["origin_cookie"] for h in HITS if h["host"].startswith("cdn.test"))
        checks["origin_cookie_not_sent_to_cdn"] = True
        for iteration in range(2):
            if iteration:
                await page.close()
                page = await ctx.new_page()
            try:
                await page.goto(ORIGIN + "/jump", timeout=5000)
            except Exception:
                await asyncio.sleep(0.2)  # Chromium commits its denied-navigation error document.
            assert not any(h["host"].startswith("forbidden.test") for h in HITS), HITS
        checks["redirect_denied_fresh_and_reused_context"] = True
        await page.goto(ORIGIN + "/frames", wait_until="networkidle", timeout=8000)
        assert "jade-953" in await page.inner_text("body")
        checks["iframe_redirect_denied_parent_retained"] = True
        await page.goto(ORIGIN + "/popup", timeout=8000)
        await page.get_by_text("Open", exact=True).click()
        await asyncio.sleep(0.5)
        assert not any(h["host"].startswith("forbidden.test") for h in HITS)
        async with page.expect_popup() as event:
            await page.locator("#safe").click()
        popup = await event.value
        await popup.wait_for_load_state()
        assert "silver-275" in await popup.inner_text("body")
        checks["popup_scoped_and_allowed_popup_works"] = True
        await page.goto(ORIGIN + "/sw-page", timeout=8000)
        await page.wait_for_selector("#swready", timeout=5000)
        assert "silver-275" in await page.inner_text("#swready")
        checks["service_worker_allowed_cdn_fetch"] = True
        try:
            await page.goto(ORIGIN + "/sw-nav", timeout=5000)
        except Exception:
            pass
        await asyncio.sleep(0.2)
        assert not any(h["host"].startswith("forbidden.test") for h in HITS), HITS
        checks["service_worker_navigation_redirect_denied"] = True
        assert not any(h["host"].startswith("blocked.test") for h in HITS)
        assert not any(h["path"] == "/private" for h in HITS)
        assert not set(ACCEPTS).intersection({8444, 8445, 8091}), ACCEPTS
        checks["adblock_and_private_redirect_zero_destination_hits"] = True
        checks["policy_events"] = list(gate.events)
        await ctx.close()
        await gate.close()

        for public, assets, expected in [
            (False, None, False),
            (False, ("cdn.test",), True),
            (True, (), False),
            (True, ("cdn.test",), True),
        ]:
            ctx, gate = await context(Scope(public, ("origin.test",), assets, "origin.test"))
            page = await ctx.new_page()
            await page.goto(ORIGIN + "/page", wait_until="networkidle", timeout=8000)
            text = await page.inner_text("body")
            assert ("amber-842" in text) == expected, text
            assert "cobalt-731" in text
            await ctx.close()
            await gate.close()
        checks["internal_cdn_requires_explicit_trusted_asset_scope"] = True
        checks["explicit_public_asset_scope_is_restrictive"] = True
        await browser.close()
    # Endpoint wiring gate: use the actual ASGI handlers and normal lifecycle.
    # Anonymous requests here deliberately do not certify phase-3 delegation.
    import httpx

    os.environ["DNB_ALLOW_INTERNAL_URLS"] = "false"
    import dnb_service as dnb

    launch = browser_api.BrowserType.launch

    async def fixture_launch(kind, *args, **kwargs):
        kwargs["args"] = [*kwargs.get("args", []), "--ignore-certificate-errors-spki-list=" + spki]
        return await launch(kind, *args, **kwargs)

    browser_api.BrowserType.launch = fixture_launch
    async with dnb.app.router.lifespan_context(dnb.app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=dnb.app), base_url="http://worker"
        ) as client:
            response = await client.post(
                "/crawl",
                json={
                    "urls": [ORIGIN + "/page"],
                    "crawler_config": {
                        "type": "CrawlerRunConfig",
                        "params": {"wait_for": "css:#ready", "delay_before_return_html": 0.1},
                    },
                },
            )
            assert response.status_code == 200, response.text
            row = response.json()["results"][0]
            assert row["success"] and "amber-842" in row["markdown"]["raw_markdown"], row
            response = await client.post(
                "/drive",
                json={
                    "url": ORIGIN + "/page",
                    "allowed_hosts": ["origin.test"],
                    "public_only": True,
                    "steps": [
                        {"action": "wait", "ms": 100},
                        {"action": "text", "selector": "body"},
                    ],
                    "screenshot": False,
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["ok"], response.text
            assert "amber-842" in response.text, response.text
            assert not set(ACCEPTS).intersection({8444, 8445, 8091}), ACCEPTS
    checks["crawl_and_drive_handlers_preserve_cdn_evidence"] = True
    checks["forbidden_adblock_private_tcp_connections"] = {
        str(port): ACCEPTS.count(port) for port in (8444, 8445, 8091)
    }
    checks["elapsed_seconds"] = round(time.monotonic() - started, 3)
    # Connection IDs are ephemeral test-local socket ports, not credentials.
    checks["fixture_hits"] = HITS
    Path(output).write_text(json.dumps(checks, indent=2) + "\n")
    print(
        json.dumps(
            {k: v for k, v in checks.items() if k not in {"fixture_hits", "policy_events"}},
            indent=2,
        )
    )


if __name__ == "__main__":
    import sys

    try:
        asyncio.run(run(sys.argv[1]))
    except BaseException:
        Path(sys.argv[1] + ".failed-hits.json").write_text(json.dumps(HITS, indent=2) + "\n")
        raise
