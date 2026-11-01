# 2026-11-01 measured release evidence

Compare deployed 0.7.0 (`5bd93c4`) with 0.8.0. See
[the report](../../MEASURED-IMPROVEMENTS.md) for conclusions and limitations.
Numbers here are mechanical fixture checks, not a representative web benchmark.

The renderer probe supplies 48 known successful upstream responses to isolate
admission. Fairness/queue bounds and kill-before-release faults are exercised by
`tests/test_measured_workers.py`; real HTTP disconnect is also recorded. Speech
uses the same 11-second file, model, decode and beam settings on both builds.
The PDF fixture is raster-only with known values; the vector counterpart is a
retention check. The format checks require readable facts, not merely HTTP 200.
The Rust candidate panic is retained, not counted as support.

`holdout-results.json` separates calibration, distinct fresh questions, unrelated
queries and one exact duplicate excluded from holdout. The original script's
membership-based split initially labelled that duplicate as calibration; records
were relabelled by position without reranking or changing scores/thresholds.
The raw calibration scores remain in `multilingual-baseline.json`.

For a source build run `pytest -q -m "not network"` and `ruff check .`.
Use the API image for actual-model experiments; its pinned ONNX weights are not
committed to git. Mount this directory at `/evidence` and set a disposable
`DETHROTTLED_DATA_DIR` when running `holdout_eval.py`. Use
`DETHROTTLED_MODEL_DIR=/opt/dethrottled/models` with the image's model directory.
`read_compare.py` needs format/layout worker URLs; the optional Compose profiles
and private workers are documented in CONFIGURATION.md. The recorded fixture
worker ports are 18403 (layout), 18404 (Tika), 18405 (isolated API). They are not
production public ports. `http_disconnect.py` requires the layout fixture worker.
Set `LABEL=baseline` or `candidate` for admission/cache/read probes. Baseline
images must come from the baseline commit; candidate source mounts must point to
this release, never to whichever future checkout happens to be active.

Download external fixtures from URLs in fixture-manifest.json and verify SHA-256
before running. Only the two synthetic PDFs are included. Upstream file URLs
may change; the hashes define the tested bytes. MSG bodies contain upstream
Apache Tika test emails. Preserve their license and attribution if redistributing
those original fixture files. Snapshot JSON outputs and SDK events include public
source text and scoped temporary evidence handles, never bearer credentials.

Public MCP probes use the real Python MCP SDK 1.28.1, initialize a fresh client,
list tools and then fetch, inspect and read retained documents. This establishes
the server/SDK boundary, not that a particular remote plugin loaded updated code
or that every agent model follows the instructions. Public REST reads and the
older browser/search/site/speech workflows are also recorded.

`shutdown-results.json` measures real API shutdown during native backfill after
44 passages have committed, using copies of the same retained corpus. Core dumps
are disabled in both probe containers. The threaded implementation exits 139;
the process-isolated implementation exits 0. `shutdown-warmup-results.json` keeps
the earlier probe stopped before any passages committed (both exited 0). The
production interruption and subsequent fix are disclosed in the report. Copies
of the production corpus are never published; synthetic retrieval fixtures and
model revisions permit the inference tests without private retained content.

`distractor-results.json` repeats the positive controlled-source queries against
a private copied corpus of 10,188 retained passages plus the eight fixture
passages. Only controlled labels, aggregate counts and queries are published;
private distractor text and URLs are omitted. An alternative retained source may
answer a question, so a controlled-source miss is not a fully adjudicated wrong
answer. The exact private distractor snapshot is not distributed. There is no
negative-query score for this run because the broader corpus may contain answers.

Trailing whitespace in the archived pytest log is normalized; outcomes and
warning text are preserved. Original output is retained in the local work records.
