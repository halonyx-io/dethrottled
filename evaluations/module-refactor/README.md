# Module-boundary refactor verification — 2026-11-05

This change separates HTTP request models from route execution and URL identity
from fetch orchestration. Existing `server.*Body`, `server.DriveStep` and
`fetch.canonical_url` imports remain usable. Search-menu helpers, corpus storage,
fetch escalation and worker configuration stay in place.

## URL helper measurement

Query filtering now uses one lowercase operation and a tuple-prefix check per
parameter instead of a generator repeatedly lowercasing the key. URL-parser imports
are resolved at module load. Outputs matched the pre-refactor implementation for
15,007 synthetic and malformed/empty inputs.

Python 3.13, x86_64; nine rounds, 5,000 URLs per workload per round. Baseline/candidate
order alternates. Values below are median total milliseconds for each 5,000-URL batch.
Raw timings and source hashes are in [results.json](results.json).

| Workload | Baseline ms | Candidate ms | Helper speedup |
| --- | ---: | ---: | ---: |
| no query | 19.79 | 16.02 | 1.24× |
| two parameters | 35.28 | 27.67 | 1.28× |
| twelve parameters | 128.67 | 92.93 | 1.38× |

These are CPU microbenchmarks, not end-to-end search/fetch latency measurements.
They do not imply changes to coverage, ranking, throughput or provider latency.

```sh
python evaluations/module-refactor/benchmark.py --output /tmp/url-results.json
```

The harness reads the recorded baseline revision through Git and the candidate
helper from the working tree. No provider requests or model downloads occur.

## Behaviour and packaging checks

- Baseline: 631 passed, 67 skipped, two network tests deselected.
- Implementation: 647 passed, 67 skipped, two network tests deselected.
- All 24 OpenAPI paths, 12 request schemas and 31 accepted/rejected payload outcomes
  match the baseline exactly; see [contracts.json](contracts.json).
- New regression checks cover old import paths, a lightweight URL-helper import,
  malformed inputs and preservation of meaningful repeated/blank query parameters.
  An existing canonical-URL assertion previously ended in `or True`; it now asserts
  the actual expected behaviour.
- Wheel and sdist build passed. The wheel includes both new modules; installed-wheel
  imports, aliases, OpenAPI generation and bundled stack-context verification passed.
- Ruff and documentation/reference checks passed locally.

Run `PYTHONPATH=src pytest -q -m 'not network'` in the development environment.
To compare contracts independently, extract the baseline revision into a temporary
folder and run `contract_snapshot.py` twice with `PYTHONPATH` pointing to each
revision's `src`; compare the resulting JSON. The snapshot includes the full API
schema and validation outcomes. It does not make any network requests.

Skipped tests retain gaps for unavailable optional libraries and model weights.
Local checks alone do not establish cross-platform release validation. No package
version, published artifact or production container is changed by this refactor.
