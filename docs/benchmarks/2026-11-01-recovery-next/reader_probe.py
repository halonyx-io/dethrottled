import concurrent.futures
import json
import os
import time

from dethrottled import fetch as f

label = os.environ["LABEL"]
rows = []
host = "http://dethrottled-recovery-fixture:19890"
for path in ["/plain", "/slow", "/loading", "/webgl"]:
    start = time.monotonic()
    payload, reason, url = f._tier_headed(host + path)
    rows.append(
        {
            "path": path,
            "elapsed_ms": round((time.monotonic() - start) * 1000),
            "expected_fact": "7341 tonnes" in payload.get("html", ""),
            "reason": reason,
            "recovery": payload.get("browser_recovery"),
        }
    )
    print(label, rows[-1], flush=True)


def read(i):
    token = f._READ_OPTIONS.set({"admission_key": "concurrent-" + str(i)})
    try:
        p, r, _ = f._tier_headed(host + "/plain")
        return {
            "id": i,
            "fact": "7341 tonnes" in p.get("html", ""),
            "reason": r,
            "recovery": p.get("browser_recovery"),
        }
    finally:
        f._READ_OPTIONS.reset(token)


with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    concurrent = list(pool.map(read, range(6)))
out = {"build": label, "reads": rows, "concurrent": concurrent}
if hasattr(f, "_HEADED_QUEUE"):
    out["admission"] = f._HEADED_QUEUE.stats()
open("/evidence/" + label + "-reader.json", "w").write(json.dumps(out, indent=2))
print("Completed", label, flush=True)
