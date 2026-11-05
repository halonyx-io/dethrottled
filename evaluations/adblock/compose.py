"""Small live acquisition smoke for an isolated candidate Compose project.

Run separately with --label on/off after recreating only this disposable project.
Do not use production volumes. Live source changes prevent exact paired relevance claims.
"""

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--base", default="http://127.0.0.1:18987")
parser.add_argument("--label", choices=["on", "off"], required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()
report = {"label": args.label, "cases": []}


def post(path, body):
    request = urllib.request.Request(
        args.base + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    return json.load(urllib.request.urlopen(request, timeout=150))


report["adblock"] = json.load(urllib.request.urlopen(args.base + "/stats"))["adblock"]
started = time.monotonic()
found = post(
    "/v2/search",
    {"query": "Python sqlite3 connect documentation", "limit": 3, "cache_mode": "bypass"},
)
report["search"] = {
    "elapsed_ms": (time.monotonic() - started) * 1000,
    "outcome": found["outcome"],
    "degraded": found["degraded"],
    "urls": [r["url"] for r in found["results"]],
    "attempts": found["attempts"],
}
for url, focus in [
    ("https://docs.python.org/3/library/sqlite3.html", "sqlite3.connect"),
    ("https://www.rfc-editor.org/rfc/rfc8446.html", "TLS 1.3"),
]:
    started = time.monotonic()
    payload = post(
        "/fetch",
        {
            "urls": [url],
            "max_chars": 3000,
            "focus": focus,
            "cache_mode": "bypass",
            "render": "never",
            "recovery": "manual",
        },
    )[0]
    report["cases"].append(
        {
            "url": url,
            "elapsed_ms": (time.monotonic() - started) * 1000,
            "quality": payload["quality"],
            "tier": payload["tier"],
            "fact_anchor_retained": focus.casefold() in payload.get("content", "").casefold(),
            "content_chars": len(payload.get("content", "")),
            "failure_reason": payload.get("failure_reason"),
            "content_sha256": hashlib.sha256(payload.get("content", "").encode()).hexdigest(),
        }
    )
    time.sleep(1)
started = time.monotonic()
drive = post(
    "/drive",
    {
        "url": "https://www.reddit.com/r/Python/",
        "timeout_ms": 30000,
        "screenshot": "never",
        "allowed_hosts": ["www.reddit.com", "reddit.com"],
        "public_only": True,
        "steps": [{"action": "text", "selector": "body", "max_chars": 2000}],
    },
)
report["reddit_drive"] = {
    "elapsed_ms": (time.monotonic() - started) * 1000,
    "ok": drive.get("ok"),
    "access": drive.get("access"),
    "adblock": drive.get("adblock"),
    "steps": [
        {
            "ok": r.get("ok"),
            "reason": r.get("reason"),
            "action": r.get("action"),
            "text_chars": len(r["data"]) if isinstance(r.get("data"), str) else 0,
        }
        for r in drive.get("steps", [])
    ],
}
report["blocked_top_level"] = post(
    "/fetch",
    {
        "urls": ["https://a.google-analytics.com/collect"],
        "max_chars": 500,
        "render": "never",
        "recovery": "manual",
    },
)[0]
# Retain diagnostics only, not a third party's page text.
report["blocked_top_level"].pop("content", None)
Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
print(
    json.dumps(
        {
            "label": args.label,
            "search": report["search"]["outcome"],
            "facts": [r["fact_anchor_retained"] for r in report["cases"]],
            "reddit_access": report["reddit_drive"]["access"],
        }
    )
)
