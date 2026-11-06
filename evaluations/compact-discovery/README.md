# Compact evidence responses and sparse discovery

This offline harness compares response projection against the immutable 1.6.1
helper. It also links to the real Chromium discovery regression harness. Neither
requires external search requests or production state. Findings and limits are in
[the dated report](results/2026-11-06/REPORT.md).

From a prepared development environment:

```sh
git show v1.6.1:src/dethrottled/content.py > /tmp/baseline-content.py
python evaluations/compact-discovery/verify.py --baseline-source /tmp/baseline-content.py
```

The synthetic 194-page metadata fixture is generated in the harness. Supply
`--input /path/to/saved-fetch.json` to replay a saved response instead. Keep private
responses outside the repository. Measurements cover projection and JSON encoding,
not acquisition latency or whole-process memory. Seven repeats use the identical
canonical metadata, asserting that excerpts, handles, warnings and continuation
are preserved and that the input is not mutated.

For the browser test, use the browser image's prepared Patchright/Chromium/Xvfb
environment, with candidate `service.py` and `verify_search.py` copied or mounted
into `/app`. Tests use a local HTTP fixture, software rendering and no live engines:

```sh
cd /app
python verify_search.py
```

For the before/after sparse-query comparison, save the original service source
with `git show v1.6.1:browser-search/service.py`, make that file available in the
container, and set `BASELINE_SERVICE_SOURCE` to its path. Only its `_engine` and
`_usable` functions are loaded for the baseline; fixture server, browser, pacing,
timeouts, extraction, race coordinator and requested limits stay identical.
The harness also checks strict menu caps, no pagination, bounded failure history,
redaction, admission cleanup and explicit refusal reporting.

## Optional live DDG observation

`live_ddg.py` sends one normal acquisition for each of two queries with historical
HTTP 202 evidence. Run it only in a disposable environment with
`DETHROTTLED_BROWSER_SEARCH_URL` pointing at the disposable browser worker and
`DETHROTTLED_ENGINE_HEALTH` pointing at its own temporary health file. Supply the
same validated filtering snapshot to both processes. It bypasses caches, requests
no supplementary providers, spaces queries by five seconds and never clears
cooldowns. Optional `--browser-controls` makes two additional, explicitly labelled
browser-only calls. It does not manufacture refusals or retry until success.

A successful query days after a recorded refusal demonstrates availability at the
new observation time. It does not prove that the pipeline defeated a current
challenge; same-request refusal-and-recovery evidence is reported separately.
