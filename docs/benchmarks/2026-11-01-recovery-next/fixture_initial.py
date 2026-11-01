# ruff: noqa: E501
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ARTICLE = (
    "<article>" + ("The allocation is 7341 tonnes. Verified source material. " * 35) + "</article>"
)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/slow.js"):
            time.sleep(20)
            body = "void 0;"
            kind = "text/javascript"
        elif self.path.startswith("/delay.js"):
            time.sleep(2)
            body = "void 0;"
            kind = "text/javascript"
        elif self.path == "/slow":
            body = "<html><body>" + ARTICLE + '<script src="/slow.js"></script></body></html>'
            kind = "text/html"
        elif self.path == "/loading":
            body = (
                '<html><head><script src="/delay.js"></script></head><body>'
                + ARTICLE
                + "</body></html>"
            )
            kind = "text/html"
        elif self.path == "/webgl":
            body = """<html><body><script>const g=document.createElement('canvas').getContext('webgl');let valid=false;if(g){g.clearColor(1,0,0,1);g.clear(g.COLOR_BUFFER_BIT);const p=new Uint8Array(4);g.readPixels(0,0,1,1,g.RGBA,g.UNSIGNED_BYTE,p);valid=p[0]===255&&p[3]===255;}document.body.innerHTML=valid?'<article>Rendered allocation is 7341 tonnes. '+('Actual canvas readback verified. '.repeat(40))+'</article>':'WebGL unavailable';</script></body></html>"""
            kind = "text/html"
        else:
            body = "<html><body>" + ARTICLE + "</body></html>"
            kind = "text/html"
        raw = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except BrokenPipeError:
            pass

    def log_message(self, *a):
        pass


ThreadingHTTPServer(("0.0.0.0", 19890), Handler).serve_forever()
