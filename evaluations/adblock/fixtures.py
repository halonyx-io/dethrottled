"""Local evidence/ad fixtures. Real tracking domains resolve locally only in labs."""

import json
import ssl
import subprocess
import tempfile
from pathlib import Path
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FACTS = [
    "Allocation is 7341 tonnes",
    "JS result is 9127 units",
    "Challenge script preserved 6193",
    "Clicked record 4482",
]
TRACKER = "a.google-analytics.com"


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
                if path == "/page":
                    html = f"""<html><body><main><h1>Evidence fixture</h1>
                    <p>{FACTS[0]}</p><p id="js"></p><p id="challenge"></p><p id="clicked"></p>
                    <button id="open" onclick="document.querySelector('#clicked').textContent='{FACTS[3]}'">Read record</button>
                    <a id="popup" target="_blank" href="https://{TRACKER}:{port}/popup">Popup</a>
                    <a id="download" download href="/document.txt">Download</a>
                    <script src="https://cdn.example:{port}/content.js"></script>
                    <script src="https://challenges.cloudflare.com:{port}/challenge.js"></script>
                    <script>for(let i=0;i<8;i++){{let s=document.createElement('script');
                    s.src='https://{TRACKER}:{port}/track.js?i='+i;document.body.append(s);}}
                    fetch('https://{TRACKER}:{port}/collect').catch(()=>{{}});
                    let image=new Image();image.src='https://{TRACKER}:{port}/pixel';
                    let frame=document.createElement('iframe');frame.src='https://{TRACKER}:{port}/frame';document.body.append(frame);
                    </script></main></body></html>"""
                    payload = html.encode()
                elif path == "/content.js":
                    ctype = "application/javascript"
                    payload = f"document.querySelector('#js').textContent='{FACTS[1]}';".encode()
                elif path == "/challenge.js":
                    ctype = "application/javascript"
                    payload = f"document.cookie='fixture_verified=1';document.querySelector('#challenge').textContent='{FACTS[2]}';".encode()
                elif path == "/redirect":
                    code, payload = 302, b""
                    extra["Location"] = f"https://{TRACKER}:{port}/landing"
                elif path == "/clean-redirect":
                    code, payload = 302, b""
                    extra["Location"] = "/document.txt"
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
