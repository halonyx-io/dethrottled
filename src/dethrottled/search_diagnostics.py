"""Search outcomes and bounded readiness observations; never reorder results."""

from __future__ import annotations

import threading
import time

_SUCCESS = {"ok", "cached", "no_results", "no_matching_candidates"}
_SKIPPED = {"not_requested", "not_configured"}
_LOCK = threading.Lock()
_OBSERVATIONS = {}
OBSERVATION_TTL = 60.0


def outcome(count, report):
    status = report.get("status", "unknown")
    if status in _SKIPPED:
        return status
    if count:
        return "degraded" if status not in _SUCCESS or report.get("upstream_status") in {
            "cooldown", "recovery_in_progress", "unavailable"} else "available"
    if report.get("upstream_status") in {"cooldown", "recovery_in_progress", "unavailable"}:
        return "unavailable"
    if status in _SUCCESS:
        return "empty"
    if status in {"unknown", "thin_or_empty", "indeterminate"}:
        return "unknown"
    return "unavailable"


def summarize(per_source, reports):
    providers = {}
    for name, count in per_source.items():
        if name in {"gnews-resolved", "reputable-sweep"}:
            continue
        report = reports.get(name) or reports.get("supplements", {}).get(name) or (
            reports.get("providers", {}).get(name)) or {}
        # Aggregate SearXNG counts are not another provider vote.
        if name == "searxng" and reports.get("supplements") and not report:
            continue
        count_status = count if isinstance(count, str) else "unknown"
        status = report.get("status", count_status)
        count = count if isinstance(count, int) else 0
        providers[name] = {"count": count, "status": status,
                           "availability": outcome(count, dict(report, status=status)),
                           "upstream_status": report.get("upstream_status", status),
                           "families": report.get("families", [])}
    requested = [r for r in providers.values() if r["status"] not in _SKIPPED]
    useful = any(r["count"] for r in requested)
    unhealthy = any(r["availability"] in {"unavailable", "unknown", "degraded"}
                    for r in requested)
    if useful:
        label = "partial_results" if unhealthy else "results"
    elif requested and all(r["availability"] == "empty" for r in requested):
        label = "no_results"
    elif requested and all(r["availability"] == "unavailable" for r in requested):
        label = "unavailable"
    else:
        label = "indeterminate"
    return {"outcome": label, "degraded": unhealthy or not requested,
            "providers": providers, "primary": providers.get("web", {
                "status": "not_requested", "availability": "not_requested", "count": 0})}


def observe(discovery):
    now = time.time()
    with _LOCK:
        for name, row in discovery["providers"].items():
            if row["status"] not in _SKIPPED:
                if row["status"] == "cached" and row.get("upstream_status") == "cached":
                    previous = _OBSERVATIONS.get(name, {})
                    if now - previous.get("observed_at", 0) < OBSERVATION_TTL:
                        continue  # Cached evidence does not refresh upstream health.
                    row = dict(row, availability="unknown", upstream_status="unknown",
                               cached_results_available=True)
                _OBSERVATIONS[name] = dict(row, observed_at=now)


def readiness(*, configured):
    """Report recent real-search observations without sending upstream probes.

    Cold or stale discovery is unknown, not down. Process/worker liveness is
    checked separately. Normal searches refresh these bounded observations.
    """
    with _LOCK:
        components = {}
        for name in ("web", "yandex", "yahoo", "bing-news"):
            row = dict(_OBSERVATIONS.get(name, {}))
            age = max(0, time.time() - row.get("observed_at", 0)) if row else None
            stale = age is None or age >= OBSERVATION_TTL
            availability = row.get("availability", "unknown") if not stale else "unknown"
            components[name] = dict(
                row, availability=availability, stale=stale,
                observation_state="unobserved" if age is None else "stale" if stale else "current",
                last_observed_availability=row.get("availability", "unknown"),
                age_seconds=round(age, 3) if age is not None else None)
        initializing = not bool(_OBSERVATIONS)
    primary = components["web"]
    primary_ready = (primary["availability"] in {"available", "empty", "degraded"}
                     and primary.get("upstream_status") not in {"cooldown", "recovery_in_progress"})
    supplementary = {name: components[name] for name in ("yandex", "yahoo")}
    sx = any(row["availability"] in {"available", "empty", "degraded"}
             for row in supplementary.values())
    sx_status = ("not_configured" if not configured else
                 "degraded" if sx and any(r["availability"] not in {"available", "empty"}
                                         for r in supplementary.values()) else
                 "ok" if sx else
                 "down" if all(r["availability"] == "unavailable"
                               for r in supplementary.values()) else "unknown")
    return {"ok": primary_ready, "searxng": sx, "searxng_status": sx_status,
            "bing_news": components["bing-news"]["availability"] in {"available", "empty"},
            "searxng_configured": configured,
            "primary_discovery": dict(primary, ready=primary_ready,
                                      family=("ddg" if primary.get("families") == ["ddg"]
                                              else "web")),
            "supplementary": supplementary, "news": components["bing-news"],
            "initializing": initializing,
            "degraded": not primary_ready or (configured and not all(
                row["availability"] in {"available", "empty"} for row in supplementary.values())),
            "observation_ttl_seconds": OBSERVATION_TTL,
            "detail": "Primary discovery is distinct from supplementary/news availability; "
                      "readiness observations are cached, not an availability guarantee."}
