#!/usr/bin/env python3
"""Compare repeatable local Dethrottled work on two hosts.

Serve the generated fixtures with ``python3 -m http.server 18080 --bind 0.0.0.0``
on the benchmark host. Run the API image with host networking, its own empty
data volume, and no sidecar URLs. Loopback aliases distribute requests among
domains so the normal per-domain pacing does not define all throughput.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import platform
import shlex
import statistics
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from benchmark_endpoints import sample_stats, summarize

FILES = (
    "article.html", "table.html", "values.csv", "report.pdf", "scan.pdf",
    "report.docx", "report.xlsx", "report.pptx", "report.odt",
    "report.epub", "report.rtf", "wrong.pdf", "missing.html",
)


def request(base: str, path: str, payload: dict | None = None, timeout: int = 90) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        base + path, data=data, method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = response.status
            body = json.load(response)
        error = None
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        status, body, error = None, None, str(exc)[:180]
    return {"ms": round((time.perf_counter() - start) * 1000, 1),
            "status": status, "body": body, "error": error}


def summary(samples: list[dict], useful=lambda row: row["status"] == 200) -> dict:
    times = sorted(row["ms"] for row in samples)
    count = len(times)
    return {"requests": count,
            "useful": sum(bool(useful(row)) for row in samples),
            "median_ms": round(statistics.median(times), 1) if times else None,
            "p95_ms": times[max(0, (95 * count + 99) // 100 - 1)] if times else None,
            "min_ms": times[0] if times else None,
            "max_ms": times[-1] if times else None}


def pool(work, total: int, workers: int) -> tuple[list[dict], float]:
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        samples = list(executor.map(work, range(total)))
    return samples, round(time.perf_counter() - started, 3)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:18787")
    parser.add_argument("--fixture-port", type=int, default=18080)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--container", action="append", default=[])
    args = parser.parse_args()
    api = args.api.rstrip("/")

    def fixture(name: str, n: int = 0) -> str:
        return f"http://127.0.0.{2 + (n % 8)}:{args.fixture_port}/{name}"

    if request(api, "/health")["status"] != 200:
        raise SystemExit("API health check failed")
    try:
        with urllib.request.urlopen(fixture("article.html"), timeout=5) as response:
            fixture_ok = response.status == 200
    except urllib.error.URLError:
        fixture_ok = False
    if not fixture_ok:
        raise SystemExit("fixture server is unavailable")

    resources: list[dict] = []
    stop = threading.Event()
    thread = None
    if args.container:
        thread = threading.Thread(target=sample_stats, args=(shlex.split(args.docker),
                                  args.container, stop, resources), daemon=True)
        thread.start()
        time.sleep(2)

    result = {"meta": {"host": platform.node(), "machine": platform.machine(),
                       "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                       "api": api, "repeats": args.repeats},
              "formats": [], "load": {}}

    # Named fetches bypass the extraction cache. A good result must actually
    # contain the fixture's marker; HTTP 200 on its own is not accepted.
    for index, name in enumerate(FILES):
        samples = []
        for repeat in range(args.repeats):
            response = request(api, "/fetch", {
                "urls": [fixture(name, index + repeat * len(FILES))],
                "fresh": True, "render": "never", "max_chars": 12000,
            })
            row = (response["body"] or [{}])[0] if isinstance(response["body"], list) else {}
            samples.append({"ms": response["ms"], "status": response["status"],
                            "error": response["error"], "quality": row.get("quality"),
                            "tier": row.get("tier"),
                            "chars": len(row.get("content") or ""),
                            "marker": "cedar observatory" in
                            (row.get("content") or "").lower(),
                            "failure_reason": row.get("failure_reason")})
        expected_good = name not in {"wrong.pdf", "missing.html"}
        def expected(row, good=expected_good):
            return row["status"] == 200 and (
                (row["quality"] == "ok" and row["marker"])
                if good else row["quality"] == "failed")

        item = {"file": name, "expected_good": expected_good,
                "summary": summary(samples, expected),
                "samples": samples}
        result["formats"].append(item)
        print(name, item["summary"], flush=True)

    # The corpus's background writer may still be indexing the last page.
    time.sleep(3)
    query = urllib.parse.urlencode({"q": "cedar observatory 5120 megawatts",
                                    "floor": "0", "limit": "3"})
    for endpoint, levels, count in (("health", (1, 8, 32), 120),
                                    ("fetch", (1, 4, 8), 24),
                                    ("corpus", (1, 4, 8), 48)):
        for workers in levels:
            if endpoint == "health":
                def work(_):
                    return request(api, "/health", timeout=30)

                def useful(row):
                    return row["status"] == 200
            elif endpoint == "fetch":
                def work(n):
                    response = request(api, "/fetch", {
                        "urls": [fixture("article.html", n)], "fresh": True,
                        "render": "never", "max_chars": 4000}, timeout=90)
                    content = ((response["body"] or [{}])[0].get("content") or ""
                               if isinstance(response["body"], list) else "")
                    response["good"] = "cedar observatory" in content.lower()
                    response.pop("body", None)
                    return response
                def useful(row):
                    return row["status"] == 200 and row.get("good")
            else:
                def work(_):
                    response = request(api, "/corpus/search?" + query, timeout=30)
                    response["good"] = bool((response["body"] or {}).get("results"))
                    response.pop("body", None)
                    return response
                def useful(row):
                    return row["status"] == 200 and row.get("good")
            samples, seconds = pool(work, count, workers)
            result["load"][f"{endpoint}_c{workers}"] = {
                "summary": {**summary(samples, useful), "wall_s": seconds,
                            "throughput_rps": round(count / seconds, 2)},
                "samples": samples}
            print(endpoint, workers, result["load"][f"{endpoint}_c{workers}"]["summary"],
                  flush=True)

    stop.set()
    if thread:
        thread.join(timeout=25)
    result["resource_samples"] = resources
    result["resource_summary"] = summarize([], resources)["resources"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
