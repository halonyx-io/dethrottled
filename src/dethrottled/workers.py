"""Cached, bounded readiness and metrics probes; public input cannot choose URLs."""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

_POOL = ThreadPoolExecutor(max_workers=6, thread_name_prefix="worker-health")
_LOCK = threading.Lock()
_CACHED = {}


def status():
    urls = {
        "browser": (os.getenv("DETHROTTLED_BROWSER_SEARCH_URL"), "/health"),
        "renderer": (os.getenv("DETHROTTLED_CRAWL4AI_URL"), "/health"),
        "layout": (os.getenv("DETHROTTLED_LAYOUT_WORKER_URL"), "/ready"),
        "speech": (os.getenv("DETHROTTLED_MEDIA_WORKER_URL"), "/ready"),
        "formats": (os.getenv("DETHROTTLED_FORMAT_WORKER_URL"), "/ready"),
    }
    key = tuple(urls.items())
    with _LOCK:
        cached = _CACHED.get(key)
        if cached and time.monotonic() - cached[0] < 10:
            return cached[1]

    def check(item):
        name, (base, path) = item
        if not base:
            return name, {"status": "not_configured"}
        started = time.monotonic()
        try:
            response = requests.get(base.rstrip("/") + path, timeout=2, allow_redirects=False)
            result = {
                "status": "ready" if response.status_code == 200 else "unready",
                "http_status": response.status_code,
            }
            if name == "browser" and response.status_code == 200:
                graphics = response.json().get("graphics", {})
                result["graphics"] = {k: v for k, v in graphics.items() if k in {
                    "webgl", "hardware_verified", "renderer", "requested_mode", "fallback_reason"}}
            if path == "/ready" and response.status_code == 200:
                metrics = requests.get(
                    base.rstrip("/") + "/metrics", timeout=2, allow_redirects=False
                )
                if metrics.status_code == 200:
                    allowed = {
                        "active",
                        "active_seconds",
                        "completed",
                        "failed",
                        "timed_out",
                        "cancelled",
                        "rejected",
                        "deadline_seconds",
                        "max_input_bytes",
                    }
                    result["metrics"] = {k: v for k, v in metrics.json().items() if k in allowed}
        except (requests.RequestException, ValueError):
            result = {"status": "unreachable"}
        result["probe_ms"] = int((time.monotonic() - started) * 1000)
        return name, result

    result = dict(_POOL.map(check, urls.items()))
    with _LOCK:
        _CACHED[key] = (time.monotonic(), result)
    return result
