import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

FACT = "The regional allocation for 2026 is 7341 tonnes. " * 30


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = urlsplit(self.path).path
        content = "text/html"
        status = 200
        if path == "/alternate" and "md=1" in self.path:
            content = "text/markdown"
            body = "# Allocation report\n" + FACT
        elif path == "/alternate":
            body = (
                '<html><head><link rel="alternate" type="text/markdown" href="?md=1"></'
                'head><body>The complete allocation report is available in the alternat'
                'ive representation.</body></html>'
            )
        elif path == "/lazy":
            body = (
                    '<html><body>Allocation report is loading. Scroll to view the available'
                    ' evidence.<div style="height:4000px"></div><article id="report"></arti'
                    'cle><script>addEventListener("scroll",()=>{if(scrollY>100)document.que'
                    'rySelector("#report").textContent='
                + json.dumps(FACT)
                + "})</script></body></html>"
            )
        elif path == "/details":
            body = (
                    '<html><body>Allocation report. Expand the report to read the available'
                    ' evidence.<details><summary>Read allocation report</summary><article i'
                    'd="report"></article></details><script>document.querySelector("details'
                    '").addEventListener("toggle",()=>{if(document.querySelector("details")'
                    '.open)document.querySelector("#report").textContent='
                + json.dumps(FACT)
                + "})</script></body></html>"
            )
        elif path == "/network":
            body = (
                '<html><body>Allocation application is loading. The primary report is f'
                'etched separately.<script>fetch("/data").then(r=>r.json()).then(x=>win'
                'dow.report=x)</script></body></html>'
            )
        elif path == "/data":
            content = "application/json"
            body = json.dumps(
                {
                    "link": "http://" + self.headers["Host"] + "/network",
                    "content": {"rendered": "<article>" + FACT + "</article>"},
                }
            )
        elif path == "/poison":
            body = (
                '<html><head><link rel="alternate" type="application/json" href="/wrong'
                '"></head><body>Allocation report unavailable. This page contains no re'
                'quested allocation evidence.</body></html>'
            )
        elif path == "/wrong":
            content = "application/json"
            body = json.dumps(
                {
                    "link": "https://different.example/report",
                    "content": {"rendered": "<article>" + FACT + "</article>"},
                }
            )
        elif path == "/cookie-gated" and "visit=1" not in self.headers.get("Cookie", ""):
            status = 401
            body = "<html><body>Prior visitor state is required for this fixture.</body></html>"
        else:
            body = "<html><body><article>" + FACT + "</article></body></html>"
        self.send_response(status)
        self.send_header("Content-Type", content)
        if path == "/cookie-seed":
            self.send_header("Set-Cookie", "visit=1; Path=/; HttpOnly; SameSite=Lax")
        self.end_headers()
        self.wfile.write(body.encode())


ThreadingHTTPServer(("0.0.0.0", 8099), Handler).serve_forever()
