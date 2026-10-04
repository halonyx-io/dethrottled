#!/usr/bin/env python3
"""Run the same 50 English search requests at a fixed concurrency level."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import shlex
import threading
import time
from pathlib import Path

from benchmark_endpoints import QUERIES, api_call, sample_stats, summarize


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True)
    parser.add_argument("--workers", type=int, choices=(3, 8), required=True)
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

    def one(numbered: tuple[int, tuple[str, str]]) -> dict:
        number, (category, query) = numbered
        response = api_call(args.api.rstrip("/"), "/search",
                            {"query": query, "limit": 3, "fresh": True})
        rows = response["body"] if isinstance(response["body"], list) else []
        valid = [r for r in rows if r.get("url", "").startswith(("http://", "https://"))
                 and len(r.get("title") or "") >= 10]
        rich = sum(len(r.get("snippet") or "") >= 25 for r in valid)
        return {"number": number, "category": category, "query": query,
                "elapsed_ms": response["elapsed_ms"],
                "http_status": response["http_status"], "error": response["error"],
                "result_count": len(rows), "valid_result_count": len(valid),
                "rich_snippet_count": rich, "useful": bool(valid)}

    started = time.time()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            cases = list(pool.map(one, enumerate(QUERIES, 1)))
    finally:
        stop.set()
        thread.join(timeout=25)
    ended = time.time()
    report = {"meta": {"mode": "search-parallel", "workers": args.workers,
                       "started_at_epoch": started, "ended_at_epoch": ended,
                       "duration_s": round(ended - started, 2),
                       "container_names": args.container},
              "cases": cases, "resource_samples": resources,
              "summary": summarize(cases, resources)}
    report["summary"]["throughput_qps"] = round(len(cases) / (ended - started), 2)
    report["summary"]["rich_cases"] = sum(c["rich_snippet_count"] >= 2 for c in cases)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print("wrote", args.out)


if __name__ == "__main__":
    main()
