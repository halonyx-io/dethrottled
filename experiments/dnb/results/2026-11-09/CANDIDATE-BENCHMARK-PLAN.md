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

### H1. Per-render CPU overhead — improved

Observed: the candidate used ~6.8-7.2 CPU-seconds per 10 renders versus ~2.4-2.8
for 1.7.1, with similar latency. The consolidation was not the reader: direct
extraction was within 3% and the extractor was ~0.019 CPU-seconds/call. The gap
was the headed Mesa/llvmpipe browser.

Implemented: a separate headed non-GL crawl browser; `/drive` keeps the verified
Mesa/WebGL browser. Ten renders fell from **0.706 to 0.370 CPU-seconds/request**
at the same latency, with Crunchbase and drive passing. The trade is about
1.0 GiB browser memory versus 0.52 GiB. Reference remains 0.216. See
[S2-RENDERER-CPU.md](S2-RENDERER-CPU.md).

Next: H11 (browser idle/memory) and H12 (cache ceiling) before more renderer
work.

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

### H4. OCR numeric and layout accuracy — improved

Observed: both sides misread the same generated PNG token (`hotel-905` became
`hote-005`) with the warning retained.

Implemented: bounded 2x upscale for small standalone images (candidate now reads
`hotel-905`), no upscale for PDF pages already rendered at OCR DPI (the first
version regressed table rows and was fixed), and transparent PNGs composited on
a contrasting background (dark text on transparent black was empty before).
See [S3-OCR-RESOLUTION.md](S3-OCR-RESOLUTION.md).

Next: a labelled OCR set with digits, punctuation, small fonts and rotated text
to check for regressions; P0.3 adds CID-garbage PDF recovery.

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

## Prioritized backlog

Bugs and efficiency first. Exploratory work is deliberately last. The source
review is in [SIMILAR-PROJECTS-IDEAS.md](SIMILAR-PROJECTS-IDEAS.md); Hound is
`dondai1234/master-fetch` 12.4.1 and the second project is
`sweetcornna/free-search-mcp`.

| Priority | Item | Stage | Evidence / status |
|---|---|---|---|
| **P0.1** | Enforce cache expiry and a size ceiling; report cache bytes | S7, S9 | `Cache.purge()` has no callers and there is no size cap. Hound caps and evicts. |
| **P0.2** | Browser idle close plus CDP memory-pressure after fetch/drive | S8 | Ten-minute browser grew 495 -> 619 MiB; split uses ~1.0 GiB. Hound closes idle browsers and sends memory pressure. |
| **P0.3** | Detect PDF `(cid:` garbage and force OCR for the affected page | S3, S5 | No CID handling today. Hound's flagship PDF recovery. |
| **P0.4** | Audit 404/403/429/login/paywall/error pages for false `ok` | S2, S3 | Hound's universal error detection. This is a correctness bug if any such page reads as success. |
| **P0.5** | Reddit rewrite/read-path efficiency (`old.reddit.com`) | S2, S3 | No rewrite today. Hound reports a much smaller page; measure bytes/CPU and content parity. |
| **P0.6** | Measure and trim MCP tool-definition token cost | S1, S10 | Hound ships 6 tools in ~2.7K tokens; Dethrottled has 20 unmeasured tools. |
| **P1.1** | Search date provenance (`date_source`, `dated_results`, undated warning) | S6, S10 | free-search-mcp gives agents a trust signal; Dethrottled has dates but not their source. |
| **P1.2** | `source_type` / `page_type` / fetch relevance fields | S10 | Hound exposes these; derive from existing URL/extraction data, no new classifier. |
| **P1.3** | Whole-bucket decoy detection | S2, S6 | free-search-mcp's measured signal; needs a labelled query set before use. |
| **P1.4** | Query normalization for cache identity only | S2 | Hound/free-search-mcp cache normalisation; measure hit rate, never change upstream text. |
| **P1.5** | Token estimates and boundary-aware truncation | S3, S10 | free-search-mcp output shaping; keep canonical text/cache unchanged. |
| **P2.1** | Search consensus / intent fan-out | S6 | Hound; measure recall and added requests before adopting. |
| **P2.2** | Neural rerank | S6 | Hound uses an ONNX cross-encoder; Dethrottled deliberately has it off. Experiment only. |
| **P2.3** | Semantic query cache | S6 | Hound two-level cache; separate namespace, false-hit precision at 0.90-0.95. |
| **P2.4** | Persistent browser profile / stealth | S4, S8 | Hound; needs security review for cross-caller isolation. |
| **P2.5** | Proxy / BYOK key rotation | S6, S9 | Hound; keep opt-in, never a default third-party route. |

Already implemented in this cycle: P0 render CPU split, low-resolution OCR,
transparent-PNG OCR, concise empty-table metadata, news cache ceiling, and the
HTTP/MCP reference fixes. They remain in the suite as regressions.

## Execution order

1. **Close S0/S1.** Provenance and contract diff are already recorded; add the
   tool-definition token baseline (P0.6).
2. **P0 bugs/efficiency.** Cache ceiling (P0.1), browser idle/memory (P0.2),
   CID PDF OCR (P0.3), false-error-page audit (P0.4), Reddit efficiency (P0.5).
   Do these before adding any new capability.
3. **S2-S3 correctness.** Fixed corpus, paired extraction matrix, error and
   warning review. Adopt only measured fixes.
4. **S4-S6 browser, workers and corpus.** Reuse `compare.py`, `verify.py`,
   `phase5_check.py` and the existing worker lab; add only missing fixtures.
5. **S7-S8 performance and robustness.** Re-run cgroup resource benches,
   concurrency ladder, 60-minute soak and crash injection after P0.
6. **S9-S10 packaging and UX.** Clean install, stack upgrade/rollback, token
   estimates, source/date provenance and tool-definition trimming.
7. **P1/P2 exploratory work.** Only after P0/P1 correctness and efficiency are
   stable; each experiment needs its own before/after evidence.
8. **Decision round.** Rank improvements by user value, risk and measured gain;
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
