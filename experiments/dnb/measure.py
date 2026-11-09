#!/usr/bin/env python3
"""Warm fixture resource comparison; raw samples and cgroup CPU deltas retained."""

import argparse
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from compare import ENDPOINTS, FIXTURE, render, stats

NAMES = {"reference": ["reference-browser", "reference-render"], "candidate": ["candidate"]}


def cpu(side):
    values = []
    for service in NAMES[side]:
        raw = subprocess.check_output(
            [
                "docker",
                "exec",
                f"dethrottled-dnb-lab-{service}-1",
                "cat",
                "/sys/fs/cgroup/cpu.stat",
            ],
            text=True,
        )
        values.append(int(dict(line.split() for line in raw.splitlines())["usage_usec"]))
    return sum(values)


def workload(side):
    return [
        render(ENDPOINTS[side], FIXTURE + ("/long" if n % 2 else "/article")) for n in range(10)
    ]


def main(output):
    records = []
    for side in ENDPOINTS:
        render(ENDPOINTS[side], FIXTURE + "/article")
    for repeat in range(3):
        for side in ["reference", "candidate"] if repeat % 2 == 0 else ["candidate", "reference"]:
            before = cpu(side)
            began = time.monotonic()
            samples = []
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(workload, side)
                while not future.done():
                    samples.append({"elapsed_s": time.monotonic() - began, "containers": stats()})
                results = future.result()
            records.append(
                {
                    "side": side,
                    "repeat": repeat,
                    "requests": 10,
                    "elapsed_s": time.monotonic() - began,
                    "cpu_seconds": (cpu(side) - before) / 1e6,
                    "successes": sum(r["body"].get("success", False) for r in results),
                    "latency_ms": [r["elapsed_ms"] for r in results],
                    "samples": samples,
                }
            )
    output.write_text(
        json.dumps(
            {
                "workload": "10 sequential .5s-settle article/long renders per phase",
                "records": records,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps(
            [{k: v for k, v in r.items() if k not in {"samples", "latency_ms"}} for r in records]
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    main(parser.parse_args().output)
