# DDG refusal recovery

[The dated report](results/2026-11-06/REPORT.md) separates ordinary availability,
real request-profile refusals, live autonomous recovery and controlled outage tests.

`prove.py` requires an explicit live flag. Run it only in a disposable installation
with its own browser worker, its own engine-health file, cheap discovery enabled
and the validated adblock snapshot loaded. Production services/data are unnecessary.
The prepared core image has the required dependencies; no new dependency is added.

```sh
DETHROTTLED_CHEAP_DISCOVERY=1 \
DETHROTTLED_ENGINE_HEALTH=/tmp/ddg-proof-health.json \
DETHROTTLED_BROWSER_SEARCH_URL=http://browser-search:19888 \
python evaluations/ddg-recovery/prove.py --live-plain-primary-ablation
```

The experiment replaces only the first hop's curl impersonation with ordinary
`requests`. It does not replace the DDG response or browser results. Normal refusal
detection, browser selection, parsing, source limits and family health run unchanged.
No caches or supplementary sources are requested. Two fixed questions are spaced
by five seconds. An actual server-requested wait is honored, not reset. Success is
not assumed: each result records whether a real refusal and subsequent DDG recovery
occurred. A run where the first hop does not refuse cannot prove refusal recovery.
The shipped default retains curl impersonation; this ablation is test code only.

Additional live controls, also opt-in:

```sh
python evaluations/ddg-recovery/probe_static.py --live
```

This compares plain Lite GET, curl Lite GET, Lite/HTML form POST and HTML GET,
with four seconds between requests. It captures statuses, challenge markers,
body hashes and sample source choices. POST controls do not follow redirects.
They are experimental controls, not new production fallbacks.

Run the browser control inside the prepared browser image, with Xvfb running and
`service.py` importable (for example `PYTHONPATH=/app`):

```sh
PYTHONPATH=/app python /work/evaluations/ddg-recovery/probe_browser.py --live
```

It compares Lite navigation, actual HTML form submission and the JavaScript page.
No claim is made that a successful control was autonomously reached by production.

Offline refusal/parser/backoff checks:

```sh
pytest -q tests/test_discovery_recovery.py tests/test_search_observability.py
```

These cover sparse sources, challenges, genuine emptiness, misleading empty
fallbacks, persisted cooldowns, concurrent recovery, cached evidence and explicit
Retry-After. They do not substitute for the retained live observations.
