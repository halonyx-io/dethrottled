import json
import os
import time
from pathlib import Path

from dethrottled import fetch as f

rows = []
label = os.environ["LABEL"]
for path in ["/slow", "/webgl"]:
    start = time.monotonic()
    out = f.fetch_and_extract(
        "http://dethrottled-recovery-fixture:19890" + path, headed_fallback=False, max_chars=4000
    )
    rows.append(
        {
            "path": path,
            "elapsed_ms": round((time.monotonic() - start) * 1000),
            "fact": "7341 tonnes" in out.get("text", ""),
            "result": out,
        }
    )
    Path("/evidence/" + label + "-default-workflow.json").write_text(json.dumps(rows, indent=2))
    print(label, path, rows[-1]["fact"], out.get("reason"), flush=True)
