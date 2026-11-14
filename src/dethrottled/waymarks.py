"""Waymarks: which steps of the read ladder each site has taught us to skip.

## Why

Every read climbs the same ladder: plain HTTP, TLS impersonation, the
renderer, a real browser. On most sites the cheap steps fail in well under a
tenth of a second, so remembering the winning step saves almost nothing. Two
patterns are expensive and repeat on every read of the same site (measured on
14 Nov 2026, 5,924 stored reads):

- plain HTTP left hanging until its timeout, 18.7 s each time, on sites that
  TLS then read in about a second (nseindia.com, npr.org, pogo.org);
- a challenge the real browser never clears, 15 s each time (Stack Exchange's
  Cloudflare cost one research call 33 s).

So this remembers what to SKIP, not what won. A step is skipped for a site
only after it failed the same way three reads running while a later step
worked; a site whose real browser has hit an unresolved challenge three reads
running fails at once as a known wall. Skipped steps are retried now and then
(a probe), so a site that changes is noticed and the record heals itself.

## Privacy

The record is about sites, not callers, but a remote caller must not learn
which sites other callers read:

- only public internet hosts are recorded, never intranet or private ones;
- hosts are stored as keyed hashes (HMAC with a per-install secret), so the
  file is not a browsing history; no paths, queries, content or callers;
- a streak built by one caller applies only to that caller; it applies to
  everyone once at least two callers have independently hit it;
- nothing here lists hosts: stats() reports counts only.

## Cost

A dictionary lookup per read and a small JSON file written at most once a
minute. Nothing on the read path touches the disk.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from urllib.parse import urlsplit

from . import paths as _paths

ENABLED = os.environ.get("DETHROTTLED_WAYMARKS", "1").strip().lower() not in {
    "0", "false", "no", "off"}
STREAK = max(2, int(os.environ.get("DETHROTTLED_WAYMARK_STREAK", "3")))
FRESH_SECONDS = float(os.environ.get("DETHROTTLED_WAYMARK_FRESH_HOURS", "24")) * 3600
WON_SECONDS = 7 * 86400          # a later step must have worked this recently
PROBE_SECONDS = float(os.environ.get("DETHROTTLED_WAYMARK_PROBE_HOURS", "6")) * 3600
WALL_PROBE_SECONDS = float(os.environ.get("DETHROTTLED_WAYMARK_WALL_PROBE_MINUTES",
                                          "30")) * 60
PROBE_EVERY = 10                 # also retry one in ten skip-eligible reads
MAX_ENTRIES = int(os.environ.get("DETHROTTLED_WAYMARK_MAX_ENTRIES", "20000"))
SAVE_EVERY = 60.0
LADDER = ("direct", "tls", "crawl4ai", "headed")

_lock = threading.Lock()
_state: dict | None = None
_secret: bytes | None = None
_dirty = False
_last_save = 0.0
_counts = {"skipped_steps": 0, "known_walls": 0, "probes": 0}


def _path():
    return _paths.data_dir() / "waymarks.json"


def _key_material() -> bytes:
    global _secret
    if _secret is None:
        path = _paths.data_dir() / "waymarks.key"
        try:
            _secret = bytes.fromhex(path.read_text().strip())
        except (OSError, ValueError):
            _secret = secrets.token_bytes(32)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as handle:
                    handle.write(_secret.hex())
            except OSError:
                pass  # in-memory secret: the record lasts until restart
    return _secret


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").rstrip(".").lower()
    except ValueError:
        return ""


def _hash(value: str) -> str:
    return hmac.new(_key_material(), value.encode(), hashlib.sha256).hexdigest()[:32]


def _load() -> dict:
    global _state
    if _state is None:
        try:
            _state = json.loads(_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _state = {}
    return _state


def _failure_kind(attempt: dict) -> str | None:
    """What a failed step says about the SITE, or None if it says nothing.

    Page-level results (an empty shell, thin text, a 404) and our own capacity
    (renderer busy, resting, unreachable) are not facts about the site's
    willingness to serve that step, so they never build a streak.
    """
    tier, outcome = attempt.get("tier"), attempt.get("outcome")
    reason = str(attempt.get("reason") or "")
    if outcome in {"extracted", "thin", "shell", "response", "skipped"} or not tier:
        return None
    if tier == "crawl4ai" and reason.startswith((
            "crawl4ai_busy:", "crawl4ai_http_", "crawl4ai_Connection", "crawl4ai_Read",
            "crawl4ai_Connect", "crawl4ai_Timeout")):
        return None  # our renderer's own state, not the site
    if tier == "headed" and "challenge_unresolved" in reason:
        return "wall:" + reason.rsplit(":", 1)[-1]
    if outcome == "challenge" or "challenge" in reason:
        return "challenge"
    if reason.startswith("no_response_in_"):
        return "silent"  # TLS answered while plain HTTP had not (fetch._race_direct)
    if any(word in reason for word in ("Timeout", "ConnectionError", "SSLError")):
        return "timeout"
    if any(reason.endswith(code) for code in ("_403", "_429", "_401", "_451")):
        return "blocked"
    return None


def observe(url: str, attempts: list, namespace: str = "local") -> None:
    """Learn from one read's acquisition attempts. Never raises."""
    if not ENABLED or not attempts:
        return
    try:
        _observe(url, attempts, namespace)
    except Exception:  # bookkeeping must never break a read
        return


def _observe(url, attempts, namespace):
    global _dirty
    real = [a for a in attempts if a.get("tier") in LADDER and a.get("outcome") != "skipped"]
    if not real:
        return
    host = _host(url)
    if not host:
        return
    key = _hash(host)
    kinds = [(a["tier"], _failure_kind(a), a.get("outcome")) for a in real]
    interesting = any(kind for _, kind, _ in kinds) or real[-1]["tier"] != "direct"
    with _lock:
        known = key in _load()
    if not interesting and not known:
        return  # plain HTTP read it first time: nothing worth remembering
    from .research import public_url
    if not public_url(url):
        return  # never record intranet or private hosts
    caller = _hash("ns|" + str(namespace))[:12]
    now = time.time()
    with _lock:
        state = _load()
        entry = state.setdefault(key, {"tiers": {}, "won": {}})
        entry["seen"] = now
        for tier, kind, outcome in kinds:
            record = entry["tiers"].setdefault(tier, {})
            if kind:
                if record.get("kind") != kind:
                    record.update(kind=kind, streak=0, callers=[])
                record["streak"] = record.get("streak", 0) + 1
                record["last_fail"] = now
                if caller not in record.setdefault("callers", []):
                    record["callers"] = (record["callers"] + [caller])[-4:]
            elif outcome in {"extracted", "thin", "shell", "response"}:
                # The step answered: whatever it was skipped for has changed.
                entry["tiers"].pop(tier, None)
                if outcome == "extracted":
                    entry["won"][tier] = now
        if len(state) > MAX_ENTRIES:
            for old in sorted(state, key=lambda k: state[k].get("seen", 0))[
                    :max(1, MAX_ENTRIES // 10)]:
                state.pop(old, None)
        _dirty = True
    _maybe_save()


def _applies(record: dict, caller: str, now: float) -> bool:
    if record.get("streak", 0) < STREAK or now - record.get("last_fail", 0) > FRESH_SECONDS:
        return False
    callers = record.get("callers", [])
    return len(callers) >= 2 or callers == [caller]


def plan(url: str, namespace: str = "local") -> dict:
    """What to skip for this read: {"skip": {tier: why}, "wall": why or None}."""
    empty = {"skip": {}, "wall": None}
    if not ENABLED:
        return empty
    try:
        host = _host(url)
        if not host:
            return empty
        key = _hash(host)
        with _lock:
            entry = _load().get(key)
            if not entry:
                return empty
            entry = json.loads(json.dumps(entry))
        return _plan(entry, _hash("ns|" + str(namespace))[:12], time.time())
    except Exception:
        return empty


def _plan(entry, caller, now):
    out = {"skip": {}, "wall": None}
    tiers = entry.get("tiers", {})
    headed = tiers.get("headed", {})
    won = entry.get("won", {})
    if (str(headed.get("kind", "")).startswith("wall:") and _applies(headed, caller, now)
            and not any(t > headed["last_fail"] for t in won.values())):
        if now - headed["last_fail"] < WALL_PROBE_SECONDS:
            _counts["known_walls"] += 1
            out["wall"] = {"kind": headed["kind"].split(":", 1)[1], "streak": headed["streak"],
                           "retry_after_seconds": int(WALL_PROBE_SECONDS
                                                      - (now - headed["last_fail"]))}
            return out
        _counts["probes"] += 1
        return out  # probe: let the full ladder try again
    for index, tier in enumerate(LADDER[:-1]):
        record = tiers.get(tier)
        if not record or str(record.get("kind", "")).startswith("wall:"):
            continue
        if not _applies(record, caller, now):
            continue
        if not any(now - won.get(later, 0) < WON_SECONDS for later in LADDER[index + 1:]):
            continue  # nothing later has worked: skipping would skip into nothing
        if now - record["last_fail"] > PROBE_SECONDS:
            _counts["probes"] += 1
            continue
        _counts["skipped_steps"] += 1
        out["skip"][tier] = {"kind": record["kind"], "streak": record["streak"]}
    return out



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
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(snapshot)
        tmp.replace(path)
    except OSError:
        pass


def flush() -> None:
    global _last_save
    _last_save = 0.0
    _maybe_save()


def stats() -> dict:
    """Counts only. Never hosts: see the module docstring."""
    with _lock:
        state = _load()
        walls = sum(1 for e in state.values() if str(
            e.get("tiers", {}).get("headed", {}).get("kind", "")).startswith("wall:"))
    return {"enabled": ENABLED, "sites": len(state), "walls": walls, **_counts}


def reset() -> None:
    """Forget everything. For tests."""
    global _state, _dirty
    with _lock:
        _state = {}
        _dirty = False
    for name in _counts:
        _counts[name] = 0
