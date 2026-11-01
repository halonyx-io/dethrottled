import json
import urllib.request
from pathlib import Path

rows = []
for label, port in [("baseline", 18409), ("candidate", 18410)]:
    body = {
        "url": "http://dethrottled-findings-fixture:19890/popup",
        "allowed_hosts": ["dethrottled-findings-fixture"],
        "public_only": True,
        "screenshot": "never",
        "steps": [
            {"action": "click", "selector": "#popup"},
            {"action": "wait", "ms": 500},
            {"action": "tabs"},
        ],
    }
    req = urllib.request.Request(
        "http://127.0.0.1:" + str(port) + "/drive",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as f:
        data = json.load(f)
    tabs = data["steps"][-1]["data"]["tabs"]
    blocked = any(
        tab["index"] > 0 and not tab["allowed"] and tab["url"].startswith("chrome-error://")
        for tab in tabs
    )
    rows.append({"build": label, "popup_blocked": blocked, "response": data})
    print(label, blocked, flush=True)
Path(__file__).with_name("popup-results.json").write_text(json.dumps(rows, indent=2))
assert all(x["popup_blocked"] for x in rows)
