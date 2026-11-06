# Fetch edge cases

Regressions for small acquired DOMs, large detailed responses and separate
connection/read timeouts. These checks do not alter search ranking or corpus
policy. Install the project's `dev` and `tls` extras in a disposable environment.

```sh
DETHROTTLED_ADBLOCK=0 PYTHONPATH=src python -m pytest -q tests/test_fetch_edge_cases.py
```

The slow-body regressions use a loopback HTTP fixture, not an external provider.
TLS cases skip when the optional curl_cffi library is absent.

For one live direct/TLS observation (no renderer or read-plan browser recovery):

```sh
DETHROTTLED_ADBLOCK=0 PYTHONPATH=src python evaluations/fetch-edge-cases/acquisition.py
```

Run once per version, not in a stress loop. Upstream availability changes; this
is not a benchmark of GNU's general availability. A request can exceed the
connect allowance during DNS resolution, multiple address attempts, response
reading or later worker recovery.

[Dated results and limitations](results/2026-11-06/REPORT.md) retain the negative
outcome as well as the timeout reduction. Tests require no image rebuild.

## Batch scheduling comparison

Use the same Python environment for both schedulers. The harness extracts only
the baseline `_read_batch` function, shares the candidate's executor and alternates
which scheduler runs first. Fixtures use local waits, not upstream traffic.

```sh
git show a774f15:src/dethrottled/server.py > /tmp/dethrottled-baseline-server.py
DETHROTTLED_ADBLOCK=0 PYTHONPATH=src python evaluations/fetch-edge-cases/batch_measure.py /tmp/dethrottled-baseline-server.py
```

The script asserts identical ordered output hashes and records raw timings and
peak active reads. Follow-up regressions for redirects and malformed caches:

```sh
DETHROTTLED_ADBLOCK=0 PYTHONPATH=src python -m pytest -q tests/test_fetch_efficiency.py tests/test_cache.py tests/test_pipeline_improvements.py
```
