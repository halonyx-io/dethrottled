import json
import time
import urllib.error
import urllib.request
from pathlib import Path

r = Path(__file__).parent
rows = []
for label, port in [("baseline", 18409), ("candidate", 18410)]:
    for _ in range(60):
        try:
            urllib.request.urlopen("http://127.0.0.1:" + str(port) + "/health", timeout=1).close()
            break
        except OSError:
            time.sleep(0.1)
    for case, path in [
        ("challenge-frame", "/framed"),
        ("private-frame", "/private-frame"),
        ("foreign-top", "/frame"),
    ]:
        host = (
            "dethrottled-findings-frame"
            if case == "foreign-top"
            else "dethrottled-findings-fixture"
        )
        body = {
            "url": "http://" + host + ":19890" + path,
            "allowed_hosts": ["dethrottled-findings-fixture"],
            "public_only": True,
            "screenshot": "never",
            "steps": [
                {"action": "wait", "ms": 3500},
                {"action": "html", "selector": "body", "max_chars": 10000},
            ],
        }
        req = urllib.request.Request(
            "http://127.0.0.1:" + str(port) + "/drive",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as f:
                status = f.status
                data = json.load(f)
        except urllib.error.HTTPError as e:
            status = e.code
            data = json.load(e)
        html = (data.get("steps") or [{}])[-1].get("data", "")
        private_blocked = any(
            "127.0.0.1:19888" in event.get("url", "")
            for event in data.get("events", {}).get("request_failures", [])
        )
        row = {
            "build": label,
            "case": case,
            "http": status,
            "expected_fact": "7341 tonnes" in str(html),
            "private_blocked": private_blocked,
            "ok": data.get("ok"),
            "response": data,
        }
        rows.append(row)
        print({k: v for k, v in row.items() if k != "response"}, flush=True)
(r / "frame-results.json").write_text(json.dumps(rows, indent=2))
new = [x for x in rows if x["build"] == "candidate"]
assert new[0]["expected_fact"] and new[1]["private_blocked"] and not new[2]["ok"]
