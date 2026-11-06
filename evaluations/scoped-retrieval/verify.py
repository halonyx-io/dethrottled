#!/usr/bin/env python3
"""Controlled before/after acquisition and field tests; no external providers.

Run in the same dependency image with PYTHONPATH selecting baseline or candidate.
Use --baseline for 1.6.2 (unsupported features are recorded, not simulated).
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import threading
import time
import tracemalloc
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

from dethrottled import fetch, search
from dethrottled.api_models import FetchBody
from dethrottled.readplan import run as plan
from dethrottled.site import crawl

COUNTS = []
PROSE = "".join(
    f"<p>Paragraph {i}: observations document verified public evidence, "
    "retained facts and source measurements for this controlled experiment.</p>"
    for i in range(180)
)
HTML = (
    "<html><head><title>Fixture report</title></head><body><main>"
    + PROSE
    + '<h1>Allocation report</h1><div class="price">17.25 GBP</div>'
    + "".join(f'<a href="/page/{i}">Report {i}</a>' for i in range(12))
    + "</main></body></html>"
)
RULES = {"title": {"selector": "h1"}, "price": {"selector": ".price"}}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        COUNTS.append(self.path)
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/index")
            self.end_headers()
            return
        data = HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def measure(operation, repeats=7):
    timings, cpu, peaks, counts, results = [], [], [], [], []
    for _ in range(repeats):
        COUNTS.clear()
        tracemalloc.start()
        at, cpu_at = time.perf_counter(), time.process_time()
        result = operation()
        timings.append(round((time.perf_counter() - at) * 1000, 3))
        cpu.append(round((time.process_time() - cpu_at) * 1000, 3))
        peaks.append(tracemalloc.get_traced_memory()[1])
        tracemalloc.stop()
        counts.append(len(COUNTS))
        results.append(result)
    return {
        "samples": repeats,
        "elapsed_ms": timings,
        "median_ms": statistics.median(timings),
        "p95_ms": sorted(timings)[math.ceil(len(timings) * 0.95) - 1],
        "cpu_ms": cpu,
        "python_peak_bytes": peaks,
        "http_requests": counts,
    }, results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    fixture = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=fixture.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{fixture.server_port}/index"
    fetch.MIN_DOMAIN_GAP = 0  # Loopback fixture only, identical on both runs.

    # Never index, start workers, touch production volumes or consult a live engine.
    def read(target):
        result = fetch.fetch_and_extract(
            target,
            max_chars=120000,
            keep_html=True,
            format="html",
            allow_render=False,
            allow_ocr=False,
        )
        return {
            "quality": "ok" if result.get("ok") else "failed",
            "html": result.get("html", ""),
            "content": result.get("text", ""),
            "final_url": result.get("url", target),
        }

    report = {
        "mode": "baseline-1.6.2" if args.baseline else "candidate",
        "scope": "Loopback HTTP, identical HTML/SERP, no live-provider accuracy claim; "
        "tracemalloc is Python allocation peak, not process/container RSS.",
        "fixture_html_bytes": len(HTML.encode()),
        "rows_on_index": 12,
    }
    try:
        report["crawl"], crawls = measure(lambda: crawl([url], read, max_pages=13))
        report["crawl"]["evidence_reads"] = [r["coverage"]["attempted"] for r in crawls]
        if not args.baseline:
            from dethrottled.selectors import fields
            from dethrottled.site import map_site

            report["map"], maps = measure(lambda: map_site([url], read, max_pages=13))
            report["map"]["returned_urls"] = [len(r["sources"]) for r in maps]
            report["map"]["discovery_requests"] = [
                r["coverage"]["discovery_requests"] for r in maps
            ]
            assert all(len(r["sources"]) == 13 and r["coverage"]["attempted"] == 0 for r in maps)

            def selected():
                result = fetch.fetch_and_extract(
                    url, max_chars=800, keep_html=True, allow_render=False, allow_ocr=False
                )
                row = fields(
                    {"quality": "ok", "content": result["text"]},
                    FetchBody(urls=[url], selectors=RULES).selectors,
                    result["html"],
                )
                assert row["structured"] == {"title": "Allocation report", "price": "17.25 GBP"}
                return row

            report["with_selectors"], selected_rows = measure(selected)
            report["with_selectors"]["field_facts_retained"] = [2 for _ in selected_rows]

        report["plain_fetch"], plain = measure(
            lambda: fetch.fetch_and_extract(
                url, max_chars=800, keep_html=False, allow_render=False, allow_ocr=False
            )
        )
        report["plain_fetch"]["facts_in_display_excerpt"] = [
            sum(fact in r["text"] for fact in ["Allocation report", "17.25 GBP"]) for r in plain
        ]
        serp = [{"url": f"https://unrelated.org/{i}", "engine": "yahoo"} for i in range(5)]
        serp += [{"url": f"https://nasa.gov/{i}", "engine": "yahoo"} for i in range(5)]
        calls = []

        def engine(*a, **kw):
            calls.append(kw["params"])
            return SimpleNamespace(status_code=200, json=lambda: {"results": serp})

        with (
            patch.object(search, "SEARXNG_URL", "http://fixture"),
            patch.object(search.requests, "get", engine),
        ):
            rows = search.searxng("climate site:nasa.gov", engines="yahoo", max_items=3)
        admitted = [r["url"] for r in rows if r["url"].startswith("https://nasa.gov/")]
        report["constrained_serp"] = {
            "matching_sources": admitted,
            "requests": len(calls),
            "pages": [c["pageno"] for c in calls],
        }
        report["terminal_policy"] = {}
        for reason in (
            "invalid_url",
            "public_target_required",
            "redirect_target_not_public",
            "ConnectionError",
        ):
            attempts = []
            row = plan(
                "https://fixture.invalid/",
                {"quality": "failed", "failure_reason": reason},
                read=lambda *a: {},
                drive=lambda *a, attempts=attempts, **kw: attempts.append(1) or {"ok": False},
                options={"allow_render": True},
                browser_available=True,
            )
            report["terminal_policy"][reason] = {
                "browser_calls": len(attempts),
                "stop_reason": row["read_plan"]["stop_reason"],
            }
        if not args.baseline:
            assert len(admitted) == 3 and len(calls) == 1
            assert report["terminal_policy"]["invalid_url"]["browser_calls"] == 0
            assert report["terminal_policy"]["ConnectionError"]["browser_calls"] > 0
    finally:
        fixture.shutdown()
        fixture.server_close()
    with open(args.output, "w") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {"mode": report["mode"], "saved": args.output, "matching_sources": len(admitted)},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
