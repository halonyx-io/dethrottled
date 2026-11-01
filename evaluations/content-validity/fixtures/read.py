"""Same fixed payloads through an installed baseline or source candidate reader."""

import json
import os
import sys

from dethrottled import __version__, fetch

fetch.ENABLE_TLS = False
fetch.ENABLE_JINA = False
fetch.CRAWL4AI_URL = ""
os.environ.pop("DETHROTTLED_BROWSER_SEARCH_URL", None)
results = []
for case in json.load(open(sys.argv[1])):
    fetch._tier_direct = lambda *args, payload=case["payload"]: (payload, "", args[0])
    result = fetch.fetch_and_extract("https://fixture.example/" + case["id"],
                                     allow_render=False, max_chars=120000)
    results.append(dict(case=case["id"], version=__version__, result=result))
json.dump(results, sys.stdout, indent=2)
