"""Cached, bounded readiness and metrics probes; public input cannot choose URLs."""

import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

_POOL = ThreadPoolExecutor(max_workers=6, thread_name_prefix="worker-health")
_LOCK = threading.Lock()
_CACHED = {}
_ENDPOINTS = {}
_DISCOVERY_LOCK = threading.Lock()
_WORKERS = {
    "layout": ("DETHROTTLED_LAYOUT_WORKER_URL", "docling-worker", 19891),
    "speech": ("DETHROTTLED_MEDIA_WORKER_URL", "media-worker", 19889),
    "formats": ("DETHROTTLED_FORMAT_WORKER_URL", "format-worker", 19892),
}


def endpoint(name):
    """Discover only fixed Compose service names, never a caller-supplied target.

    Explicit URLs win; `off` disables a worker even if its service is running.
    Source installs perform no discovery unless the operator enables it.
    Cache DNS misses briefly so newly started profiles become usable automatically.
    """
    variable, host, port = _WORKERS[name]
    explicit = os.getenv(variable, "").strip()
    if explicit:
        return "" if explicit.lower() == "off" else explicit.rstrip("/")
    if os.getenv("DETHROTTLED_AUTO_WORKERS", "0") != "1":
        return ""
    with _DISCOVERY_LOCK:
        now = time.monotonic()
        cached = _ENDPOINTS.get(name)
        if cached and now - cached[0] < 10:
            return cached[1]
        try:
            socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            value = f"http://{host}:{port}"
        except OSError:
            value = ""
        _ENDPOINTS[name] = (now, value)
        return value



def status():
    urls = {
        "browser": (os.getenv("DETHROTTLED_BROWSER_SEARCH_URL"), "/health"),
        "renderer": (os.getenv("DETHROTTLED_CRAWL4AI_URL"), "/health"),
        "layout": (endpoint("layout"), "/ready"),
        "speech": (endpoint("speech"), "/ready"),
        "formats": (endpoint("formats"), "/ready"),
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
            if response.status_code == 503:
                try:
                    detail = response.json().get('detail', '')
                except ValueError:
                    detail = ''
                if isinstance(detail, str) and detail.startswith((
                        'speech_model_not_cached;', 'layout_models_not_cached;')):
                    result.update(reason='model_not_cached', initialization='first_use_download')
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
