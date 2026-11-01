import json
import os
import time
from pathlib import Path

from dethrottled import fetch as f
from dethrottled.content import short_text

protocol = json.loads(Path("/evidence/live-protocol.json").read_text())
label = os.environ["LABEL"]
rows = []
for case in protocol:
    token = f._READ_OPTIONS.set({"public_only": True, "admission_key": "hostile-probe"})
    start = time.monotonic()
    try:
        p, r, _ = f._tier_headed(case["url"])
    finally:
        f._READ_OPTIONS.reset(token)
    text = short_text(p.get("html", ""))
    challenge = f.challenge_kind(p.get("html", ""))
    row = {
        "name": case["name"],
        "url": case["url"],
        "elapsed_ms": round((time.monotonic() - start) * 1000),
        "reason": r,
        "challenge": challenge,
        "chars": len(text),
        "markers_found": all(m.lower() in text.lower() for m in case["markers"]),
        "readable_candidate": bool(
            not r
            and not challenge
            and len(text) > 600
            and all(m.lower() in text.lower() for m in case["markers"])
        ),
        "recovery": p.get("browser_recovery"),
        "text_preview": text[:250],
    }
    rows.append(row)
    Path("/evidence/" + label + "-hostile.json").write_text(json.dumps(rows, indent=2))
    print(label, row["name"], row["readable_candidate"], r, flush=True)
