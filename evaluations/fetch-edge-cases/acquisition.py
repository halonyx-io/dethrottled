"""Single paced reachability observation; no rendering or browser worker requests."""
import json
import time

from dethrottled import fetch

started = time.monotonic()
result = fetch.fetch_and_extract(
    "https://www.gnu.org/philosophy/free-sw.html",
    allow_render=False, cache=None, max_chars=8000)
print(json.dumps({
    "scope": "direct and TLS only; workers deliberately excluded",
    "elapsed_s": round(time.monotonic() - started, 3),
    "ok": result["ok"], "reason": result.get("reason"),
    "attempts": result.get("acquisition_attempts"),
    "content_chars": len(result.get("text", "")),
}))
