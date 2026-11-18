"""Bounded static discovery before the warm browser fallback."""

from __future__ import annotations

import math
import os
import threading
import time
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlsplit

from . import adblock
from . import netfilter as requests
from .content import constrained

# Supplements beside the web chain (DDG Lite, then Bing and Yahoo directly):
# Yandex through SearXNG and Mwmbl's keyless API, both independent of Bing's
# index. SearXNG's Yahoo engine returned nothing on every live search (17 Nov
# 2026) while Yahoo's own page answered, so Yahoo is now a direct door.
# Yahoo runs beside DDG, not only after it: same (Bing) index, so most of
# DDG's rows are on Yahoo's page too, and Yahoo's snippets carry the dates
# DDG Lite's lack (0/80 DDG rows dated; 39/80 gain a date from Yahoo's copy,
# 18 Nov 2026). fast takes Yahoo only if it is already in when DDG answers.
SOURCE_PROFILES = {
    "fast": ("web", "yahoo"),
    "web": ("web", "yahoo", "yandex", "mwmbl"),
    "balanced": ("web", "yahoo", "yandex", "mwmbl"),
    "thorough": ("web", "yahoo", "bing", "yandex", "mwmbl"),
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
            # text(strip=True) strips each text node and joins them with no
            # separator, gluing the words DDG wraps in <b> to their neighbours.
            title = " ".join(link.text().split())
            snippet = (" ".join(snippets[index].text().split())
                       if index < len(snippets) else "")
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


# Other front doors to (mostly) Bing's index, read directly like DDG Lite.
# Each has its own pacing and its own rest, so one refusing does not end the
# search. Probed 17 Nov 2026 from a residential IP: Bing's HTML page and
# Yahoo's both answered with relevant results; Bing's RSS answered with decoys
# (unrelated stock-icon pages), so it is not used for web results.
_DOOR_LOCK = threading.Lock()
_DOOR_NEXT: dict = {}
_DOOR_REST: dict = {}
_DOOR_SESSIONS = threading.local()
DOOR_REST_SECONDS = 1800


def door_resting(name: str) -> float:
    """Seconds left on a door's rest, 0 when it may be asked."""
    with _DOOR_LOCK:
        return max(0.0, _DOOR_REST.get(name, 0) - time.monotonic())


def rest_door(name: str, seconds: float = DOOR_REST_SECONDS) -> None:
    with _DOOR_LOCK:
        _DOOR_REST[name] = time.monotonic() + seconds


def _door_get(name: str, url: str, timeout: float = 4.0):
    from curl_cffi import requests as tls_requests

    from .fetch import TLS_IMPERSONATE
    with _DOOR_LOCK:
        delay = _DOOR_NEXT.get(name, 0) - time.monotonic()
        _DOOR_NEXT[name] = max(time.monotonic(), _DOOR_NEXT.get(name, 0)) + 1.0
    if delay > 0:
        time.sleep(delay)
    # Cookies are kept: since 18 Nov 2026 Yahoo first answers 307 to a
    # bot-verification step (/_bv/v.gif) that sets a cookie, and without it the
    # search returns 500. One session per door per worker thread (sessions are
    # not shared across threads), so the step is paid once, not per search.
    # Every hop is still checked by netfilter.
    sessions = getattr(_DOOR_SESSIONS, "by_door", None)
    if sessions is None:
        sessions = _DOOR_SESSIONS.by_door = {}
    session = sessions.get(name)
    if session is None:
        session = sessions[name] = tls_requests.Session(impersonate=TLS_IMPERSONATE)
    return requests.get_using(session.get, url, timeout=timeout)


def _bing_target(href: str) -> str:
    """Bing wraps results as bing.com/ck/a?...&u=a1<base64url>."""
    parsed = urlsplit(href)
    if parsed.hostname not in {"www.bing.com", "bing.com"}:
        return href
    wrapped = parse_qs(parsed.query).get("u", [""])[0]
    if not wrapped.startswith("a1"):
        return ""
    import base64
    raw = wrapped[2:]
    try:
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""


def _yahoo_target(href: str) -> str:
    """Yahoo wraps results as r.search.yahoo.com/.../RU=<quoted>/RK=..."""
    if "/RU=" not in href:
        return href
    return unquote(href.split("/RU=", 1)[1].split("/R", 1)[0])


def _bing_rows(html: str) -> list:
    from selectolax.lexbor import LexborHTMLParser
    out = []
    for item in LexborHTMLParser(html).css("li.b_algo"):
        link = item.css_first("h2 a")
        if link is None:
            continue
        snippet = item.css_first(".b_caption p") or item.css_first("p")
        out.append((_bing_target(link.attributes.get("href") or ""), link.text(),
                    snippet.text() if snippet else "", ""))
    return out


def _yahoo_rows(html: str) -> list:
    from selectolax.lexbor import LexborHTMLParser
    out = []
    for item in LexborHTMLParser(html).css("div.algo-sr"):
        link, title = item.css_first(".compTitle a"), item.css_first("h3")
        if link is None or title is None:
            continue
        snippet = item.css_first(".compText")
        # Yahoo shows the page date in its own element ahead of the snippet
        # ("Oct 31, 2025 · "): the engine's date, not text to infer one from.
        dated = snippet.css_first(".fc-smoke") if snippet else None
        date = " ".join(dated.text().split()).rstrip(" ·") if dated else ""
        if " ago" in date:
            date = ""  # relative: left in the snippet for the usual resolver
        text = snippet.text() if snippet else ""
        if date and dated is not None:
            text = text.replace(dated.text(), " ", 1)
        out.append((_yahoo_target(link.attributes.get("href") or ""), title.text(), text,
                    date))
    return out


_DOORS = {
    "bing": ("https://www.bing.com/search?q={q}&setlang=en", _bing_rows,
             ("b_captcha", "/challenge/verify", "captcha")),
    "yahoo": ("https://search.yahoo.com/search?p={q}", _yahoo_rows,
              ("captcha", "unusual traffic", "/sorry/")),
}


_INFLIGHT: dict = {}


def door_search(name, query, *, max_items=8, cache=None, diagnostics=None):
    """One direct front door (bing, yahoo); concurrent identical asks share one request."""
    key = (name, query, max(1, min(max_items, 10)))
    with _DOOR_LOCK:
        shared = _INFLIGHT.get(key)
        mine = shared is None
        if mine:
            shared = _INFLIGHT[key] = {"done": threading.Event()}
    if not mine:
        shared["done"].wait(10)
        if diagnostics is not None:
            diagnostics.update(shared.get("report", {}), shared_request=True)
        return list(shared.get("rows", []))
    report = {}
    try:
        rows = _door_search(name, query, max_items=max_items, cache=cache, diagnostics=report)
        shared.update(rows=rows, report=report)
        return rows
    finally:
        if diagnostics is not None:
            diagnostics.update(report)
        shared["done"].set()
        with _DOOR_LOCK:
            _INFLIGHT.pop(key, None)


def _door_search(name, query, *, max_items=8, cache=None, diagnostics=None):
    """One direct front door (bing, yahoo). Refusals rest it for half an hour."""
    max_items = max(1, min(max_items, 10))
    diagnostics = diagnostics if diagnostics is not None else {}
    engine = "tls-" + name
    attempt = {"engine": engine, "status": "unavailable", "count": 0}
    started = time.monotonic()
    try:
        if os.environ.get("DETHROTTLED_DIRECT_DOORS", "1") == "0":
            attempt["status"] = "not_configured"
            return []
        if cache is not None:
            hit = cache.get("search", engine, query, max_items)
            if hit is not None:
                attempt.update(status="cached", count=len(hit))
                return hit[:max_items]
        resting = door_resting(name)
        if resting:
            attempt.update(status="resting", retry_in_seconds=int(resting))
            return []
        template, parse, refusals = _DOORS[name]
        response = _door_get(name, template.format(q=quote_plus(query)))
        html = response.text or ""
        attempt["http_status"] = response.status_code
        found = parse(html) if response.status_code == 200 else []
        if response.status_code != 200 or (not found and any(
                marker in html[:40000].lower() for marker in refusals)):
            attempt.update(status="challenge_or_http_error", refusal=True)
            rest_door(name)
            return []
        rows, seen, rejected = [], set(), []
        for target, title, snippet, date in found:
            parsed = urlsplit(target)
            title, snippet = " ".join(title.split()), " ".join(snippet.split())
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or target in seen or len(title) < 10):
                continue
            row = {"title": title[:300], "url": target, "snippet": snippet[:600],
                   "engine": "web-" + engine, "publishedDate": date, "cached": False}
            seen.add(target)
            if not constrained(query, row):
                # Off-topic for this query, but a real URL from a page that was
                # not refused: kept only as a destination-matching candidate.
                rejected.append(row)
                continue
            rows.append(row)
            if len(rows) >= max_items:
                break
        if rejected:
            attempt["candidates"] = rejected[:20]
        if not rows:
            attempt["status"] = "no_results" if not found else "no_matching_candidates"
            return []
        attempt.update(status="ok", count=len(rows))
        if cache is not None:
            cache.put("search", engine, query, max_items, value=rows)
        return rows
    except Exception as exc:
        attempt.update(status="transport_error", reason=adblock.error_reason(exc))
        return []
    finally:
        attempt["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        diagnostics.update(attempt)


def mwmbl_search(query, *, max_items=5, cache=None, diagnostics=None):
    """Mwmbl's keyless JSON API: a small independent index, strong on tech."""
    diagnostics = diagnostics if diagnostics is not None else {}
    attempt = {"engine": "mwmbl", "status": "unavailable", "count": 0}
    started = time.monotonic()
    try:
        if cache is not None:
            hit = cache.get("search", "mwmbl-api", query, max_items)
            if hit is not None:
                attempt.update(status="cached", count=len(hit))
                return hit[:max_items]
        if os.environ.get("DETHROTTLED_MWMBL", "1") == "0":
            attempt["status"] = "not_configured"
            return []
        resting = door_resting("mwmbl")
        if resting:
            attempt.update(status="resting", retry_in_seconds=int(resting))
            return []
        response = _door_get("mwmbl", "https://api.mwmbl.org/api/v1/search/?s="
                             + quote_plus(query), timeout=4.0)
        attempt["http_status"] = response.status_code
        if response.status_code != 200:
            attempt.update(status="challenge_or_http_error", refusal=True)
            rest_door("mwmbl")
            return []
        rows = []
        for item in response.json() if isinstance(response.json(), list) else []:
            def text(parts):
                return "".join(p.get("value", "") for p in parts or [] if isinstance(p, dict))
            row = {"title": " ".join(text(item.get("title")).split())[:300],
                   "url": item.get("url") or "", "snippet": " ".join(
                       text(item.get("extract")).split())[:600],
                   "engine": "mwmbl", "publishedDate": "", "cached": False}
            if (urlsplit(row["url"]).scheme in {"http", "https"} and len(row["title"]) >= 10
                    and constrained(query, row)):
                rows.append(row)
            if len(rows) >= max_items:
                break
        attempt.update(status="ok" if rows else "no_results", count=len(rows))
        if cache is not None and rows:
            cache.put("search", "mwmbl-api", query, max_items, value=rows)
        return rows
    except Exception as exc:
        attempt.update(status="transport_error", reason=adblock.error_reason(exc))
        return []
    finally:
        attempt["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        diagnostics.update(attempt)
