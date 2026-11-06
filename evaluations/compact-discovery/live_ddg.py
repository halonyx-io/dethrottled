"""Opt-in, paced DDG recovery observation using the ordinary acquisition ladder.

Run only in a disposable environment with an explicitly configured browser worker
and an isolated engine-health file. No cache, supplements, reset of refusals or
retry-until-success loop. A later success is not proof of defeating a challenge.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from urllib.parse import urlsplit

from dethrottled import adblock, search

QUERIES = [
    # Both Lite and HTML returned HTTP 202 for this exact hash in the retained study.
    'Were Scott Derrickson and Ed Wood of the same nationality?',
    'Why are RGB and CMYK used for different display and printing workflows?',
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser-controls', action='store_true')
    args = parser.parse_args()
    if not search.BROWSER_SEARCH_URL or not os.environ.get('DETHROTTLED_ENGINE_HEALTH'):
        raise SystemExit('Explicit disposable browser worker and engine-health file required')
    observed = []
    original = search.requests.get_using

    def capture(fn, url, *args, **kwargs):
        response = original(fn, url, *args, **kwargs)
        if urlsplit(url).hostname == 'lite.duckduckgo.com':
            body = response.text or ''
            observed.append({'host': 'lite.duckduckgo.com', 'status': response.status_code,
                             'body_sha256': hashlib.sha256(body.encode()).hexdigest(),
                             'challenge_markers': [m for m in ('anomaly.js', 'bots use duckduckgo',
                                                               'challenge-platform')
                                                   if m in body[:20000].lower()]})
        return response

    search.requests.get_using = capture
    results = []
    try:
        for index, query in enumerate(QUERIES):
            if index:
                time.sleep(5)
            observed.clear()
            diagnostics = {}
            started = time.perf_counter()
            rows = search.web_search(query, max_items=10, cache=None, diagnostics=diagnostics)
            ddg_rows = [row for row in rows if search.result_family(row) == 'ddg']
            refused = diagnostics.get('direct', {}).get('refusal', False)
            results.append({'query': query,
                            'query_sha256': hashlib.sha256(query.encode()).hexdigest(),
                            'seconds': time.perf_counter() - started,
                            'diagnostics': diagnostics, 'tls_observations': list(observed),
                            'ddg_results': ddg_rows,
                            'same_request_tls_refusal_then_ddg_read': bool(refused and ddg_rows),
                            'claim': ('TLS refusal recovered within ordinary DDG acquisition'
                                      if refused and ddg_rows else
                                      'DDG available now; no same-request refusal recovery proven'
                                      if ddg_rows else 'No DDG read recovered')})
    finally:
        search.requests.get_using = original
    controls = []
    if args.browser_controls:
        for query in QUERIES:
            time.sleep(5)
            diagnostics = {}
            started = time.perf_counter()
            rows = search.browser_search(query, max_items=10, cache=None,
                                         diagnostics=diagnostics)
            attempts = diagnostics.get('attempts', [])
            refused = any(a.get('status') in {202, 429}
                          or a.get('reason') == 'challenge_page' for a in attempts)
            controls.append({'query': query, 'seconds': time.perf_counter() - started,
                             'diagnostics': diagnostics, 'ddg_results': rows,
                             'one_variant_refused_another_returned_results': bool(refused and rows),
                             'scope': 'explicit browser-control call; not automatically reached '
                                      'when TLS already succeeds'})
    policy = adblock.status()
    print(json.dumps({'scope': 'two historical refusal queries; one live acquisition each',
                      'adblock': {k: policy.get(k) for k in ('enabled', 'available', 'sha256')},
                      'results': results, 'browser_controls': controls}, indent=2))


if __name__ == '__main__':
    main()
