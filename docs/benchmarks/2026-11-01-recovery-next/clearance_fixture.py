# ruff: noqa: E501
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ARTICLE = (
    "<html><title>Regional report</title><body><article><h1>Regional allocation</h1><p>ALPHA received 7341 tonnes in 2025.</p>"
    + (
        "<p>This published allocation is measured in tonnes, with source evidence and a stated reporting year.</p>"
        * 20
    )
    + "</article></body></html>"
)
CHALLENGE = """<html><title>Verification Required</title><body><h1>Verification Required</h1><p>Please wait while we verify your request...</p><script>setTimeout(()=>{document.cookie='fixture_clearance=1; path=/'; location.reload()},2200)</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        framed = self.path == "/framed"
        cleared = (
            "fixture_frame_clearance=1" if framed else "fixture_clearance=1"
        ) in self.headers.get("Cookie", "")
        body = ARTICLE if cleared or self.path == "/plain" else CHALLENGE
        if framed and not cleared:
            body = "<html><title>Verification Required</title><body>Verification Required. Please wait while we verify your request<iframe src=\"http://dethrottled-findings-frame:19890/frame\"></iframe><script>addEventListener('message',e=>{if(e.data==='fixture-ready'){document.cookie='fixture_frame_clearance=1; path=/';location.reload()}})</script></body></html>"
        if self.path == "/frame":
            body = "<script>setTimeout(()=>parent.postMessage('fixture-ready','*'),2200)</script>"
        if self.path == "/private-frame":
            body = '<h1>Private frame must be blocked</h1><iframe src="http://127.0.0.1:19888/health"></iframe>'
        if self.path == "/popup":
            body = '<a id="popup" target="_blank" href="http://dethrottled-findings-frame:19890/plain">Open other host</a>'
        if self.path == "/short":
            body = (
                "<body><p>A real short announcement: the regional meeting starts at 17:30.</p><script>"
                + ("var p=1;" * 200)
                + "</script></body>"
            )
        if self.path == "/empty":
            body = "<body>   <script>" + ("var p=1;" * 200) + "</script></body>"
        if self.path in ["/frame", "/private-frame", "/popup", "/short", "/empty"]:
            cleared = True

        data = body.encode()
        self.send_response(200 if cleared or self.path == "/plain" else 403)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("0.0.0.0", 19890), Handler).serve_forever()
