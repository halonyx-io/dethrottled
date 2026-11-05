# Corpus v2 validation

This is the evaluation package for the unreleased Corpus v2 candidate. It uses
fictional, labelled documents, existing pinned MiniLM/E5 weights, local HTTP
fixtures and disposable Compose projects. No search provider, cloud API or
production corpus is needed.

Read the [measured report](results/2026-11-05/REPORT.md),
[per-query comparisons](results/2026-11-05/per-query.csv),
[implementation guide](../../docs/CORPUS.md) and
[issue resolutions](results/2026-11-05/RESOLUTIONS.md).

## Verify the retained evidence

From the checkout root, with a standard Python installation:

```sh
python3 evaluations/corpus-v2/verify.py
```

The verifier checks artifact hashes and independently grades returned passage
text against the expected URL and full fact strings. It does not trust the
stored `fact_retained` flags. It also checks native regression replay, lifecycle,
public migration/rollback and concurrent-read outcomes. Runtime-source hashes
identify the code tested by the private validation wheel; later intentional
changes require a new capture rather than rewriting these historical hashes.
Repeated per-query JSON is losslessly gzip-compressed to keep repository size
reasonable; the verifier reads it directly. Summaries, manifests and CSV remain
readable without decompression.

## Reproduce acquisition and retrieval

Use an empty, isolated data directory and matching model assets. Existing
production data must not be used. For example, with the same native API image
and a writable disposable evidence directory:

```sh
docker run --rm --network none --entrypoint python \
  -e PYTHONPATH=/candidate/src -e DETHROTTLED_DATA_DIR=/evidence/v2 \
  -v "$PWD:/candidate:ro" -v "$PWD/corpus-lab:/evidence" \
  dethrottled:local /candidate/evaluations/corpus-v2/benchmark.py \
  v2 /evidence/v2-development.json
```

Create `corpus-lab` first and make it writable by the image user, or explicitly
run the container as the directory owner. The native image must contain the
existing semantic extras and pinned model assets; there is no download in this
network-disabled command. Repeat with `v1` and a **different empty data directory**.
Add `--heldout` for the separate 16-question fixture. Baseline v1 uses its actual
4,000-character indexing path; both variants retain the same canonical full
sources first. Retention, admission, indexing and retrieval timings are separate.

`model_ablation.py OUTPUT` captures a multilingual challenge with both models,
each model alone, and both support policies. `--validation` selects additional
queries frozen after policy development. `--reuse` replays the identical
retained synthetic corpus without re-embedding; it refuses a corpus whose active
URLs differ from the fixture. Never compare raw and standard policies as if only
the embedding model changed.

`scaling.py v1|v2 OUTPUT --rows 50000` measures storage/matrix behavior with fixed
384-dimensional unit vectors. It deliberately excludes model/tokenizer memory
and inference. Run each variant in a separate fresh process/data directory.
`replay.py ROOT OUTPUT` reproduces the retained v2 quality outcomes against the
four captured fixture databases; its output records reference hashes.

## Package and lifecycle gates

Build a wheel and install it outside the checkout. Use a private development
version when testing managed Compose, so an existing production image tag cannot
be replaced. Record the wheel hash, dependency inventory and native architecture.
The recorded `1.5.0.dev2` wheel was never uploaded to PyPI or released.

Use an isolated `corpus-v2-*` project and a separate port with the installed
`dethrottled stack up`. Then run:

```sh
python3 evaluations/corpus-v2/stack_smoke.py \
  --project corpus-v2-lab --port 17898 --context /path/to/managed/context \
  --output /path/to/stack.json
python3 evaluations/corpus-v2/concurrency.py \
  --container corpus-v2-lab-dethrottled-1 --port 17898 \
  --output /path/to/concurrency.json
```

The stack smoke refuses production project names and non-development versions.
It recreates the **isolated API** to verify real schema-1 rollback and schema-2
restore. `lifecycle.py` starts a disposable local API on port 17897 and tests
SIGKILL, restart, simulated lease expiry and SIGTERM during inference. Give it an
isolated `DETHROTTLED_DATA_DIR`; publish the model paths normally used by that
installation. Never run it against a production data directory.

Native wheel suites used Python 3.12.16, `pytest==9.2.0`, and `httpx==0.28.1`
installed into disposable test directories. The wheel was installed with
`--no-deps` over each native API image's existing runtime dependencies; tests ran
outside the checkout with that wheel first on `PYTHONPATH`, an isolated data
directory, `-m 'not network'` and `-p no:cacheprovider`. Fresh core-only Python
installation was tested separately. The default five-worker stack was then
built from the wheel's bundled context on both architectures.

After testing, `dethrottled stack down --project corpus-v2-lab` stops only the lab
project and preserves its volumes/models. Keep the JSON evidence separately.
