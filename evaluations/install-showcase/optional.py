"""Four real inference requests: first-use initialization, then three cached-model jobs."""

import argparse
import hashlib
import json
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

P = argparse.ArgumentParser()
P.add_argument("--api", required=True)
P.add_argument("--kind", choices=["media", "layout"], required=True)
P.add_argument("--project", required=True)
P.add_argument("--out", type=Path, required=True)
A = P.parse_args()
A.out.mkdir(parents=True, exist_ok=True)
stop = threading.Event()
samples = []


def sample():
    while not stop.is_set():
        ids = subprocess.check_output(
            ["docker", "ps", "-q", "--filter", "label=com.docker.compose.project=" + A.project],
            text=True,
        ).split()
        if ids:
            p = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", "{{json .}}", *ids],
                capture_output=True,
                text=True,
            )
            samples.append(
                dict(at=time.time(), rows=[json.loads(x) for x in p.stdout.splitlines()])
            )
        stop.wait(2)


thread = threading.Thread(target=sample, daemon=True)
thread.start()
rows = []
try:
    for i in range(4):
        payload = dict(
            urls=[
                "http://fixture:8099/formats/" + ("jfk.flac" if A.kind == "media" else "scan.pdf")
            ],
            max_chars=12000,
            cache_mode="bypass",
            public_only=False,
            evidence_namespace="optional-benchmark",
        )
        if A.kind == "layout":
            payload.update(document_mode="layout", page_start=1, page_end=1)
        started = time.monotonic()
        request = urllib.request.Request(
            A.api + "/fetch",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=650) as response:
                row = json.load(response)[0]
            text = row.pop("content", "")
            row.update(
                content_sha256=hashlib.sha256(text.encode()).hexdigest(),
                chars=len(text),
                fact=(
                    "country" in text.lower()
                    if A.kind == "media"
                    else "5120 megawatts" in text.lower()
                ),
            )
            row["worker_used"] = (
                row.get("extraction", {}).get("method") == "speech_recognition"
                if A.kind == "media"
                else row.get("extraction", {}).get("parser") == "docling"
            )
        except Exception as exc:
            row = dict(error=type(exc).__name__ + ": " + str(exc))
        row.update(attempt=i, elapsed_ms=(time.monotonic() - started) * 1000)
        rows.append(row)
        (A.out / "cases.json").write_text(json.dumps(rows, indent=2))
        print(A.kind, i, row.get("quality"), row.get("worker_used"), row["elapsed_ms"], flush=True)
        if not row.get("worker_used") or not row.get("fact"):
            raise SystemExit("Optional inference gate failed; original result retained.")
finally:
    stop.set()
    thread.join(timeout=20)
    (A.out / "resources.json").write_text(json.dumps(samples, indent=2))
