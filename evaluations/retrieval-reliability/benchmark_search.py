"""Offline degraded-search comparison. Provider latency/refusals are controlled.

This measures orchestration truth and retry counts, not actual DDG recovery.
"""
import argparse
import hashlib
import json
import os
import platform
import sys
import tempfile
import time
import types
from pathlib import Path
from unittest.mock import patch

from dethrottled import search, server
from dethrottled.api_models import SearchBody


def row(engine, index):
    return {"url": f"https://example.org/{engine}/{index}", "engine": engine,
            "title": "Useful source choice", "snippet": "Relevant evidence for the requested task."}


def scenario(primary, supplements, empty=False):
    calls = {"primary": 0, "supplements": 0, "health_sx": 0, "health_bing": 0}

    def web(*args, diagnostics, **kwargs):
        calls["primary"] += 1
        diagnostics.update(status="no_results" if empty else "ok" if primary else "failed")
        return [row("web-tls-ddg-lite", i) for i in range(10)] if primary and not empty else []

    def sx(*args, diagnostics, engines, **kwargs):
        calls["supplements"] += 1
        diagnostics.update(status="ok" if supplements else "http_429")
        return [row(engines, i) for i in range(3)] if supplements and not empty else []

    class Response:
        status_code = 200

        def json(self):
            return {"results": [row("fixture", 0)] if supplements else []}

    def health_get(*args, **kwargs):
        calls["health_sx"] += 1
        time.sleep(0.005)
        return Response()

    def health_news(*args, **kwargs):
        calls["health_bing"] += 1
        time.sleep(0.005)
        return [row("fixture", 0)] if supplements else []

    if hasattr(search, "search_diagnostics"):
        search.search_diagnostics._OBSERVATIONS.clear()
    with patch.object(search, "SEARXNG_URL", "http://fixture"), \
            patch.object(search, "web_search", web), patch.object(search, "searxng", sx), \
            patch.object(search.requests, "get", health_get), \
            patch.object(search, "bing_news", health_news):
        rows, meta = search.search("controlled evidence")
        with patch.object(server, "_ranked", return_value=(rows, meta, 15)):
            envelope = server.search_envelope(SearchBody(query="controlled evidence"))
        timings = []
        for _ in range(5):
            start = time.perf_counter()
            ready = search.health()
            timings.append((time.perf_counter() - start) * 1000)
    return {"reported_ready": ready["ok"], "ready_report": ready, "calls": calls,
            "health_poll_ms": timings, "urls": [r["url"] for r in rows],
            "legacy_status": envelope["status"], "outcome": envelope.get("outcome"),
            "degraded": envelope.get("degraded"), "attempts": envelope["attempts"]}


def refusals():
    calls = []

    def tls(*args, diagnostics, **kwargs):
        calls.append("tls-ddg-lite")
        diagnostics.update(status="challenge_or_http_error", http_status=429)
        return []

    def browser(*args, diagnostics, **kwargs):
        calls.extend(["browser-ddg-lite", "browser-ddg-html"])
        diagnostics.update(status="http_503", attempts=[
            {"engine": e, "status": 429, "reason": "http_429"} for e in ["ddg-lite", "ddg-html"]])
        return []

    class DDGS:
        def text(self, *args, **kwargs):
            calls.append("ddgs")
            raise RuntimeError("controlled provider refusal")

    outcomes = []
    with patch.dict(os.environ, {"DETHROTTLED_CHEAP_DISCOVERY": "1"}), \
            patch.object(search, "tls_search", tls), \
            patch.object(search, "browser_search", browser), \
            patch.dict(sys.modules, {"ddgs": types.SimpleNamespace(DDGS=DDGS)}):
        for _ in range(3):
            report = {}
            search.web_search("controlled refusal", diagnostics=report)
            outcomes.append({"cumulative_attempts": len(calls), "diagnostics": report})
    return {"attempts": calls, "outcomes": outcomes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
            "DETHROTTLED_ENGINE_HEALTH": temp + "/engines.json"}):
        result = {"label": args.label, "architecture": platform.machine(),
                  "search_source_sha256": hashlib.sha256(
                      Path(search.__file__).read_bytes()).hexdigest(),
                  "api_source_sha256": hashlib.sha256(
                      Path(server.__file__).read_bytes()).hexdigest(),
                  "controlled_probe_latency_ms": 5,
                  "scenarios": {"ddg_down_backups_up": scenario(False, True),
                                "ddg_up_backups_down": scenario(True, False),
                                "complete_outage": scenario(False, False),
                                "all_healthy": scenario(True, True),
                                "genuine_empty": scenario(True, True, empty=True)},
                  "correlated_refusals": refusals()}
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"label": args.label,
                      "refusal_attempts": len(result["correlated_refusals"]["attempts"])}))


if __name__ == "__main__":
    main()
