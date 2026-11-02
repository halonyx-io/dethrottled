import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path("/fixtures")
APP = """<h1>Allocation portal</h1><button id="save" onclick="save()">Sign in</button>
<div id="state"></div><iframe id="embed" src="/frame"></iframe>
<a id="popup" target="_blank" href="/popup">Open report</a>
<a id="download" href="/report.csv" download="report.csv">Export</a>
<script>
function db() { return new Promise((ok,bad)=>{let r=indexedDB.open('evidence',1);
 r.onupgradeneeded=()=>r.result.createObjectStore('auth');r.onsuccess=()=>ok(r.result);
 r.onerror=bad;}); }
async function save() { document.cookie='ticket=gold; path=/';
 localStorage.setItem('local','local-kept');
 sessionStorage.setItem('session','session-kept');
 let d=await db();let t=d.transaction('auth','readwrite');
 t.objectStore('auth').put('idb-kept','token');t.oncomplete=()=>location='/app'; }
(async()=>{let d=await db();let r=d.transaction('auth').objectStore('auth').get('token');
 r.onsuccess=()=>document.querySelector('#state').textContent=[document.cookie.includes('ticket=gold'),
 localStorage.getItem('local'),sessionStorage.getItem('session'),r.result].join('|');
 await fetch('/chunked').then(x=>x.json());await fetch('/oversized').then(x=>x.text());
 document.body.insertAdjacentHTML('beforeend','<div id="ready">ready</div>');})();
</script>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        kind = "text/html; charset=utf-8"
        status = 200
        if self.path in ("/app", "/"):
            data = APP.encode()
        elif self.path == "/frame":
            data = (
                b'<h2 id="allocation">ALPHA 7341 tonnes</h2><input id="entry">'
                b'<button onclick="document.querySelector(\'#allocation\').'
                b'textContent=\'updated 291\''
                b'">Update</button>'
            )
        elif self.path == "/popup":
            data = b'<h1 id="report">BETA allocation 420 tonnes</h1>'
        elif self.path == "/chunked":
            data = json.dumps({"region": "ALPHA", "allocation": 7341}).encode()
            kind = "application/json"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for chunk in [data[:10], data[10:]]:
                self.wfile.write(("%x\r\n" % len(chunk)).encode() + chunk + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            return
        elif self.path == "/oversized":
            import gzip

            data = gzip.compress(b"x" * 2000100)
            kind = "text/plain"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        elif self.path == "/report.csv":
            data = b"Region,2024,2025\nALPHA,17,7341\nBETA,291,420\n"
            kind = "text/csv"
        elif self.path == "/table.pdf":
            data = (ROOT / "table.pdf").read_bytes()
            kind = "application/pdf"
        else:
            status = 404
            data = b"missing"
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 19890), Handler).serve_forever()
