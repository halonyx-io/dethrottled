"""Explicit, optional metered discovery. Keys never cross the agent interface."""

import os
import threading
import time

from . import netfilter as requests

NAMES = ("exa", "tavily", "parallel")
_LOCK = threading.Lock()
_COOLDOWN = {}
_PROXY_INDEX = 0


def _key_list(name: str) -> list:
    plural = os.getenv("DETHROTTLED_" + name.upper() + "_API_KEYS", "").strip()
    single = os.getenv("DETHROTTLED_" + name.upper() + "_API_KEY", "").strip()
    raw = plural or single
    return [item.strip() for item in raw.split(",") if item.strip()]


def _keys(name: str) -> list:
    """All configured keys for a provider, deduplicated in order."""
    return list(dict.fromkeys(_key_list(name)))


def configured():
    return {name: bool(_keys(name)) for name in NAMES}


def _cooling(name: str, key: str) -> bool:
    with _LOCK:
        return _COOLDOWN.get((name, key), 0) > time.time()


def _cool(name: str, key: str, seconds: float) -> None:
    with _LOCK:
        _COOLDOWN[(name, key)] = time.time() + seconds


def _proxy_pool() -> list:
    raw = (os.getenv("DETHROTTLED_SEARCH_PROXIES", "").strip()
           or os.getenv("DETHROTTLED_SEARCH_PROXY", "").strip())
    return [item.strip() for item in raw.split(",") if item.strip()]


def _next_proxy() -> str:
    global _PROXY_INDEX
    pool = _proxy_pool()
    if not pool:
        return ""
    with _LOCK:
        proxy = pool[_PROXY_INDEX % len(pool)]
        _PROXY_INDEX += 1
    return proxy


def search(name, query, limit, diagnostics):
    started = time.monotonic()
    diagnostics.update(provider=name, metered=True, cost="unknown", status="not_configured")
    keys = _keys(name)
    if not keys:
        return []
    limit = min(max(limit, 1), 10)
    headers = {"Content-Type": "application/json"}
    if name == "exa":
        url = "https://api.exa.ai/search"
        payload = {"query": query, "type": "auto", "numResults": limit,
                   "contents": {"highlights": True}}
    elif name == "tavily":
        url = "https://api.tavily.com/search"
        payload = {"query": query, "max_results": limit, "search_depth": "advanced",
                   "include_answer": False, "include_usage": True}
    else:
        url = "https://api.parallel.ai/v1/search"
        payload = {"objective": query, "search_queries": [query], "max_chars_total": 12000}
    proxy = _next_proxy()
    diagnostics["proxy_rotated"] = bool(proxy)
    attempts = []
    try:
        for index, key in enumerate(keys):
            if _cooling(name, key):
                attempts.append({"key": index, "status": "cooling"})
                continue
            request_headers = dict(headers)
            if name == "tavily":
                request_headers["Authorization"] = "Bearer " + key
            else:
                request_headers["x-api-key"] = key
            kwargs = {"json": payload, "headers": request_headers, "timeout": (5, 45),
                      "allow_redirects": False}
            if proxy:
                kwargs["proxies"] = {"http": proxy, "https": proxy}
            try:
                response = requests.post(url, **kwargs)
            except requests.RequestException:
                attempts.append({"key": index, "status": "transport"})
                if proxy:
                    _cool("proxy:" + proxy, proxy, 60)
                diagnostics.update(status="failed", key_attempts=attempts,
                                   elapsed_ms=int((time.monotonic() - started) * 1000))
                return []
            status = response.status_code
            if status in {401, 403, 429}:
                _cool(name, key, 300 if status in {401, 403} else 60)
                attempts.append({"key": index, "status": status})
                continue
            diagnostics["http_status"] = status
            response.raise_for_status()
            if response.is_redirect:
                raise ValueError("provider_redirect")
            data = response.json()
            rows = []
            for item in data.get("results", [])[:limit]:
                if not isinstance(item, dict) or not str(item.get("url", "")).startswith(
                        ("https://", "http://")):
                    continue
                snippet = item.get("highlights") or item.get("excerpts") or item.get("content", "")
                if isinstance(snippet, list):
                    snippet = "\n".join(str(x) for x in snippet)
                rows.append({"url": item["url"], "title": str(item.get("title") or "")[:1000],
                             "snippet": str(snippet)[:6000], "engine": name,
                             "publishedDate": item.get("publishedDate") or item.get("publish_date"),
                             "discovery": [{"provider": name, "query": query}]})
            diagnostics.update(status="ok" if rows else "empty", returned=len(rows),
                               key_index=index, key_attempts=attempts)
            return rows
        diagnostics.update(status="keys_exhausted", key_attempts=attempts)
        return []
    except (requests.RequestException, ValueError, TypeError, KeyError):
        diagnostics["status"] = "failed"
        return []
    finally:
        diagnostics["elapsed_ms"] = int((time.monotonic() - started) * 1000)
