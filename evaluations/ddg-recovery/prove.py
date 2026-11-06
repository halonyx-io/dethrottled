"""Opt-in real DDG refusal recovery with a plain first-hop transport ablation.

The shipped first hop uses curl impersonation. This experiment deliberately
substitutes ordinary requests for that hop, retaining real upstream responses
and the ordinary autonomous browser fallback. No CAPTCHA is fabricated/solved.
Run only in an isolated environment with its own health file and browser worker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from urllib.parse import urlsplit

import requests as plain

from dethrottled import discovery, search

QUERIES = [
    "Were Scott Derrickson and Ed Wood of the same nationality?",
    "Python pathlib recursive glob documentation",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-plain-primary-ablation", action="store_true", required=True)
    parser.parse_args()
    if not search.BROWSER_SEARCH_URL or not os.environ.get("DETHROTTLED_ENGINE_HEALTH"):
        raise SystemExit("Explicit disposable browser worker and engine-health file required")
    if os.environ.get("DETHROTTLED_CHEAP_DISCOVERY") != "1":
        raise SystemExit("Enable cheap discovery in the disposable environment")
    original = discovery.requests.get_using
    observations = []

    def plain_first_hop(getter, url, **kwargs):
        if urlsplit(url).hostname != "lite.duckduckgo.com":
            return original(getter, url, **kwargs)
        kwargs.pop("impersonate", None)
        response = original(plain.get, url, **kwargs)
        body = response.text or ""
        observations.append(
            {
                "observed_at": time.time(),
                "status": response.status_code,
                "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
                "challenge_markers": [
                    marker
                    for marker in ["anomaly.js", "bots use duckduckgo", "select all squares"]
                    if marker in body.lower()
                ],
                "retry_after": response.headers.get("Retry-After"),
            }
        )
        return response

    results = []
    try:
        discovery.requests.get_using = plain_first_hop
        for query in QUERIES:
            if results:
                time.sleep(5)
            observations.clear()
            report = {}
            started = time.perf_counter()
            rows = search.web_search(query, max_items=10, cache=None, diagnostics=report)
            ddg = [row for row in rows if search.result_family(row) == "ddg"]
            results.append(
                {
                    "query": query,
                    "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
                    "seconds": time.perf_counter() - started,
                    "primary_transport": "plain requests; experimental first-hop replacement",
                    "upstream_observations": list(observations),
                    "diagnostics": report,
                    "results": ddg,
                    "real_refusal_then_autonomous_ddg_recovery": bool(
                        report.get("direct", {}).get("refusal") and ddg
                    ),
                    "family_health_after": search.health()["ddg_family"],
                }
            )
    finally:
        discovery.requests.get_using = original
    print(
        json.dumps({"experiment": "plain-primary transport ablation", "results": results}, indent=2)
    )


if __name__ == "__main__":
    main()
