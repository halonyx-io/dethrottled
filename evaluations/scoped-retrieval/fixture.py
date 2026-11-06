"""Private integration fixture: JavaScript UI and nested sitemap discovery."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        base = "http://" + self.headers["Host"]
        if self.path == "/index.xml":
            text = f"<sitemapindex><sitemap><loc>{base}/urls.xml</loc></sitemap></sitemapindex>"
            kind = "application/xml"
        elif self.path == "/urls.xml":
            text = (
                "<urlset>"
                + "".join(f"<url><loc>{base}/{p}</loc></url>" for p in ("a", "b", "c"))
                + "</urlset>"
            )
            kind = "application/xml"
        else:
            text = """<html><body><h1>Loading</h1><div class="price"></div>
<button id="confirm" onclick="this.textContent='Confirmed 7341 tonnes'">Confirm</button>
<script>setTimeout(()=>{document.querySelector('h1').textContent='Verified live DOM';
document.querySelector('.price').textContent='17.25 GBP';
document.body.dataset.ready='yes';},150)</script></body></html>"""
            kind = "text/html"
        data = text.encode()
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
