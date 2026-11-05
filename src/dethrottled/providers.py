"""Explicit, optional metered discovery. Keys never cross the agent interface."""

import os
import time

from . import netfilter as requests

NAMES = ("exa", "tavily", "parallel")


def configured():
    return {name: bool(os.getenv("DETHROTTLED_" + name.upper() + "_API_KEY"))
            for name in NAMES}


def search(name, query, limit, diagnostics):
    started = time.monotonic()
    diagnostics.update(provider=name, metered=True, cost="unknown", status="not_configured")
    key = os.getenv("DETHROTTLED_" + name.upper() + "_API_KEY", "")
    if not key:
        return []
    limit = min(max(limit, 1), 10)
    headers = {"Content-Type": "application/json"}
    if name == "exa":
        url = "https://api.exa.ai/search"
        headers["x-api-key"] = key
        payload = {"query": query, "type": "auto", "numResults": limit,
                   "contents": {"highlights": True}}
    elif name == "tavily":
        url = "https://api.tavily.com/search"
        headers["Authorization"] = "Bearer " + key
        payload = {"query": query, "max_results": limit, "search_depth": "advanced",
                   "include_answer": False, "include_usage": True}
    else:
        url = "https://api.parallel.ai/v1/search"
        headers["x-api-key"] = key
        payload = {"objective": query, "search_queries": [query], "max_chars_total": 12000}
    try:
        # Do not follow redirects with credentials or leak upstream error bodies.
        response = requests.post(url, json=payload, headers=headers, timeout=(5, 45),
                                 allow_redirects=False)
        diagnostics["http_status"] = response.status_code
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
        diagnostics.update(status="ok" if rows else "empty", returned=len(rows))
        return rows
    except (requests.RequestException, ValueError, TypeError, KeyError):
        diagnostics["status"] = "failed"
        return []
    finally:
        diagnostics["elapsed_ms"] = int((time.monotonic() - started) * 1000)
