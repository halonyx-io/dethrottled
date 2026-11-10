#!/usr/bin/env python3
"""Capture reference/candidate outcomes; failures are retained, never filtered.

Uses stdlib on the host; lab endpoints must be running. Writes only the chosen
output directory. No account/session data from production is used.
"""

import argparse
import hashlib
import json
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ENDPOINTS = {"reference": "http://127.0.0.1:19982", "candidate": "http://127.0.0.1:19983"}
BROWSERS = {"reference": "http://127.0.0.1:19981", "candidate": "http://127.0.0.1:19983"}
FIXTURE = "http://fixture:8090"
FACTS = {
    "/article": ["cobalt-731", "amber-592", "violet-683"],
    "/tiny": ["quartz-452"],
    "/long": ["cobalt-731", "amber-592"],
    "/redirect": ["cobalt-731", "amber-592", "violet-683"],
    "/missing": [],
}


def request(base, path, payload=None):
    started = time.perf_counter()
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer dnb-disposable-lab-only",
    }
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=75) as r:
            raw, status = r.read(), r.status
        body = json.loads(raw)
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
        try:
            body = json.loads(raw)
        except ValueError:
            body = {"error": raw.decode(errors="replace")}
    except Exception as exc:
        status, body, raw = 0, {"error": str(exc)}, b""
    return {
        "http_status": status,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "bytes": len(raw),
        "body": body,
    }


def render(base, url):
    return request(
        base,
        "/crawl",
        {
            "urls": [url],
            "browser_config": {"type": "BrowserConfig", "params": {"headless": True}},
            "crawler_config": {
                "type": "CrawlerRunConfig",
                "params": {
                    "cache_mode": "bypass",
                    "check_robots_txt": False,
                    "page_timeout": 20000,
                    "delay_before_return_html": 0.5,
                },
            },
        },
    )


def drive(base):
    steps = [
        {"action": "goto", "url": FIXTURE + "/article", "ms": 5000},
        {"action": "fill", "selector": "#name", "value": "Ada"},
        {"action": "type", "selector": "#name", "value": " Lovelace", "delay_ms": 5},
        {"action": "press", "selector": "#name", "value": "Tab"},
        {"action": "select", "selector": "#choice", "value": "b"},
        {"action": "check", "selector": "#check"},
        {"action": "uncheck", "selector": "#check"},
        {"action": "hover", "selector": "#go"},
        {"action": "click", "selector": "#go"},
        {"action": "wait", "ms": 150},
        {"action": "wait_for", "selector": "#delayed"},
        {"action": "text", "selector": "#answer"},
        {"action": "html", "selector": "main", "max_chars": 500},
        {"action": "attr", "selector": "#name", "name": "value"},
        {"action": "count", "selector": "h1"},
        {"action": "snapshot", "selector": "main"},
        {"action": "url"},
        {"action": "title"},
        {"action": "download", "selector": "#download", "ms": 5000},
        {"action": "network", "name": "body", "index": 0},
        {"action": "checkpoint"},
        {"action": "click", "selector": "#popup"},
        {"action": "wait", "ms": 100},
        {"action": "tabs"},
        {"action": "switch_tab", "index": 0},
        {"action": "history"},
        {"action": "read_state"},
        {"action": "scroll"},
        {"action": "expand_details"},
        {"action": "text", "selector": "#frame-fact", "frame": "iframe"},
    ]
    result = request(
        base,
        "/drive",
        {
            "session": "dnb-lab",
            "allowed_hosts": ["fixture"],
            "steps": steps,
            "timeout_ms": 60000,
            "screenshot": "always",
        },
    )
    request(base, "/drive", {"session": "dnb-lab", "close_session": True, "screenshot": "never"})
    # Explicit close deletes checkpoints. This is session recreation only;
    # checkpoint restart/restore is tested separately by verify.py.
    restored = request(
        base,
        "/drive",
        {
            "session": "dnb-lab",
            "url": FIXTURE + "/article",
            "steps": [{"action": "read_state"}],
            "screenshot": "never",
        },
    )
    request(base, "/drive", {"session": "dnb-lab", "close_session": True, "screenshot": "never"})
    return {"run": result, "restored": restored}


def stats():
    raw = subprocess.check_output(
        ["docker", "stats", "--no-stream", "--format", "{{json .}}"], text=True
    )
    return [json.loads(line) for line in raw.splitlines() if "dethrottled-dnb-lab" in line]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    records = []

    def save(name, value):
        (args.output / (name + ".json")).write_text(json.dumps(value, indent=2) + "\n")

    save("resources-before", stats())
    for repeat in range(3):
        for side in ["reference", "candidate"] if repeat % 2 == 0 else ["candidate", "reference"]:
            for path, facts in FACTS.items():
                item = render(ENDPOINTS[side], FIXTURE + path)
                result = (item["body"].get("results") or [{}])[0]
                md = result.get("markdown") or {}
                text = md.get("raw_markdown", "") if isinstance(md, dict) else md
                summary = {
                    "side": side,
                    "repeat": repeat,
                    "path": path,
                    "elapsed_ms": item["elapsed_ms"],
                    "bytes": item["bytes"],
                    "success": result.get("success"),
                    "target_status": result.get("status_code"),
                    "facts": {fact: fact in text for fact in facts},
                    "markdown_chars": len(text),
                    "markdown_sha256": hashlib.sha256(text.encode()).hexdigest(),
                }
                records.append(summary)
                save(f"render-{side}-{repeat}-{path.strip('/')}", item)
    for side, base in BROWSERS.items():
        save("drive-" + side, drive(base))
    # Browser drive and rendering must coexist, with isolated ephemeral contexts.
    for side in ENDPOINTS:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [
                pool.submit(render, ENDPOINTS[side], FIXTURE + "/long"),
                pool.submit(render, ENDPOINTS[side], FIXTURE + "/article"),
                pool.submit(
                    request,
                    BROWSERS[side],
                    "/drive",
                    {
                        "url": FIXTURE + "/article",
                        "steps": [{"action": "title"}],
                        "screenshot": "never",
                    },
                ),
            ]
            save("concurrent-" + side, [f.result() for f in futures])
    if args.live:
        urls = [
            "https://example.com",
            "https://www.reddit.com/r/python/",
            "https://en.wikipedia.org/wiki/HTTP",
            "https://developer.mozilla.org/en-US/docs/Web/JavaScript",
            "https://www.booking.com/",
            "https://www.crunchbase.com/",
        ]
        for n, url in enumerate(urls):
            for side in ["candidate", "reference"] if n % 2 else ["reference", "candidate"]:
                save(f"live-{n}-{side}", {"url": url, **render(ENDPOINTS[side], url)})
                time.sleep(3)
        # Same-family DDG requests are paced and not independent agreement votes.
        for side, base in BROWSERS.items():
            save(
                "search-" + side,
                request(base, "/search", {"query": "Python pathlib documentation", "limit": 5}),
            )
            time.sleep(8)
    save("resources-after", stats())
    save(
        "summary",
        {
            "records": records,
            "median_ms": {
                side: statistics.median(r["elapsed_ms"] for r in records if r["side"] == side)
                for side in ENDPOINTS
            },
        },
    )
    print(
        json.dumps(
            {
                "renders": len(records),
                "failures": sum(not r["success"] for r in records),
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
