import json
import os
import time
from pathlib import Path

from dethrottled import formats

r = Path("/evidence")
rows = []
for p in sorted((r / "fixtures").iterdir()):
    if p.suffix not in [".msg", ".xlsb", ".pdf"]:
        continue
    data = p.read_bytes()
    kind = formats.kind_of(data, p.name)
    start = time.monotonic()
    try:
        text, meta = formats.read_blob(data, kind, 100000, options={"document_mode": "auto"})
        out = {"text": text, "metadata": meta}
    except Exception as e:
        out = {"error": type(e).__name__ + ":" + str(e)}
    rows.append(
        {
            "file": p.name,
            "kind": kind,
            "elapsed_ms": round((time.monotonic() - start) * 1000),
            **out,
        }
    )
(r / (os.environ["LABEL"] + "-reads.json")).write_text(json.dumps(rows, indent=2))
print(
    [
        (
            x["file"],
            x["kind"],
            len(x.get("text", "")),
            x.get("error"),
            x.get("metadata", {}).get("parser"),
        )
        for x in rows
    ]
)
