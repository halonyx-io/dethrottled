"""Deterministic browser/extraction fixtures; never points at live accounts."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ARTICLE = (
    "<p>The orbital reference is cobalt-731. This controlled article explains "
    "browser consolidation while retaining substantial readable evidence.</p>" * 25
)
PAGE = (
    """<!doctype html><html><head><title>DNB fixture</title></head><body><main>
<h1>Browser evidence laboratory</h1>"""
    + ARTICLE
    + """
<input id="name"><select id="choice"><option value="a">Alpha</option>
<option value="b">Beta</option></select>
<input id="check" type="checkbox"><button id="go"
onclick="document.querySelector('#answer').textContent='confirmed-928';
localStorage.setItem('proof','saved-417')">Confirm</button>
<p id="answer">pending</p><details><summary>More</summary><p>Expanded fact silver-319</p></details>
<a id="popup" href="/article" target="_blank">Open tab</a>
<a id="download" href="/download">Download</a><iframe src="/frame"></iframe>
<div style="height:1500px">Space</div><p>Final fact amber-592</p>
</main><script>setTimeout(()=>{let p=document.createElement('p');p.id='delayed';
p.textContent='Delayed fact violet-683';document.querySelector('main').append(p)},100);
fetch('/api').then(r=>r.json()).then(v=>window.api=v);
</script></body></html>"""
)


class Handler(BaseHTTPRequestHandler):
    ticks = 0
    mutations = 0

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/article")
            self.end_headers()
            return
        if self.path == "/private-redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:8090/")
            self.end_headers()
            return
        if self.path == "/blocked-redirect":
            self.send_response(302)
            self.send_header("Location", "https://blocked.dnb-test.invalid/")
            self.end_headers()
            return
        if self.path in {"/tick", "/tick-count", "/ticker"}:
            if self.path == "/tick":
                type(self).ticks += 1
            content = (
                PAGE + "<script>setInterval(()=>fetch('/tick'),100)</script>"
                if self.path == "/ticker"
                else str(type(self).ticks)
            )
            raw = content.encode()
            self.send_response(200)
            self.send_header(
                "Content-Type", "text/html" if self.path == "/ticker" else "text/plain"
            )
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if self.path in {"/mutation", "/mutation-count", "/mutate"}:
            if self.path == "/mutation":
                type(self).mutations += 1
            content = (
                "<html><body><button id='mutate' onclick=\"fetch('/mutation')\">Submit</button></body></html>"
                if self.path == "/mutate"
                else str(type(self).mutations)
            )
            raw = content.encode()
            self.send_response(200)
            self.send_header(
                "Content-Type", "text/html" if self.path == "/mutate" else "text/plain"
            )
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        parsed = urlparse(self.path)
        if parsed.path == "/state":
            value = parse_qs(parsed.query).get("set", [""])[0][:50]
            script = """const seed=SEED;
if(seed){localStorage.setItem('owner',seed);sessionStorage.setItem('owner',seed)}
const open=indexedDB.open('dnb-isolation',1);
open.onupgradeneeded=()=>open.result.createObjectStore('state');
open.onsuccess=()=>{const db=open.result;
const tx=db.transaction('state','readwrite'), store=tx.objectStore('state');
if(seed) store.put(seed,'owner');const read=store.get('owner');
read.onsuccess=()=>{document.querySelector('pre').textContent=JSON.stringify({
cookie:document.cookie,local:localStorage.getItem('owner'),
session:sessionStorage.getItem('owner'),idb:read.result||null});
document.querySelector('pre').id='ready'};tx.oncomplete=()=>db.close()};""".replace(
                "SEED", json.dumps(value)
            )
            content = "<html><body><pre></pre><script>" + script + "</script></body></html>"
            raw = content.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            if value:
                self.send_header("Set-Cookie", "owner=" + value + "; Path=/; SameSite=Lax")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        status, ctype = 200, "text/html"
        if self.path == "/api":
            content, ctype = json.dumps({"fact": "network-jade-718"}), "application/json"
        elif self.path == "/download":
            content, ctype = "download-copper-823\n", "text/plain"
        elif self.path == "/frame":
            content = '<html><body><p id="frame-fact">Frame fact gold-214</p></body></html>'
        elif self.path == "/tiny":
            content = "<html><body><h1>Tiny fact quartz-452</h1></body></html>"
        elif self.path == "/error-403":
            content = "<html><body><h1>403 Forbidden</h1><p>Access denied by policy.</p></body></html>"
            status = 403
        elif self.path == "/error-429":
            content = "<html><body><h1>Too Many Requests</h1><p>Slow down and retry later.</p></body></html>"
            status = 429
        elif self.path == "/maintenance":
            content = "<html><body><h1>Service temporarily unavailable</h1><p>Maintenance in progress.</p></body></html>"
            status = 503
        elif self.path == "/login":
            content = ("<html><head><title>Sign in</title></head><body><main><h1>Sign in</h1>"
                       "<form><input name=user><input name=password type=password>"
                       "<button>Sign in</button></form><p>You must be signed in to continue.</p>"
                       "</main></body></html>")
        elif self.path == "/paywall":
            content = ("<html><head><title>Subscribe to continue</title></head><body><main>"
                       "<h1>Subscribe to continue</h1><p>This article is available to subscribers. "
                       "Start your free trial to read the full story.</p></main></body></html>")
        elif self.path == "/access-denied":
            content = ("<html><head><title>Access Denied</title></head><body><main>"
                       "<h1>Access Denied</h1><p>You do not have permission to view this page.</p>"
                       "</main></body></html>")
        elif self.path == "/paywall-long":
            content = ("<html><head><title>Subscribe to continue</title></head><body><main>"
                       + ARTICLE + "<h1>Subscribe to continue</h1><p>This article is available to subscribers.</p>"
                       "</main></body></html>")
        elif self.path == "/login-long":
            content = ("<html><head><title>Sign in</title></head><body><main>"
                       + ARTICLE + "<h1>Sign in</h1><p>You must be signed in to continue.</p>"
                       "</main></body></html>")
        elif self.path == "/access-denied-long":
            content = ("<html><head><title>Access Denied</title></head><body><main>"
                       + ARTICLE + "<h1>Access Denied</h1><p>You do not have permission to view this page.</p>"
                       "</main></body></html>")
        elif self.path == "/huge":
            content = (
                "<html><body><article>"
                + ARTICLE * 1500
                + "<p>Final fact amber-592</p></article></body></html>"
            )
        elif self.path == "/busy":
            content = PAGE + "<script>setTimeout(()=>{while(true){}},50)</script>"
        elif self.path == "/long":
            content = (
                "<html><body><article>"
                + ARTICLE * 30
                + "<p>Final fact amber-592</p></article></body></html>"
            )
        elif self.path == "/blocked-resource":
            content = PAGE + '<script src="https://blocked.dnb-test.invalid/tracker.js"></script>'
        elif self.path == "/missing":
            status, content = (
                404,
                "<html><body><p>Missing resource with readable error text.</p></body></html>",
            )
        else:
            content = PAGE
        raw = content.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        if self.path == "/download":
            self.send_header("Content-Disposition", "attachment; filename=evidence.txt")
        self.end_headers()
        self.wfile.write(raw)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8090), Handler).serve_forever()
