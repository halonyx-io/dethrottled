import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(os.getenv("DETHROTTLED_EVAL_OUTPUT", "evaluation-results"))
ROOT.mkdir(parents=True, exist_ok=True)
records = []


def call(build, label, payload):
    port = 18390 if build == "baseline" else 18391
    started = time.monotonic()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/drive",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=70) as response:
            status = response.status
            result = json.load(response)
    except urllib.error.HTTPError as error:
        status = error.code
        result = json.load(error)
    row = {
        "build": build,
        "case": label,
        "input": payload,
        "http_status": status,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "result": result,
    }
    records.append(row)
    (ROOT / "browser-benchmark.json").write_text(json.dumps(records, indent=2))
    return row


def ready(port):
    for _ in range(45):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2):
                return
        except Exception:
            time.sleep(1)
    raise RuntimeError("not ready")


for build in ["baseline", "candidate"]:
    ready(18390 if build == "baseline" else 18391)
    base = {
        "session": "dependable-" + uuid.uuid4().hex[:8],
        "allowed_hosts": ["dethrottled-dependable-fixture"],
        "screenshot": "never",
        "timeout_ms": 40000,
    }
    call(
        build,
        "setup",
        {
            **base,
            "url": "http://dethrottled-dependable-fixture:19890/app",
            "steps": [{"action": "wait_for", "selector": "#ready", "ms": 10000}],
        },
    )
    row = call(
        build,
        "chunked-json",
        {**base, "steps": [{"action": "network", "name": "body", "value": "/chunked"}]},
    )
    row["pass"] = bool(row["result"].get("ok")) and "7341" in str(row["result"])
    row = call(
        build,
        "decoded-body-limit",
        {**base, "steps": [{"action": "network", "name": "body", "value": "/oversized"}]},
    )
    row["pass"] = not row["result"].get("ok", True) and "over_2MB" in str(row["result"])
    row = call(
        build,
        "iframe-read",
        {**base, "steps": [{"action": "text", "frame": "#embed", "selector": "#allocation"}]},
    )
    row["pass"] = bool(row["result"].get("ok")) and "ALPHA 7341 tonnes" in str(row["result"])
    row = call(
        build,
        "iframe-act",
        {
            **base,
            "steps": [
                {"action": "click", "frame": "#embed", "selector": "button"},
                {"action": "text", "frame": "#embed", "selector": "#allocation"},
            ],
        },
    )
    row["pass"] = bool(row["result"].get("ok")) and "updated 291" in str(row["result"])
    call(
        build,
        "open-popup",
        {
            **base,
            "steps": [{"action": "click", "selector": "#popup"}, {"action": "wait", "ms": 300}],
        },
    )
    row = call(
        build,
        "popup-read",
        {
            **base,
            "steps": [
                {"action": "tabs"},
                {"action": "switch_tab", "index": 1},
                {"action": "text", "selector": "#report"},
            ],
        },
    )
    row["pass"] = bool(row["result"].get("ok")) and "BETA allocation 420 tonnes" in str(
        row["result"]
    )
    call(build, "return-to-main", {**base, "steps": [{"action": "switch_tab", "index": 0}]})
    call(
        build,
        "save-authentication",
        {
            **base,
            "steps": [
                {"action": "click", "selector": "#save"},
                {
                    "action": "wait_for",
                    "selector": '#state:text-is("true|local-kept|session-kept|idb-kept")',
                    "ms": 10000,
                },
                {"action": "text", "selector": "#state"},
                {"action": "checkpoint"},
            ],
        },
    )
    subprocess.run(
        ["sudo", "-n", "docker", "restart", "dethrottled-dependable-browser-" + build],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    ready(18390 if build == "baseline" else 18391)
    row = call(
        build,
        "restart-four-storage-types",
        {
            **base,
            "steps": [
                {"action": "wait_for", "selector": "#ready", "ms": 10000},
                {"action": "text", "selector": "#state"},
            ],
        },
    )
    row["pass"] = bool(row["result"].get("ok")) and "true|local-kept|session-kept|idb-kept" in str(
        row["result"]
    )
    row = call(build, "action-history", {**base, "steps": [{"action": "history"}]})
    row["pass"] = bool(row["result"].get("ok")) and "sequence" in str(row["result"])
    row = call(
        build,
        "download",
        {**base, "steps": [{"action": "download", "selector": "#download", "ms": 10000}]},
    )
    row["pass"] = bool(row["result"].get("ok")) and "download_b64" in str(row["result"])
    call(build, "close", {**base, "close_session": True})
    (ROOT / "browser-benchmark.json").write_text(json.dumps(records, indent=2))
print(
    json.dumps(
        {
            b: {r["case"]: r["pass"] for r in records if r["build"] == b and "pass" in r}
            for b in ["baseline", "candidate"]
        },
        indent=2,
    )
)
