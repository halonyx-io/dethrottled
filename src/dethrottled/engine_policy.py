"""Per-profile engine order, with evidence-based demotion.

A search profile chooses engines; this decides the ORDER their results enter
the menu, which is what survives a small `limit`. Each profile has a default
order from measurement. Engines then earn or lose their place on evidence: for
every search, each engine's offered results are scored by what the profile
values, and an engine whose yield stays far below the best one is moved to the
back. It is never removed, so it keeps being asked and can earn its place back
when the evidence changes.

Only the news profile uses this today. Measured 14 Nov 2026 on 20
current-events queries: the news menu held 7 dated results out of 158, because
DuckDuckGo News (all dated) entered after DuckDuckGo web and was cut by the
limit. See evaluations/news-profile.

Engine names and counts only: nothing about queries or callers is recorded.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone

from . import paths as _paths

ENABLED = os.environ.get("DETHROTTLED_ENGINE_POLICY", "1").strip().lower() not in {
    "0", "false", "no", "off"}
MIN_OBSERVATIONS = 10       # searches before an engine can be demoted
DEMOTE_RATIO = 0.25         # yield below this share of the best engine's
DECAY = 0.9                 # weight of history per new observation
SAVE_EVERY = 60.0

# Default order per profile; engines not listed keep their arrival order after.
DEFAULT_ORDER = {
    "news": ["duckduckgo-news", "google-news", "qwant-news", "reuters", "bing-news",
             "gnews-resolved"],
}

_lock = threading.Lock()
_state: dict | None = None
_dirty = False
_last_save = 0.0


def family(row: dict) -> str:
    return str(row.get("engine") or "unknown").lower().removeprefix(
        "web-browser-").removeprefix("web-").replace(" ", "-")


def _path():
    return _paths.data_dir() / "engine-policy.json"


def _load() -> dict:
    global _state
    if _state is None:
        try:
            _state = json.loads(_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _state = {}
    return _state


def _dated(row: dict) -> bool:
    """A provider- or page-declared date, never a snippet hint."""
    value = row.get("published") or row.get("publishedDate") or ""
    return bool(str(value).strip())


VALUE = {"news": _dated}


def observe(profile: str, rows: list) -> None:
    """Score each engine's offered rows for this profile. Never raises."""
    global _dirty
    value = VALUE.get(profile)
    if not ENABLED or value is None or not rows:
        return
    try:
        offered, useful = {}, {}
        for row in rows:
            name = family(row)
            offered[name] = offered.get(name, 0) + 1
            useful[name] = useful.get(name, 0) + bool(value(row))
        with _lock:
            engines = _load().setdefault(profile, {})
            for name, count in offered.items():
                entry = engines.setdefault(name, {"yield": 0.0, "n": 0})
                current = useful[name] / count
                entry["yield"] = (current if entry["n"] == 0
                                  else DECAY * entry["yield"] + (1 - DECAY) * current)
                entry["n"] += 1
                entry["at"] = time.time()
            _dirty = True
        _maybe_save()
    except Exception:
        return


def demoted(profile: str) -> list:
    if not ENABLED:
        return []
    with _lock:
        engines = dict(_load().get(profile, {}))
    proven = {name: e for name, e in engines.items() if e.get("n", 0) >= MIN_OBSERVATIONS}
    best = max((e["yield"] for e in proven.values()), default=0.0)
    if best <= 0:
        return []
    return sorted(name for name, e in proven.items() if e["yield"] < DEMOTE_RATIO * best)


def order(profile: str, rows: list) -> tuple[list, dict]:
    """Interleave rows by engine in policy order; demoted engines go last.

    Round-robin keeps several sources in a small menu; per-engine caps still
    apply afterwards in bounded_results.
    """
    preferred = DEFAULT_ORDER.get(profile, [])
    back = set(demoted(profile))
    groups: dict[str, list] = {}
    for row in rows:
        groups.setdefault(family(row), []).append(row)
    names = sorted(groups, key=lambda name: (
        name in back,
        preferred.index(name) if name in preferred else len(preferred)))
    lead = [name for name in names if name not in back]
    out = []
    for index in range(max((len(groups[n]) for n in lead), default=0)):
        out.extend(groups[name][index] for name in lead if index < len(groups[name]))
    for name in names:
        if name in back:
            out.extend(groups[name])
    return out, {"profile": profile, "order": names, "demoted": sorted(back)}


FRESH_DAYS = float(os.environ.get("DETHROTTLED_NEWS_FRESH_DAYS", "7"))
SOCIAL = ("facebook.com", "x.com", "twitter.com", "instagram.com", "tiktok.com",
          "threads.net", "threads.com", "linkedin.com", "pinterest.com", "reddit.com")


def landing_path(url: str) -> bool:
    """A front, section or topic page: no article slug in the path."""
    from urllib.parse import urlsplit
    parsed = urlsplit(url or "")
    segments = [part for part in parsed.path.split("/") if part]
    return (len(segments) == 0 or (len(segments) == 1 and len(segments[0]) <= 24)
            or "/topics/" in parsed.path)


def is_landing(row: dict) -> bool:
    """A front, section or topic page, dated or not.

    Dated ones count too: Google News lists reuters.com/ itself, dated
    2005-09-10, and it ranked #3 for "news headlines today" (14 Nov 2026).
    """
    return landing_path(row.get("url", ""))


# Headline roundups list other stories: "School assembly news headlines today",
# "Top 10 news stories". They ranked #1 and #2 for vague headline queries on
# 14 Nov 2026 (found in review). Title-only, narrow, and they are moved back,
# never removed.
ROUNDUP = re.compile(
    r"\bschool assembly\b|\bnews headlines (?:today|for)\b|\bheadlines (?:today|of the day)\b"
    r"|\btoday'?s (?:top )?headlines\b|\btop \d+ (?:news|headlines|stories)\b"
    r"|\bnews (?:roundup|round-up|digest|wrap)\b", re.I)


def _roundup(row: dict) -> bool:
    return bool(ROUNDUP.search(str(row.get("title") or "")))


def _social(row: dict) -> bool:
    from urllib.parse import urlsplit
    host = (urlsplit(row.get("url", "")).hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in SOCIAL)


PER_SITE = int(os.environ.get("DETHROTTLED_NEWS_PER_SITE", "2"))


def news_order(rows: list, now: float | None = None) -> list:
    """Fresh, undated, stale, then front pages and social posts; at most
    PER_SITE rows per site lead, the rest follow in the same order.

    Measured 14 Nov 2026: ordering by freshness alone let reuters.com take 47
    of 176 places (27 before), with 41 rows repeating a site in their menu.
    """
    return news_order_report(rows, now)[0]


TIER_NAMES = ("fresh", "undated", "stale", "front_page_social_or_roundup")


def news_order_report(rows: list, now: float | None = None) -> tuple[list, dict]:
    """news_order plus what it did, for the response: rows are moved, never
    dropped, and a caller should be able to see how many and why."""
    from urllib.parse import urlsplit
    tiers = [news_tier(row, now) for row in rows]
    ordered = [row for _, row in sorted(zip(tiers, rows), key=lambda pair: pair[0])]
    report = {name: tiers.count(index) for index, name in enumerate(TIER_NAMES)}
    report.update(per_site_limit=PER_SITE, moved_by_site_limit=0)
    if PER_SITE <= 0:
        return ordered, report
    lead, rest, seen = [], [], {}
    for row in ordered:
        host = (urlsplit(row.get("url", "")).hostname or "").lower().removeprefix("www.")
        seen[host] = seen.get(host, 0) + 1
        (lead if seen[host] <= PER_SITE else rest).append(row)
    report["moved_by_site_limit"] = len(rest)
    return lead + rest, report


def news_tier(row: dict, now: float | None = None) -> int:
    """0 fresh, 1 undated, 2 stale, 3 front page, social post or roundup."""
    if is_landing(row) or _social(row) or _roundup(row):
        return 3
    value = row.get("published") or row.get("publishedDate") or ""
    if not str(value).strip():
        return 1
    from .signals import parse_date
    when = parse_date(str(value))
    if when is None:
        return 1
    now = time.time() if now is None else now
    return 0 if now - when.timestamp() <= FRESH_DAYS * 86400 else 2


def _maybe_save() -> None:
    global _dirty, _last_save
    now = time.time()
    if not _dirty or now - _last_save < SAVE_EVERY:
        return
    with _lock:
        snapshot = json.dumps(_load())
        _dirty, _last_save = False, now
    try:
        path = _path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(snapshot, encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def flush() -> None:
    global _last_save
    _last_save = 0.0
    _maybe_save()


def stats() -> dict:
    with _lock:
        state = json.loads(json.dumps(_load()))
    return {"enabled": ENABLED, "profiles": {
        profile: {"engines": {name: {"yield": round(e["yield"], 3), "observations": e["n"],
                                     "last": datetime.fromtimestamp(
                                         e.get("at", 0), timezone.utc).isoformat()}
                              for name, e in engines.items()},
                  "demoted": demoted(profile)}
        for profile, engines in state.items()}}


def reset() -> None:
    global _state, _dirty
    with _lock:
        _state, _dirty = {}, False
