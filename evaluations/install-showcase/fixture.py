"""Existing controlled browser contracts plus generated native document fixtures."""
import importlib.util
import mimetypes
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

spec = importlib.util.spec_from_file_location('release_fixture', '/evaluations/release/fixture.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Handler(module.Handler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith('/formats/'):
            name = path.removeprefix('/formats/')
            if '/' in name or '..' in name:
                self.send_error(404)
                return
            target = Path('/formats') / name
            if not target.is_file():
                self.send_error(404)
                return
            body = target.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', mimetypes.guess_type(name)[0]
                             or 'application/octet-stream')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()


ThreadingHTTPServer(('0.0.0.0', 8099), Handler).serve_forever()
