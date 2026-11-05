"""Local evidence/ad fixtures. Real tracking domains resolve locally only in labs."""

import json
import ssl
import subprocess
import tempfile
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FACTS = [
    "Allocation is 7341 tonnes",
    "JS result is 9127 units",
    "Challenge script preserved 6193",
    "Clicked record 4482",
]
TRACKER = "a.google-analytics.com"


def pdf():
    stream = (
        "BT /F1 12 Tf 40 720 Td (" + FACTS[0] + ") Tj 0 -20 Td (" + FACTS[1] + ") Tj ET"
    ).encode()
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        (
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
            b"/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>"
        ),
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
        b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream",
    ]
    result = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result += str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    start = len(result)
    result += b"xref\n0 6\n0000000000 65535 f \n"
    result += b"".join(("%010d 00000 n \n" % offset).encode() for offset in offsets[1:])
    return result + b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n" + str(start).encode() + b"\n%%EOF"


class Fixture:
    def __init__(self):
        self.counts = Counter()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                host = self.headers.get("Host", "").split(":")[0]
                outer.counts["requests"] += 1
                if host == TRACKER:
                    outer.counts["tracking_requests"] += 1
                path = self.path.split("?")[0]
                port = outer.tls_port
                code, ctype = 200, "text/html"
                extra = {}
                if path in {"/page", "/clean-page"}:
                    html = f"""<html><body><main><h1>Evidence fixture</h1>
                    <p>{FACTS[0]}</p><p id="js"></p><p id="challenge"></p><p id="clicked"></p>
                    <button id="open"
onclick="document.querySelector('#clicked').textContent='{FACTS[3]}'">Read record</button>
                    <a id="popup" target="_blank" href="https://{TRACKER}:{port}/popup">Popup</a>
                    <a id="download" download href="/document.txt">Download</a>
                    <script src="https://cdn.example:{port}/content.js"></script>
                    <script src="https://challenges.cloudflare.com:{port}/challenge.js"></script>
                    <script>for(let i=0;i<8;i++){{let s=document.createElement('script');
                    s.src='https://{TRACKER}:{port}/track.js?i='+i;document.body.append(s);}}
                    fetch('https://{TRACKER}:{port}/collect').catch(()=>{{}});
                    let image=new Image();image.src='https://{TRACKER}:{port}/pixel';
                    let frame=document.createElement('iframe');
                    frame.src='https://{TRACKER}:{port}/frame';document.body.append(frame);
                    </script></main></body></html>"""
                    if path == "/clean-page":
                        start = html.index("<script>for(let")
                        end = html.index("</script>", start) + len("</script>")
                        html = html[:start] + html[end:]
                    payload = html.encode()
                elif path == "/content.js":
                    ctype = "application/javascript"
                    payload = f"document.querySelector('#js').textContent='{FACTS[1]}';".encode()
                elif path == "/challenge.js":
                    ctype = "application/javascript"
                    payload = (
                        "document.cookie='fixture_verified=1';"
                        f"document.querySelector('#challenge').textContent='{FACTS[2]}';"
                    ).encode()
                elif path == "/sw.js":
                    ctype = "application/javascript"
                    payload = (
                        "self.addEventListener('install',e=>e.waitUntil(fetch("
                        f"'https://{TRACKER}:{port}/service-worker-collect'"
                        ").catch(()=>{})));self.addEventListener('fetch',()=>{});"
                    ).encode()
                elif path == "/worker.js":
                    ctype = "application/javascript"
                    payload = (
                        "Promise.all(['/document.txt','/redirect'].map(u=>fetch(u)"
                        ".then(r=>r.text()).catch(e=>'blocked'))).then(r=>postMessage(r));"
                    ).encode()
                elif path == "/redirect":
                    code, payload = 302, b""
                    extra["Location"] = f"https://{TRACKER}:{port}/landing"
                elif path == "/clean-redirect":
                    code, payload = 302, b""
                    extra["Location"] = "/document.txt"
                elif path == "/document.pdf":
                    ctype, payload = "application/pdf", pdf()
                elif path == "/document.txt":
                    ctype, payload = "text/plain", (FACTS[0] + "\n" + FACTS[1]).encode()
                    extra["Content-Disposition"] = 'attachment; filename="evidence.txt"'
                elif path == "/track.js":
                    ctype, payload = "application/javascript", b"/*" + b"x" * 16384 + b"*/"
                elif host == TRACKER:
                    payload = b"x" * 8192
                else:
                    payload = b"<html><body>Clean content</body></html>"
                outer.counts["body_bytes"] += len(payload)
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Access-Control-Allow-Origin", "*")
                for key, value in extra.items():
                    self.send_header(key, value)
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.cert_dir = tempfile.TemporaryDirectory()
        cert = Path(self.cert_dir.name) / "cert.pem"
        key = Path(self.cert_dir.name) / "key.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-subj",
                "/CN=fixture.invalid",
                "-days",
                "1",
                "-keyout",
                str(key),
                "-out",
                str(cert),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.tls_server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
        self.tls_port = self.tls_server.server_port
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)
        self.tls_server.socket = tls.wrap_socket(self.tls_server.socket, server_side=True)
        threading.Thread(target=self.tls_server.serve_forever, daemon=True).start()
        self.server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def reset(self):
        self.counts.clear()

    def stop(self):
        self.tls_server.shutdown()
        self.tls_server.server_close()
        self.cert_dir.cleanup()
        self.server.shutdown()
        self.server.server_close()


if __name__ == "__main__":
    fixture = Fixture()
    print(json.dumps({"port": fixture.port}), flush=True)
    fixture.thread.join()


def metrics():
    """Linux cgroup v2 totals; working set excludes inactive file cache."""
    from pathlib import Path

    root = Path("/sys/fs/cgroup")
    try:
        cpu = dict(line.split() for line in (root / "cpu.stat").read_text().splitlines())
        memory = dict(line.split() for line in (root / "memory.stat").read_text().splitlines())
        current = int((root / "memory.current").read_text())
        return {
            "cpu_ms": int(cpu["usage_usec"]) / 1000,
            "working_set_bytes": max(0, current - int(memory.get("inactive_file", 0))),
            "anon_bytes": int(memory.get("anon", 0)),
        }
    except OSError:
        return {"cpu_ms": 0, "working_set_bytes": 0, "anon_bytes": 0}


def text_only(html):
    """Grade text nodes, never facts hidden in attributes/scripts/styles."""
    from html.parser import HTMLParser

    class Text(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts, self.hidden = [], 0

        def handle_starttag(self, tag, attrs):
            if tag in {"script", "style", "noscript"}:
                self.hidden += 1

        def handle_endtag(self, tag):
            if tag in {"script", "style", "noscript"}:
                self.hidden = max(0, self.hidden - 1)

        def handle_data(self, data):
            if not self.hidden:
                self.parts.append(data)

    parser = Text()
    parser.feed(html)
    return " ".join(parser.parts)
