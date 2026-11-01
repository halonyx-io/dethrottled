import json
import socket
import time
import urllib.request
from pathlib import Path

r = Path(__file__).parent
url = "http://127.0.0.1:18403/metrics"


def metrics():
    with urllib.request.urlopen(url, timeout=3) as f:
        return json.load(f)


before = metrics()
data = (r / "fixtures/scanned-table.pdf").read_bytes()
s = socket.create_connection(("127.0.0.1", 18403))
s.sendall(
    (
        "POST /convert?page_start=1&page_end=1 HTTP/1.1\r\nHost: localhost\r\nContent-Length: "
        + str(len(data))
        + "\r\nContent-Type: application/pdf\r\n\r\n"
    ).encode()
    + data
)
start = time.monotonic()
active = None
while time.monotonic() - start < 3:
    active = metrics()
    if active["active"]:
        break
    time.sleep(0.02)
s.close()
while time.monotonic() - start < 5:
    after = metrics()
    if not after["active"] and after["cancelled"] > before["cancelled"]:
        break
    time.sleep(0.02)
passed = bool(
    active["active"]
    and not after["active"]
    and after["cancelled"] == before["cancelled"] + 1
    and after["child_pid"] is None
)
(r / "http-disconnect.json").write_text(
    json.dumps(
        {
            "before": before,
            "active": active,
            "after": after,
            "elapsed_ms": round((time.monotonic() - start) * 1000),
            "pass": passed,
        },
        indent=2,
    )
)
assert passed
print("PASS real HTTP disconnect: child cancelled, active slot cleared")
