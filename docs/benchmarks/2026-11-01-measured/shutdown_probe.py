import json
import os
import sqlite3
import subprocess
import time
import urllib.request
from pathlib import Path

r = Path(__file__).parent
rows = []
for label, image, port in [
    ("threaded", "dethrottled:measured-pre-cache", 18406),
    ("isolated", "dethrottled:measured-candidate", 18407),
]:
    d = r / ("shutdown-" + label)
    d.mkdir(exist_ok=True)
    with (
        sqlite3.connect(
            "file:/var/lib/docker/volumes/dethrottled_dethrottled-data/_data/corpus.sqlite?mode=ro",
            uri=True,
        ) as src,
        sqlite3.connect(d / "corpus.sqlite") as dst,
    ):
        src.backup(dst)
    # Force a sizeable unfinished index in the isolated copy; leave production untouched.
    with sqlite3.connect(d / "corpus.sqlite") as db:
        db.execute("DELETE FROM passages WHERE model LIKE 'e5-%'")
    os.chown(d, 10001, 10001)
    for p in d.iterdir():
        os.chown(p, 10001, 10001)
    name = "dethrottled-shutdown-" + label
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--label",
            "com.docker.compose.project=dethrottled-measured",
            "--ulimit",
            "core=0",
            "-p",
            "127.0.0.1:" + str(port) + ":8787",
            "-v",
            str(d) + ":/data",
            "-e",
            "DETHROTTLED_MULTILINGUAL_CORPUS=1",
            image,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    for _ in range(80):
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:" + str(port) + "/health", timeout=1
            ) as f:
                json.load(f)
            break
        except OSError:
            time.sleep(0.1)
    deadline = time.monotonic() + 45
    count = 0
    while time.monotonic() < deadline and not count:
        with sqlite3.connect(d / "corpus.sqlite") as db:
            count = db.execute("SELECT COUNT(*) FROM passages WHERE model LIKE 'e5-%'").fetchone()[
                0
            ]
        if not count:
            time.sleep(0.1)
    assert count > 0, "did not reach active backfill"
    time.sleep(0.1)
    start = time.monotonic()
    subprocess.run(["docker", "stop", "-t", "10", name], check=True, stdout=subprocess.DEVNULL)
    state = json.loads(
        subprocess.check_output(
            ["docker", "inspect", "--format", "{{json .State}}", name], text=True
        )
    )
    row = {
        "build": label,
        "migrated_before_stop": count,
        "stop_ms": round((time.monotonic() - start) * 1000),
        "exit_code": state["ExitCode"],
        "oom_killed": state["OOMKilled"],
    }
    rows.append(row)
    print(row, flush=True)
    subprocess.run(["docker", "rm", "-fv", name], check=True, stdout=subprocess.DEVNULL)
(r / "shutdown-results.json").write_text(json.dumps(rows, indent=2))
assert rows[1]["exit_code"] == 0 and rows[1]["stop_ms"] < 5000
