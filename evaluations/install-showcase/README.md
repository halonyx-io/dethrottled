# Complete installation and two-device evaluation

This protocol validates the package-managed deployment before making performance
claims. The workload is frozen in [manifest.json](manifest.json); its assertions
are literal text-retention checks. They are not independent truth judgements or
an evaluation of all supported document layouts.

## Installation gates

Use an Ubuntu ARM64 Q6A with Python 3.12. Create separate, fresh core and `[all]`
virtual environments. Save pip installation reports and dependency inventories.
Build a wheel, record its SHA-256, and run it from outside the source checkout.
The package must not start services or acquire model weights during installation.

```sh
python -m build
python scripts/verify_stack_package.py dist/dethrottled-*.whl
python3 -m venv /tmp/dethrottled-core
/tmp/dethrottled-core/bin/pip install dist/dethrottled-*.whl
cd /tmp
/tmp/dethrottled-core/bin/dethrottled --help
/tmp/dethrottled-core/bin/dethrottled stack up --project dethrottled-benchmark --port 19087
/tmp/dethrottled-core/bin/dethrottled stack status --project dethrottled-benchmark
```

Install Docker through the [official Ubuntu path](https://docs.docker.com/engine/install/ubuntu/)
when absent. The CLI checks prerequisites; it does not install packages or change
privileges/firewalls. Save original errors before fixing and repeating a gate.
Check default, media, layout and full profiles. Distinguish model initialization
from readiness. Stop a worker to verify unavailable status. Test port conflicts,
worker restart, retained documents and model/data volumes across `stack down`.

After publishing a new immutable release, repeat with its actual PyPI package
and a fresh GitHub clone at that tag. Installing a locally built wheel is not
proof that the published artifact works.

## Fixed workloads

Use isolated `dethrottled-benchmark` projects and fresh named volumes on both
hosts. Production services remain untouched. Match runtime source, manifest and
fixture bytes. Record native image IDs, dependency inventories, Docker/Compose
versions, hardware, background load and startup logs. Default runs expose no GPU.

Generate controlled files once inside the API image:

```sh
python scripts/benchmark_fixtures.py /tmp/formats
```

Hash and copy those exact bytes to the other host; PDF and Office metadata can
vary if independently regenerated. Serve them with [fixture.py](fixture.py),
mounted alongside `evaluations/` in a private Python container on each project
network with alias `fixture`. The fixture has no published host port.

Run [the browser/document contracts](../release/run.py) three times on each
host. Restart only the isolated browser worker, then run its `--phase restore`
check. Retain each run separately. Independent controlled host runs may overlap;
serial live host runs avoid competing for upstream quotas.

```sh
python evaluations/install-showcase/benchmark.py \
  --manifest evaluations/install-showcase/manifest.json \
  --out results/q6a-formats --phase formats
```

Run phases `formats`, `concurrency`, `search-fresh`, `search-warm`, `fetch-fresh`,
`fetch-warm` and `research`. Formats repeat eleven fixtures three times and check
retained-document reads. Concurrency repeats twelve local HTML fetches at one,
three and six callers in three rounds. It never bursts a public search engine.

Each device gets 50 English search questions, 30 fixed public fetch targets and
six research tasks. Fresh search starts are at least three seconds apart. Run
Q6A then szbox for fresh acquisition, reversing order for cache-enabled repeats.
Keep empty, thin, suspect, blocked, failed and timed-out cases. Preserve provider
attempts and cached-row flags. Cache-enabled does not guarantee a cache hit.

The optional inference harness performs a first request and three subsequent
jobs. Check that the actual worker was used: native PDF fallback does not pass
as Docling. Model caches are fresh for first-use measurements and retained for
later jobs. Resource samples and optional-profile costs remain separate from
the default comparison.

## Interpreting and reproducing the figures

Latency includes failures and is client-observed wall time. p95 uses the nearest
rank. Docker stats samples estimate container working-set memory and CPU use;
100% CPU means one logical core. They exclude host activity, the fixture server,
and sampling gaps, so measured peaks are sampled lower bounds. Host load before
and after each phase is retained.

A `quality=ok` read is the engine's assessment, not semantic verification. Public
assertions mostly check topic markers. Controlled assertions check predefined
synthetic facts. Research counts readable sources and exposes coverage gaps;
it does not verify an answer. Search counts measure delivery and menu budgets,
not relevance. A single sequential live cohort cannot establish a hardware
speed ranking or future source availability.

After copying both devices' case/resource folders into a results directory:

```sh
python evaluations/install-showcase/summarize.py \
  --results evaluations/install-showcase/results/2026-11-04 \
  --assets docs/assets
python scripts/build_showcase.py
```

Chart generation requires Matplotlib; vector illustrations use only Python's
standard library. Neither is a runtime dependency. Every chart derives from
retained JSON. [Results and issue resolutions](results/2026-11-04/ISSUES.md)
keep original failures separate from final measurements.
