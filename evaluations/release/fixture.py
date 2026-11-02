"""Combined deterministic release fixtures; no Internet or credentials required."""

import importlib.util
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


loop = load("loop_fixture", ROOT / "read-loop/fixture.py")
browser = load("browser_fixture", ROOT / "dependable/browser_fixture.py")
browser.ROOT = ROOT / "dependable/fixtures"


class Handler(loop.Handler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self.close_connection = True
        path = urlsplit(self.path).path
        if path in {
            "/app",
            "/frame",
            "/popup",
            "/chunked",
            "/oversized",
            "/report.csv",
            "/table.pdf",
        }:
            browser.Handler.do_GET(self)
        elif path in {"/quick.msg", "/Simple.xlsb"}:
            data = (Path(__file__).parent / "fixtures" / path.lstrip("/")).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path == "/js":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(("<html><body><article data-label=\"Bob's report\" id=\"report\">"
                "Loading</article><script>setTimeout(()=>document.querySelector('#report')."
                "textContent=" + repr(loop.FACT) + ",200)</script></body></html>").encode())
        elif path == "/late.csv":
            text = "id,quantity,unit\n" + "".join(f"R{i},{i * 17},tonnes\n" for i in range(2601))
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.end_headers()
            self.wfile.write(text.encode())
        elif path == "/long-read":
            text = "<html><body><article>" + "".join(
                f"<p>Entry {i}: This record provides allocation coverage evidence.</p>"
                for i in range(2500)) + "<p>ALLOCATION_TOTAL_7341</p></article></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(text.encode())))
            self.end_headers()
            self.wfile.write(text.encode())
        elif path == "/missing":
            self.send_error(404)
        else:
            super().do_GET()


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8099), Handler).serve_forever()
