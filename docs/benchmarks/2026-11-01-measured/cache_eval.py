import json
import os
from pathlib import Path

from dethrottled import fetch

os.environ["DETHROTTLED_FORMAT_WORKER_URL"] = "http://formats"
os.environ["DETHROTTLED_LAYOUT_WORKER_URL"] = "http://layout"
fetch.valid_url = lambda u: True
fetch._tier_direct = lambda *a: ({"text": "upgraded extraction", "structured": True}, "", a[0])
rows = []
for suffix, scanned in [("xlsb", False), ("pdf", True), ("html", False)]:

    class Cache:
        def get(self, *a, scanned=scanned):
            return {
                "ok": True,
                "text": "old extraction",
                "chars": 14,
                "acquisition": {"layout_worker_configured": True},
                "extraction": {"pages": [{"method": "ocr"}] if scanned else []},
            }

        def put(self, *a, **kw):
            pass

    result = fetch.fetch_and_extract("https://fixture.example/a." + suffix, cache=Cache())
    rows.append(
        {"format": suffix, "scan": scanned, "text": result["text"], "cached": result["cached"]}
    )
Path("/evidence/" + os.environ["LABEL"] + "-cache.json").write_text(json.dumps(rows, indent=2))
print(rows)
