# Scoped retrieval candidate evaluation

Controlled comparisons for hostname-constrained discovery, CSS fields, URL mapping
and terminal target refusals. The [dated report](results/2026-11-06/REPORT.md)
distinguishes fixed fixtures from live upstream evidence and notes unavailable gates.

The harness starts only a loopback fixture server. It does not use a search provider,
corpus, GPU or Docker worker. Run it in a disposable environment with the package's
normal dependencies. Disable automatic blocklist updates and use fresh temporary data.

```sh
DETHROTTLED_ADBLOCK=0 DETHROTTLED_DATA_DIR=/tmp/dethrottled-scope-eval \
  PYTHONPATH=src python evaluations/scoped-retrieval/verify.py --output /tmp/candidate.json
```

For baseline comparison, run the **same harness** against an unmodified installed
1.6.2, without the candidate `src` on PYTHONPATH, adding `--baseline`. The flag
records unsupported features rather than pretending baseline implements them.
Both modes reuse the same HTML and SearXNG response. Seven repetitions record
latency, process CPU time, Python-traced allocation peaks and fixture request counts.
The first timed crawl includes parser initialization; p95 is the maximum for n=7.
Fixture pacing is disabled inside the harness only; external provider pacing is
unchanged. Mapping and crawling perform different tasks, so their latency ratio
is not an equivalent-evidence speedup.

Additional regressions live in `tests/test_scoped_retrieval.py`. The actual worker
checks are `browser-search/verify_search.py` (real Chromium, local SERP fixture) and
`scripts/verify_adapter.py` (real MCP/REST adapter transport, local backend fixture).
Do not point these fixture probes at production services or external providers.

## Complete candidate stack

`integration.py` starts a dedicated software-rendered `dethrottled170qa` project
with fresh volumes, the default five services, actual MCP/REST adapters and a local
JavaScript/sitemap fixture. It requires locally built `dethrottled:1.7.0`,
`dethrottled-browser-search:1.7.0`, `dethrottled-adapters:1.7.0`, plus the stock pinned
upstream and format-worker images. Install `requirements/adapters.lock` into a
separate Python environment for the client. It does not alter production tags.

```sh
task_qa_dir=$(mktemp -d)
python evaluations/scoped-retrieval/integration.py up "$task_qa_dir"
python evaluations/scoped-retrieval/integration.py check "$task_qa_dir"
python evaluations/scoped-retrieval/integration.py down "$task_qa_dir"
```

The check includes bounded public example/documentation search reads, not a provider
load benchmark. Public pages may change: retain original failures and inspect the
returned source before interpreting an assertion. Credentials are generated only
for the disposable project and are not printed. The directory stores a private
bearer and registry; keep it private and delete it after preserving sanitized results.
`down` removes only the named QA project and its disposable volumes. The runtime's
normal production projects and retained data are outside this harness.
