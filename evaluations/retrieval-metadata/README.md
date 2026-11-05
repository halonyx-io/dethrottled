# Search diagnostics and corpus provenance — 5 November 2026

Unreleased fixes based on 1.5.2, alongside the native-adblock candidate. No version
bump, publication or deployment. Ranking, cache lifetimes, corpus eligibility,
models and network policy are unchanged.

## Findings and implementation

**Legacy search status: intentional compatibility behaviour.** `/v2/search`
continues to report `status="ok"` for nonempty menus, even when discovery was
partially degraded. `outcome`, `degraded`, provider diagnostics and attempts are
authoritative for discovery health. `/search` remains an array. MCP search keeps
its default list and diagnostic JSON-text contracts; `isError=false` is tool
execution, not proof of provider availability.

The server's ranked-search consumers, combined search/read endpoint, health
observers and adapters do not branch on the legacy envelope status as a health
signal. API/playbook guidance already described the authoritative fields.
One actual gap was found: research retained attempts but discarded aggregate
`outcome`/`degraded` when building per-query telemetry. It now carries those two
fields, with `indeterminate`/true on a local search exception. Useful partial
results remain available and in the original order. MCP tool and initialization
instructions now explicitly name diagnostic mode and legacy-status semantics.

**Corpus completeness loss: confirmed.** `enqueue()` reduced extraction metadata
to older OCR/partial/method fields and discarded the newer completeness object.
Consequently retrieval provenance lost sampled-coverage uncertainty even though
passage text and offsets survived. New admissions retain the scalar diagnostic
summary under `provenance.extraction.completeness`: status, assessment,
sampled/missing counts, extractor names and selection-change flag.

Strings are bounded to 64 characters; extractor names to eight entries; counts
must be integers from zero to one million. Arbitrary keys, structural samples,
raw anchors and embedded source text are excluded. The summary is stored once
per source in existing JSON, not separately per passage. No schema migration or
new dependency is needed. Existing extraction-sensitive versioning remains in
force: a changed diagnostic can create an ordinary new indexed version. An
unchanged acquisition by another caller reuses the existing indexed version and
updates its document handle/namespace binding correctly.

Completeness remains separate from `source_partial`, corpus indexing coverage
and answer verification. `unverified` is not promoted to complete. Metadata
already discarded by an older admission cannot be reconstructed automatically;
subsequent admissions preserve the information when supplied. There is no
background re-fetch or blanket reindex of existing evidence.

## Validation

The [original controlled run](results/before.log), with checkout paths and
trailing whitespace normalized, failed four tests before the
fix: two cross-caller provenance cases, bounded completeness retention and
research diagnostics. All four passed after the minimal changes.

- Focused search/research/corpus suites: **81 passed**.
- Native full suites: **841 passed, 15 skipped, 2 network-marked exclusions** on
  each of x86_64 and ARM64. Existing FastAPI/test-client deprecation warnings
  remain; the suite is not a live upstream-provider stress test.
- Real pinned MCP/REST transport verifier passed, including legacy list shape,
  diagnostic partial/empty/unavailable/indeterminate cases, useful-result order,
  refusal timing metadata, authentication, strict arguments and public-target
  restrictions. An initial new assertion incorrectly expected structuredContent
  from the search tool's Any return; it was corrected to decode the existing JSON
  text envelope. No wire-format change was made to satisfy that test.
- Corpus tests cover suspected-incomplete and unverified extraction, warnings,
  retained offsets, cross-caller public reuse, current document availability,
  unchanged-job reuse and exclusion of oversized/unrecognized payloads.

[Validation metadata](results/validation.json) records source hashes and original
suite summaries. [SHA256SUMS](results/SHA256SUMS) covers the retained records.
Adblock's earlier measurement evidence remains unchanged and tied to its original
source snapshot (`f25a9d1`); these fixes do not constitute a new adblock resource
benchmark.

Reproduce using installed native dependencies:

```sh
DETHROTTLED_ADBLOCK=0 PYTHONPATH=src pytest -q tests/test_search_observability.py tests/test_research.py tests/test_corpus_v2.py tests/test_corpus_v2_operations.py
DETHROTTLED_ADBLOCK=0 PYTHONPATH=src pytest -q -m 'not network'
docker build -t dethrottled-adapter:metadata-candidate -f adapters/Dockerfile .
docker run --rm --entrypoint python dethrottled-adapter:metadata-candidate verify_adapter.py
```

The transport verifier uses a deterministic local backend and temporary test
credentials. It does not contact live search engines or alter production.
