#!/usr/bin/env python3
"""Exercise the optional PDF worker with ten deterministic HTML print jobs."""
from __future__ import annotations

import argparse
import json
import shlex
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from benchmark_endpoints import sample_stats, summarize


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-url", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--container", action="append", default=[])
    args = parser.parse_args()
    resources: list[dict] = []
    stop = threading.Event()
    thread = threading.Thread(target=sample_stats, args=(shlex.split(args.docker),
                              args.container, stop, resources), daemon=True)
    thread.start()
    time.sleep(2)
    cases = []
    started = time.time()
    try:
        for number in range(10):
            html = ("<!doctype html><style>@page{size:A4;margin:18mm}</style>"
                    "<h1>Cedar energy report</h1>" +
                    "".join(f"<p>Section {i}. Cedar observatory measured "
                            f"{5120 + number + i} megawatts in 2026.</p>"
                            for i in range(80)))
            req = urllib.request.Request(
                args.pdf_url.rstrip("/") + "/pdf",
                data=json.dumps({"html": html, "format": "A4"}).encode(),
                method="POST", headers={"Content-Type": "application/json"})
            t0 = time.perf_counter()
            try:
                with urllib.request.urlopen(req, timeout=120) as response:
                    status, body = response.status, response.read()
                error = None
            except (urllib.error.URLError, TimeoutError) as exc:
                status, body, error = None, b"", str(exc)[:180]
            case = {"number": number + 1, "elapsed_ms": round((time.perf_counter()-t0)*1000, 1),
                    "http_status": status, "pdf_bytes": len(body), "error": error,
                    "useful": status == 200 and body.startswith(b"%PDF") and len(body) > 5000}
            cases.append(case)
            print(number + 1, case["elapsed_ms"], case["pdf_bytes"], case["useful"], flush=True)
    finally:
        stop.set()
        thread.join(timeout=25)
    ended = time.time()
    report = {"meta": {"mode": "pdf", "started_at_epoch": started,
                       "ended_at_epoch": ended, "duration_s": round(ended-started, 2),
                       "container_names": args.container},
              "summary": summarize(cases, resources), "cases": cases,
              "resource_samples": resources}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print("wrote", args.out)


if __name__ == "__main__":
    main()
