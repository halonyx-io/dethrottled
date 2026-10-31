"""Serve synthetic evidence; log every request for acquisition auditing."""

import argparse
import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

parser = argparse.ArgumentParser()
parser.add_argument("--assets", type=Path, required=True)
parser.add_argument("--log", type=Path, required=True)
parser.add_argument("--port", type=int, default=18901)
args = parser.parse_args()
lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        pieces = urlsplit(self.path).path.strip("/").split("/")
        # URL form: /unique-run/v1/source.txt. Relative assets preserve the run.
        if len(pieces) != 3 or pieces[1] not in {"v1", "v2"}:
            self.send_error(404)
            return
        file = args.assets / pieces[1] / pieces[2]
        if file.parent != args.assets / pieces[1] or not file.is_file():
            self.send_error(404)
            return
        raw = file.read_bytes()
        with lock, args.log.open("a") as out:
            out.write(
                json.dumps(
                    {
                        "path": self.path,
                        "bytes": len(raw),
                        "user_agent": self.headers.get("User-Agent"),
                    }
                )
                + "\n"
            )
        self.send_response(200)
        self.send_header(
            "Content-Type", mimetypes.guess_type(file)[0] or "application/octet-stream"
        )
        self.send_header("Content-Length", str(len(raw)))
        if file.suffix == ".pdf":
            self.send_header("Content-Disposition", 'attachment; filename="' + file.name + '"')
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass


ThreadingHTTPServer(("172.17.0.1", args.port), Handler).serve_forever()
