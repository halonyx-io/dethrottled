import json
import os
import time
from pathlib import Path

from dethrottled import fetch

r = Path("/evidence")
label = os.environ["LABEL"]
protocol = json.loads((r / "live-protocol.json").read_text())
rows = []
for case in protocol:
    fetch._tier_rest.clear()
    fetch.reset_tier_stats()
    start = time.monotonic()
    try:
        out = fetch.fetch_and_extract(
            case["url"],
            max_chars=6000,
            cache=None,
            page_budget=60,
            admission_key="live-findings-" + label,
            public_only=True,
        )
        text = out.get("text", "")
        matched = all(marker.lower() in text.lower() for marker in case["markers"])
        row = {
            "case": case["name"],
            "url": case["url"],
            "elapsed_ms": round((time.monotonic() - start) * 1000),
            "ok": out["ok"],
            "quality": out.get("quality", "ok" if out["ok"] else "failed"),
            "expected_markers": matched,
            "tier": out.get("tier"),
            "reason": out.get("reason"),
            "browser_recovery": out.get("browser_recovery"),
            "text": text,
            "tier_stats": dict(fetch._tier_stats),
        }
    except Exception as e:
        row = {"case": case["name"], "url": case["url"], "error": type(e).__name__ + ":" + str(e)}
    rows.append(row)
    (r / (label + "-live.json")).write_text(json.dumps(rows, indent=2))
    print(label, {k: v for k, v in row.items() if k != "text"}, flush=True)
