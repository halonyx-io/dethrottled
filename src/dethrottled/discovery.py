"""Bounded static discovery before the warm browser fallback."""

from __future__ import annotations

import math
import threading
import time
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlsplit

from . import adblock
from . import netfilter as requests
from .content import constrained

SOURCE_PROFILES = {
    "fast": ("web",),
    "web": ("web", "yandex", "yahoo"),
    "balanced": ("web", "yandex", "yahoo"),
    "thorough": ("web", "yandex", "yahoo", "mwmbl"),
    "news": ("web", "news"),
    "academic": ("web", "crossref", "openalex", "arxiv"),
}
_PACE_LOCK = threading.Lock()
_NEXT = 0.0


def tls_search(query, *, max_items=8, cache=None, diagnostics=None, worker=""):
    """Accept useful SERPs only. A 202 challenge never means 'no matches'."""
    max_items = max(1, min(max_items, 10))
    diagnostics = diagnostics if diagnostics is not None else {}
    if cache is not None:
        hit = cache.get("search", "tls-ddg-lite", query, max_items)
        if hit is not None:
            diagnostics.update(status="cached", count=len(hit))
            return hit[:max_items]
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
        response = requests.get_using(
            tls_requests.get, url, impersonate=TLS_IMPERSONATE, timeout=1.5)
        html = response.text or ""
        attempt["http_status"] = response.status_code
        retry = (getattr(response, "headers", None) or {}).get("Retry-After", "")
        if retry:
            try:
                seconds = float(retry)
            except ValueError:
                try:
                    seconds = parsedate_to_datetime(retry).timestamp() - time.time()
                except (ValueError, TypeError, OverflowError):
                    seconds = 0
            attempt["retry_after_seconds"] = (max(0, min(86400, seconds))
                                              if math.isfinite(seconds) else 0)
        challenged = any(x in html[:20000].lower() for x in (
            "anomaly.js", "bots use duckduckgo", "challenge-platform"))
        attempt["refusal"] = challenged or response.status_code in {202, 429}
        if response.status_code != 200 or challenged:
            attempt["status"] = "challenge_or_http_error"
            return []
        tree = LexborHTMLParser(html)
        links, snippets = tree.css("a.result-link"), tree.css(".result-snippet")
        rows, seen, unfiltered_usable = [], set(), 0
        for index, link in enumerate(links):
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
            if target in seen or len(title) < 10:
                continue
            unfiltered_usable += len(snippet.strip()) >= 25
            if not constrained(query, row):
                continue
            seen.add(target)
            rows.append(row)
            if len(rows) >= max_items:
                break
        if not rows and unfiltered_usable:
            attempt.update(status="no_matching_candidates", filtered=True)
            return []
        if not any(len(r["snippet"].strip()) >= 25 for r in rows):
            attempt["status"] = "thin_or_empty"
            return []
        attempt.update(status="ok", count=len(rows))
        if cache is not None:
            cache.put("search", "tls-ddg-lite", query, max_items, value=rows)
        return rows
    except (ImportError, ValueError, TypeError, OSError, requests.RequestException) as exc:
        attempt.update(status="unavailable", reason=adblock.error_reason(exc))
        return []
    except Exception as exc:
        # curl_cffi transport errors are not requests.RequestException.
        attempt.update(status="transport_error", reason=adblock.error_reason(exc))
        return []
    finally:
        attempt["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        diagnostics.update(attempt)
