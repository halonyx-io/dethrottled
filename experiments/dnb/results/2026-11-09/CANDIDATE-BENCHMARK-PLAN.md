# 1.8.0 candidate benchmark and improvement plan

2026-11-09. Status: **candidate held**. The 1.8.0 candidate is not being
version-bumped, published or deployed. Production remains on 1.7.1.

The purpose of this plan is to compare the frozen 1.8.0 candidate with the
deployed 1.7.1 at every stage and layer, find real improvements worth making
while the candidate is still in the test bed, and reject changes that only move
a number or add complexity.

## Rules

- Production `dethrottled:local` / 1.7.1 and its volumes are never touched.
- Reference and candidate run side by side in disposable containers.
- Each comparison changes one variable. When measuring core extraction, both
  sides use the same browser and worker images. When measuring the browser, both
  call the browser service directly with the same harness.
- Controlled fixtures come first; live sources are observational and paced.
- Failures, thin content, blocked challenges and partial results are retained,
  never filtered out of the evidence.
- Every result records image IDs, commit, host, environment, command and raw
  outputs. No claim without a measurement.
- No new dependencies or system-package changes. Profiling uses the standard
  library and existing tools.
- A candidate change is not accepted without a documented before/after run and a
  rollback path.

## Measurement method

### Paired runs

For each fixed case, run reference and candidate in alternating order across
three rounds. Report per-side medians and the paired difference. Use at least:

- 30 fixed quality cases per format family.
- 50 latency samples per case family after five warm-ups.
- 3 interleaved rounds for resource measurements.
- 10-20 paced live cases per pass, with at least two passes.

Do not treat a single live request as parity or improvement evidence. Upstream
challenge state changes between requests.

### Resources

`docker stats --no-stream` is only a coarse screen. For real resource numbers:

- Read cgroup v2 `cpu.stat` (`usage_usec`) before and after a fixed batch and
  divide by completed operations.
- Record `memory.current`, `memory.peak`, process RSS and restart count.
- Measure cold start separately from warm cache.
- Keep the same host, container network, worker images, concurrency and payload
  sizes on both sides.
- Report p50/p95/p99 latency, throughput, CPU-seconds per success, peak memory
  and bytes transferred.

### Correctness

A response is `ok` only if the expected facts are present, the visible text is
not a challenge page, and the warning set matches the observed limitation. A
quality winner must not lose facts or convert a failure into false confidence.

### Change threshold

Keep a candidate change when all of these hold:

1. No correctness or contract regression on the fixed suite.
2. The primary metric improves by at least 5% with a consistent direction, or a
   defined failure mode is eliminated.
3. The improvement survives the opposite run order and a second round.
4. The added complexity and rollback cost are acceptable.

Below 5%, prefer no change unless the fix removes a real failure. Do not chase
noise.

## Test corpus

### Controlled

- `experiments/dnb/fixture.py`: article, long, tiny, redirect, blocked and
  private redirects, missing, busy, huge, ticker, mutation, state, download,
  frame, API and popup.
- Generated PDF (text, scanned, table), DOCX, XLSX, PPTX, ODT, EPUB, RTF, CSV,
  JSON, XML, PNG text, and a deterministic speech clip.
- 8 MiB+ HTML ceiling, malformed archives, wrong extensions, oversized headers,
  truncated bodies, redirect loops and invalid encodings.
- Schema-1 and schema-2 corpus volumes with fixed documents and queries.

### Live, frozen and paced

- The five-URL protocol in
  `docs/benchmarks/2026-11-01-recovery-next/live-protocol.json`: four hostile
  sources and the Python `sqlite3` control.
- A small ordinary set for trend checks: Python docs, MDN, example.com and one
  stable standards page.
- Alternate order, 6-8 second pacing, at least two passes. Record the exact
  response and timestamp.

## Stage and layer matrix

| ID | Layer | Question | Inputs | Primary metrics | Gate |
|---|---|---|---|---|---|
| S0 | Provenance | Are we comparing the intended builds? | image IDs, commit, tag | IDs, versions, env | Must match the frozen candidate and 1.7.1 |
| S1 | API/MCP contract | Do requests, errors and tool schemas match? | every endpoint and tool, valid and invalid bodies | status, error code, schema diff | No unexplained contract change |
| S2 | Acquisition ladder | Which tier wins, at what cost, and why? | controlled routes plus live protocol | success rate, tier distribution, latency, CPU/success | No allow-list widening; failures stay explicit |
| S3 | Extraction | Is the content complete, correct and warned? | generated and live documents | fact retention, chars, quality, warnings | No fact loss; intentional differences documented |
| S4 | Browser/drive | Do actions, sessions, checkpoints and concurrency behave the same? | 27-action drive suite, tabs, downloads, frames | action success, restore, isolation, latency | Same outcomes; no orphan session |
| S5 | Optional workers | Do format/media/layout add value without hiding failures? | PDF, Office, OCR, speech, layout | success, quality, worker latency, fallback | Same result; explicit worker failure |
| S6 | Corpus and search | Is retrieval better or just different? | labelled query set, schema 1 and 2 | recall@k, nDCG/MRR, index bytes, query latency | Better retrieval or lower cost without loss |
| S7 | Concurrency and resources | Where does the candidate spend extra CPU or memory? | mixed fetch/drive load at n=1,3,6 | CPU-s/op, p95, peak RSS, throughput | Explain and reduce the gap if material |
| S8 | Robustness and security | Does hostile input stay contained? | crash injection, 60-minute soak, malformed inputs | hang rate, recovery time, data preservation, peak memory | No cross-request damage; bounded memory |
| S9 | Packaging and upgrade | Does install, upgrade and rollback preserve data? | wheel/sdist, stack up/down, schema volumes | install time, readiness, rollback time, files | Clean install and clean rollback |
| S10 | Observability and UX | Can a caller tell what happened and what to do? | errors, warnings, `/v2/status`, metrics | actionability, warning precision, docs match | No misleading success |

## Improvement hypotheses to test

### H1. Per-render CPU overhead

Observed: the candidate used ~6.8-7.2 CPU-seconds per 10 renders versus ~2.4-2.8
for 1.7.1, with similar latency. The consolidation may be doing extra work or
re-parsing more than once.

Test: paired 30-render batches with the same browser and fixtures; cgroup CPU
deltas; `cProfile` on candidate extraction; per-tier breakdown. Target: at least
10% lower CPU per successful read with no fact loss. If the cost buys a
measurable quality gain, document the trade instead of hiding it.

### H2. Tier selection and headed fallback

Observed: single live passes sometimes reached a headed result where 1.7.1
returned a partial or failed direct result; repeated passes matched.

Test: fixed pages that succeed at direct, TLS, render and headed tiers; measure
tier distribution, fallback rate, time and CPU per success. Target: keep genuine
recoveries, remove avoidable headed work where direct content is already
sufficient. No change that merely increases "ok" by dropping warnings.

### H3. Concise PDF table fidelity

Observed: concise candidate output drops the raw table array and reports
`native_pdf_table_count=1`; reference keeps the table array. Content and tier
match.

Test: table-reading questions over generated and real PDFs; compare fact/cell
retrieval, bytes and readability. Target: a compact table representation only if
it improves usable information without the full array cost. Otherwise keep the
current intentional difference and document it.

### H4. OCR numeric and layout accuracy

Observed: both sides misread the same generated PNG token (`hotel-905` became
`hote-005`) with the warning retained.

Test: a labelled OCR set with digits, punctuation, small fonts and rotated text;
compare tesseract modes already installed, upscaling and crop. Target: fewer
digit errors without new hallucinations. Any gain must be measured against the
warning and confidence semantics.

### H5. Worker sizing, timeouts and failure surfacing

Test: format/media/layout at n=1,3,6; kill each worker mid-request; measure
queue time, timeout behaviour, fallback and error text. Target: bounded queue,
no hang, actionable failure. Tune defaults only with evidence.

### H6. Corpus schema 2 value

Test: a labelled query set over fixed documents; lexical versus hybrid; schema 1
versus 2; index size, build time and query latency. Target: schema 2 must earn
its extra storage and maintenance with better retrieval, or remain an explicit
opt-in.

### H7. Long-run browser memory

Observed: the browser stayed under ~0.62 GiB for ten minutes, then plateaued; a
longer leak was not proven.

Test: 60-minute mixed drive/fetch soak with periodic context close and session
churn; record `memory.peak`, RSS trend and restart count. Target: flat trend or a
documented bounded cache. Add a leak test at the first sign of monotonic growth.

### H8. ARM64 and software graphics

Observed: native ARM64 build and llvmpipe WebGL work, 29/29 focused tests pass;
no throughput comparison yet.

Test: same fixed workload on `q6a` and the AMD64 host; separate extraction from
renderer cost; measure CPU per success and p95. Target: explain architecture
differences, not assume parity.

### H9. Contract and upgrade ergonomics

Test: every REST/MCP tool with valid, missing, extra and wrong-type fields;
install 1.7.1, create schema-1 and schema-2 data, upgrade to candidate, roll back;
measure readiness and preserved files. Target: no silent schema change; error
messages say what to do; rollback documented and tested.

### H10. Warning and quality precision

Test: a labelled set of thin, blocked, challenge, partial, OCR and inferred-table
pages. Compare `quality`, warnings and suggested next action. Target: no false
`ok`; warnings name the limitation, not a generic disclaimer. This is the best
place to improve trust without adding features.

## Execution order

1. **S0-S1 provenance and contracts.** Re-record image IDs, freeze env, diff
   OpenAPI/MCP surfaces. One week of work is not needed; this is a short gate.
2. **S2-S3 acquisition and extraction.** Build the fixed corpus and paired
   harness; run the first full matrix and publish the gap list.
3. **S4-S6 browser, workers and corpus.** Reuse `compare.py`, `verify.py`,
   `phase5_check.py` and the existing worker lab; add only missing fixtures.
4. **S7-S8 performance and robustness.** Run cgroup-based resource benches,
   concurrency ladder, 60-minute soak and crash injection.
5. **S9-S10 packaging and UX.** Clean install, stack upgrade/rollback, error and
   warning review.
6. **Decision round.** Rank improvements by user value, risk and measured gain;
   implement only the accepted set, then rerun the full suite.

## Deliverables per stage

- Raw JSON/log evidence with timestamps and image IDs.
- A one-page result with the paired numbers and the decision.
- A gap list: no change, candidate fix, documentation fix, or accepted trade.
- A regression run of the full offline suite and the focused lab matrix after any
  accepted change.

## Stop conditions

- Any production impact or cross-request data leak: stop and restore 1.7.1.
- Any change that loses facts, hides a warning or widens an allow-list: reject.
- Any memory trend that keeps rising without a bound: stop the soak and open a
  containment investigation.
- Any release action: requires fresh explicit approval. This plan does not
  authorise a version bump, publish or deployment.
