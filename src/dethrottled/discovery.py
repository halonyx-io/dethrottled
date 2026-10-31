"""Bounded static discovery before the warm browser fallback."""

from __future__ import annotations

import threading
import time
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlsplit

import requests

from .content import constrained

SOURCE_PROFILES = {
    "fast": ("web",),
    "web": ("web",),
    "balanced": ("web", "news"),
    "thorough": ("web", "mwmbl"),
    "news": ("web", "news"),
    "academic": ("web", "crossref", "openalex", "arxiv"),
}
_PACE_LOCK = threading.Lock()
_NEXT = 0.0


def tls_search(query, *, max_items=8, cache=None, diagnostics=None, worker=""):
    """Accept useful SERPs only. A 202 challenge never means 'no matches'."""
    diagnostics = diagnostics if diagnostics is not None else {}
    if cache is not None:
        hit = cache.get("search", "tls-ddg-lite", query, max_items)
        if hit is not None:
            diagnostics.update(status="cached", count=len(hit))
            return hit
    started = time.monotonic()
    attempt = {"engine": "tls-ddg-lite", "status": "unavailable", "count": 0}
    try:
        from curl_cffi import requests as tls_requests
        from selectolax.lexbor import LexborHTMLParser

        from .fetch import TLS_IMPERSONATE
        # The private worker owns DDG pacing for both static and browser attempts.
        paced = False
        if worker:
            try:
                response = requests.post(worker + "/pace", timeout=1.5)
                paced = response.status_code == 200
            except requests.RequestException:
                pass
        if not paced:
            global _NEXT
            with _PACE_LOCK:
                delay = _NEXT - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                _NEXT = time.monotonic() + 0.5
        url = "https://lite.duckduckgo.com/lite/?q=" + quote_plus(query)
        response = tls_requests.get(url, impersonate=TLS_IMPERSONATE, timeout=1.5)
        html = response.text or ""
        attempt["http_status"] = response.status_code
        if response.status_code != 200 or any(x in html[:20000].lower() for x in (
                "anomaly.js", "bots use duckduckgo", "challenge-platform")):
            attempt["status"] = "challenge_or_http_error"
            return []
        tree = LexborHTMLParser(html)
        links, snippets = tree.css("a.result-link"), tree.css(".result-snippet")
        rows, seen = [], set()
        for index, link in enumerate(links[:max_items]):
            target = urljoin(url, link.attributes.get("href", ""))
            parsed = urlsplit(target)
            if parsed.hostname in {"duckduckgo.com", "www.duckduckgo.com"}:
                target = unquote(parse_qs(parsed.query).get("uddg", [""])[0])
                parsed = urlsplit(target)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                continue
            title = link.text(strip=True)
            snippet = snippets[index].text(strip=True) if index < len(snippets) else ""
            row = {"title": title[:300], "url": target, "snippet": snippet[:600],
                   "engine": "web-tls-ddg-lite", "publishedDate": "", "cached": False}
            if target in seen or not constrained(query, row) or len(title) < 10:
                continue
            seen.add(target)
            rows.append(row)
        if len(rows) < 3 or sum(len(r["snippet"]) >= 25 for r in rows) < 2:
            attempt["status"] = "thin_or_empty"
            return []
        attempt.update(status="ok", count=len(rows))
        if cache is not None:
            cache.put("search", "tls-ddg-lite", query, max_items, value=rows)
        return rows
    except (ImportError, ValueError, TypeError, OSError, requests.RequestException) as exc:
        attempt.update(status="unavailable", reason=type(exc).__name__)
        return []
    except Exception as exc:
        # curl_cffi transport errors are not requests.RequestException.
        attempt.update(status="transport_error", reason=type(exc).__name__)
        return []
    finally:
        attempt["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        diagnostics.update(attempt)
