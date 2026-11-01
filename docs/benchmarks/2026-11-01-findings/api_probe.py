import json
import time
import urllib.error
import urllib.request
from pathlib import Path

r = Path(__file__).parent
rows = []


def call(path, body=None):
    req = urllib.request.Request(
        "http://127.0.0.1:18405" + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=120) as f:
            status = f.status
            data = json.load(f)
    except urllib.error.HTTPError as e:
        status = e.code
        data = json.load(e)
    rows.append(
        {
            "path": path,
            "input": body,
            "status": status,
            "elapsed_ms": round((time.monotonic() - start) * 1000),
            "response": data,
        }
    )
    (r / "candidate-api.json").write_text(json.dumps(rows, indent=2))
    return status, data


status, caps = call("/v2/capabilities")
assert (
    caps["version"] == "0.9.0"
    and "headed" in caps["fetch_tiers"]
    and "format" in caps["optional_fields"]["fetch"]
    and "raw" not in caps["optional_fields"]["fetch"]
)
base = "http://dethrottled-findings-fixture:19890"
for index in range(2):
    status, data = call(
        "/fetch",
        {
            "urls": [base + "/report"],
            "fresh": True,
            "max_chars": 4000,
            "evidence_namespace": "api-probe",
        },
    )
    row = data[0]
    assert row["quality"] == "ok" and "7341 tonnes" in row["content"]
    assert row["acquisition_attempts"][-1]["tier"] == "headed"
    assert row["browser_recovery"]["challenge_polls"] == (2 if index == 0 else 0)
status, data = call(
    "/fetch", {"urls": [base + "/report"], "max_chars": 4000, "evidence_namespace": "api-probe"}
)
assert data[0]["cached"] and data[0]["acquisition_attempts"][0]["tier"] == "cache"
status, short = call("/fetch", {"urls": [base + "/short"], "render": "never", "fresh": True})
assert short[0]["quality"] == "thin" and "17:30" in short[0]["content"]
status, empty = call("/fetch", {"urls": [base + "/empty"], "render": "never", "fresh": True})
assert empty[0]["quality"] == "failed"
status, bad = call("/search", {"query": "fixture", "category": "news"})
assert status == 422
print(
    "PASS isolated API: automatic recovery, reuse/cache, thin/blank honesty, "
    "strict REST and capability spelling"
)
