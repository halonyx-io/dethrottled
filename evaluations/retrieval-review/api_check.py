import hashlib
import json
import pathlib
import re
import time

from fastapi.testclient import TestClient

from dethrottled import server

blob = pathlib.Path("/tmp/rfc9110.pdf").read_bytes()
url = "https://www.rfc-editor.org/rfc/rfc9110.pdf"
server.fetcher._tier_direct = lambda target, timeout, allow_ocr: server.fetcher._binary_payload(
    blob, target, "application/pdf", False
)
server.index_fetched = lambda *args, **kwargs: 0
browser_calls = []


def browser(*args, **kwargs):
    browser_calls.append(True)
    raise AssertionError("PDF parser continuation must not use browser recovery")


server.fs.BROWSER_SEARCH_URL = "https://unused.fixture"
server.fs.browser_drive = browser
started = time.perf_counter()
r = TestClient(server.app).post(
    "/fetch", json={"urls": [url], "max_chars": 1000000, "cache_mode": "bypass"}
)
r.raise_for_status()
row = r.json()[0]


def normalize(t):
    return re.sub(r"\s+", " ", t).lower()


facts = [
    "a user agent may send a date header field in a request",
    "transparent content negotiation in http",
    "ought to respond with a 415",
]
result = {
    "http_status": r.status_code,
    "quality": row["quality"],
    "content_status": row["content_status"],
    "content_chars": row["content_chars"],
    "document_chars": row["document_chars"],
    "partial": row["source_partial"],
    "truncated": row["truncated"],
    "pages": len(row["extraction"]["pages"]),
    "facts": [{"text": f, "found": f in normalize(row["content"])} for f in facts],
    "workflow_state": row["workflow"]["state"],
    "read_plan_stop": row["read_plan"]["stop_reason"],
    "browser_calls": len(browser_calls),
    "seconds": time.perf_counter() - started,
    "fixture_sha256": hashlib.sha256(blob).hexdigest(),
}
assert all(f["found"] for f in result["facts"])
assert not browser_calls and not result["partial"] and not result["truncated"]
print(json.dumps(result, indent=2))
