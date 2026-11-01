import json
import time
import urllib.request
from pathlib import Path

root = Path(__file__).parent
rows = []


def call(port, path, body):
    req = urllib.request.Request(
        "http://127.0.0.1:" + str(port) + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=55) as r:
        return json.load(r)


for label, port in [("baseline", 18413), ("candidate", 18412)]:
    for query in [
        "Python sqlite3 official documentation",
        "llvmpipe Mesa documentation",
        "Cloudflare challenge clearance documentation",
    ]:
        start = time.monotonic()
        d = call(port, "/search", {"query": query})
        rows.append(
            {
                "build": label,
                "kind": "search",
                "query": query,
                "elapsed_ms": round((time.monotonic() - start) * 1000),
                "response": d,
            }
        )
        (root / "live-search.json").write_text(json.dumps(rows, indent=2))
        print(label, query, d.get("ok"), len(d.get("results", [])), flush=True)
    body = {
        "url": "https://bot.sannysoft.com/",
        "public_only": True,
        "allowed_hosts": ["bot.sannysoft.com"],
        "screenshot": "never",
        "steps": [
            {"action": "wait", "ms": 3000},
            {"action": "html", "selector": "body", "max_chars": 60000},
        ],
    }
    d = call(port, "/drive", body)
    html = d["steps"][-1].get("data", "")
    from html.parser import HTMLParser

    class Rows(HTMLParser):
        def __init__(self):
            super().__init__()
            self.rows = []
            self.cells = None
            self.cell = None

        def handle_starttag(self, t, a):
            if t == "tr":
                self.cells = []
            if t == "td" and self.cells is not None:
                self.cell = ""

        def handle_data(self, s):
            if self.cell is not None:
                self.cell += s

        def handle_endtag(self, t):
            if t == "td" and self.cell is not None:
                self.cells.append(self.cell.strip())
                self.cell = None
            if t == "tr" and self.cells is not None:
                if len(self.cells) >= 2 and self.cells[0] in [
                    "WebDriver (New)",
                    "Chrome (New)",
                    "Plugins Length (Old)",
                    "Languages (Old)",
                    "WebGL Vendor",
                    "WebGL Renderer",
                ]:
                    self.rows.append(self.cells[:2])
                self.cells = None

    p = Rows()
    p.feed(html)
    (root / (label + "-sannysoft.json")).write_text(
        json.dumps({"ok": d["ok"], "checks": p.rows}, indent=2)
    )
    print(label, p.rows, flush=True)
