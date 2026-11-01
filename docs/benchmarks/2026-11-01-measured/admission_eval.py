import json
import os
from pathlib import Path

from dethrottled import fetch

fetch.CRAWL4AI_URL = "http://controlled-fixture"
fetch._crawl4ai_dialect = "crawl"
fetch._crawl4ai_via_crawl = lambda u: ({"text": "known renderer response"}, "", u)
fetch._spent.clear()
rows = []
for i in range(48):
    out, reason, url = fetch._tier_crawl4ai("https://fixture.example/" + str(i))
    rows.append({"request": i + 1, "success": bool(out), "reason": reason})
Path("/evidence/" + os.environ["LABEL"] + "-admission.json").write_text(json.dumps(rows, indent=2))
print(os.environ["LABEL"], sum(x["success"] for x in rows), "/", len(rows))
