import json
import time
import urllib.request
from pathlib import Path

root = Path(__file__).parent
rows = []
for _ in range(40):
    try:
        with urllib.request.urlopen("http://127.0.0.1:18415/health", timeout=1) as r:
            if json.load(r)["version"] == "0.9.1":
                break
    except OSError:
        time.sleep(1)
else:
    raise AssertionError("API not ready")
for path in ["/slow", "/webgl"]:
    body = {
        "urls": ["http://dethrottled-recovery-fixture:19890" + path],
        "fresh": True,
        "max_chars": 4000,
    }
    req = urllib.request.Request(
        "http://127.0.0.1:18415/fetch",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        result = json.load(r)
    row = result[0]
    assert (
        row["quality"] == "ok"
        and "7341 tonnes" in row["content"]
        and row["tier"].split("/")[0] == "headed"
    )
    if path == "/slow":
        assert row["source_partial"] and not row["workflow"]["source_complete"]
        assert any(a["tool"] == "drive" for a in row["workflow"]["next_actions"])
    rows.append({"path": path, "input": body, "result": row})
    (root / "api-candidate.json").write_text(json.dumps(rows, indent=2))
    print("PASS", path, flush=True)
print("PASS isolated API automatic default recovery and partial-source workflow")
