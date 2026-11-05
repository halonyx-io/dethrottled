"""Controlled corpus HTTP load, idle versus concurrent native indexing; no web traffic."""

import argparse
import concurrent.futures
import json
import os
import statistics
import subprocess
import time
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.container.startswith("corpus-v2-"):
        raise SystemExit("Isolated validation container required")
    base = "http://127.0.0.1:%d" % args.port

    def get(path):
        with urllib.request.urlopen(base + path, timeout=30) as response:
            return json.load(response)

    def one(index):
        started = time.perf_counter()
        data = get("/corpus/search?q=API-TAIL-FACT-1234567&mode=hybrid")
        useful = any(
            "API-TAIL-FACT-1234567" in row["text"] and "quantity 47" in row["text"]
            for row in data.get("results", [])
        )
        return {
            "trial": index,
            "elapsed_ms": (time.perf_counter() - started) * 1000,
            "ok": data.get("ok"),
            "facts_retained": useful,
        }

    def phase():
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            rows = list(pool.map(one, range(48)))
        times = sorted(row["elapsed_ms"] for row in rows)
        return {
            "trials": rows,
            "p50_ms": statistics.median(times),
            "p95_ms": times[45],
            "fact_successes": sum(row["facts_retained"] for row in rows),
        }

    one(-1)
    idle = phase()
    seed = """
from dethrottled.corpus_v2 import CorpusV2
text='\\n\\n'.join('## Inspection %d\\n'%i+
     ('This source records maintenance measurements at station %d. '%i)*8 for i in range(900))
s=CorpusV2()
print(s.enqueue('https://example.org/concurrency','Concurrent evidence',text,
                {'corpus_visibility':'public'}))
"""
    subprocess.check_call(
        ["docker", "exec", args.container, "python", "-c", seed], stdout=subprocess.DEVNULL
    )
    deadline = time.monotonic() + 90
    while not get("/corpus/stats")["index"]["jobs"].get("running"):
        if time.monotonic() > deadline:
            raise TimeoutError("worker did not start")
        time.sleep(0.01)
    indexing = phase()
    while get("/corpus/stats")["index"]["jobs"].get("running"):
        if time.monotonic() > deadline:
            raise TimeoutError("worker did not finish")
        time.sleep(0.1)
    report = {
        "concurrency": 8,
        "requests_per_phase": 48,
        "idle": idle,
        "indexing": indexing,
        "host_load_average": os.getloadavg(),
        "status": get("/corpus/stats"),
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {key: value for key, value in report.items() if key not in ("idle", "indexing")}
            | {"idle_p95_ms": idle["p95_ms"], "indexing_p95_ms": indexing["p95_ms"]}
        )
    )
    assert idle["fact_successes"] == indexing["fact_successes"] == 48


if __name__ == "__main__":
    main()
