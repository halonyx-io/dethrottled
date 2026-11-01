import json
import os
import time
from pathlib import Path

from dethrottled import fetch

r = Path("/evidence")
label = os.environ["LABEL"]
rows = []
url = "http://dethrottled-findings-fixture:19890/report"
for case, namespace, explicit in [
    ("default-alice", "alice", False),
    ("repeat-alice", "alice", False),
    ("separate-bob", "bob", False),
    ("explicit-charlie", "charlie", True),
    ("plain-control", "plain", False),
]:
    target = url.replace("/report", "/plain") if case == "plain-control" else url
    fetch._tier_rest.clear()
    fetch.reset_tier_stats()
    start = time.monotonic()
    out = fetch.fetch_and_extract(
        target,
        max_chars=4000,
        cache=None,
        headed_fallback=explicit,
        admission_key="controlled-" + namespace,
    )
    rows.append(
        {
            "case": case,
            "elapsed_ms": round((time.monotonic() - start) * 1000),
            "ok": out["ok"],
            "quality": out.get("quality", "ok" if out["ok"] else "failed"),
            "expected_fact": "7341 tonnes" in out.get("text", ""),
            "tier": out.get("tier"),
            "reason": out.get("reason"),
            "browser_recovery": out.get("browser_recovery"),
            "tier_stats": dict(fetch._tier_stats),
        }
    )
    print(label, rows[-1], flush=True)
(r / (label + "-controlled.json")).write_text(json.dumps(rows, indent=2))
