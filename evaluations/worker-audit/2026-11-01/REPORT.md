# Worker and Rust audit

> Recorded evaluation of the stated versions. This is historical evidence, not
> current deployment guidance. See the [evidence index](../../../docs/EVIDENCE.md).

Recorded 1 November 2026 (Asia/Singapore). Dethrottled 0.7.0, checkout
`7991875`. This was an inspection and functional audit; production workers,
models, engine settings and package pins were not upgraded during it.

## Findings

All seven Dethrottled containers were running. Functional probes exercised
discovery, the configured SearXNG engines, JavaScript reading, HTML-to-PDF,
Docling conversion and speech transcription successfully. Both systemd public
adapters were active. Current-container restart counts were zero and their
OOMKilled flags were false; this does not establish an incident-free history.

The Ryzen 7 5800U has eight cores/16 logical CPUs and approximately 30.8 GiB RAM.
About 19 GiB was available at the idle snapshot, with roughly 78 GiB disk free.
Inference is configured for CPU. These observations do not constitute a load
or capacity benchmark. No queue saturation was observed in the browser snapshot.

| Worker | Installed / configured | Observed result | Decision |
|---|---|---|---|
| Core API and document parsers | Dethrottled 0.7.0, PyMuPDF 1.28.2, Resiliparse 1.0.9 | API healthy; 22 controlled parser checks passed in an isolated profiling run | Improve routing, limits and isolation before adding API replicas |
| Headed browser | Patchright 1.63.0; Chromium bundle `chromium-1243` | DDG Lite returned ten results in 794 ms | Keep the working path; benchmark a separate 1.64.3 candidate |
| Crawl4AI renderer | 0.9.4 | JavaScript quotes page read successfully through the API in 3,368 ms | Highest-priority software upgrade candidate: 0.9.5 |
| HTML-to-PDF worker | Crawl4AI 0.9.4 base image, custom offline Playwright renderer | Produced a 15,361-byte PDF in 404 ms | Works; this creates PDFs, it does not improve PDF ingestion; consider a smaller independent image later |
| SearXNG | 2026.10.2-19ffbcd30 | Six individual engines returned results without reported engine errors | Test a newer dated image; preserve current engine configuration |
| Docling | 2.145.0; Torch 2.10.0 CPU; OCR disabled in its pipeline | Multicolumn PDF converted through live worker in 7,689 ms | Package already current on PyPI; configuration/model coverage matters more than a version bump |
| Speech | faster-whisper 1.2.1, CTranslate2 4.8.4; Whisper `small`, CPU int8 | Actual JFK sample transcribed with timed segments in 2,211 ms | Engine versions current on PyPI; test stronger model profiles rather than adding identical replicas |

Each timing above is one observation, not a service-level guarantee or a
before/after comparison. OCR remains available in the core API: Tesseract 5.5.0
with English, Malay, simplified/traditional Chinese and orientation data.
Antiword and catppt are installed; LibreOffice is not.

The six SearXNG probes returned Mwmbl 60, Crossref 20, OpenAlex 10, arXiv 10,
DuckDuckGo News 24 and Bing News 10 results. This establishes that they answered
these queries, not that every result was relevant or coverage is exhaustive.
Google/Brave/general scraped engines remain disabled. No configuration change
is needed to preserve the good DDG Lite path. OpenAlex authentication advice
has changed over time; its [current documentation](https://help.openalex.org/api/authentication/)
permits basic anonymous queries and describes an optional free key for larger
budgets and pagination. The local OpenAlex probe succeeded without adding a key.

## Upgrade candidates

1. **Crawl4AI 0.9.4 → 0.9.5.** Upstream calls 0.9.5 a Docker-server security
   release and recommends it for self-hosted deployments. It changes request
   validation and outbound-request behavior, including selectors/waits. Test it
   against Dethrottled's exact config, public target policy, selector syntax,
   JavaScript fixtures, failed pages and existing browser fallbacks before
   updating the digest. This audit found no evidence of exploitation.
   [Official changelog](https://raw.githubusercontent.com/unclecode/crawl4ai/main/CHANGELOG.md).
2. **Patchright 1.63.0 → 1.64.3**, the version returned by PyPI's metadata during
   this audit. Rebuild the matching Chromium bundle, then test live DDG success,
   blocked pages, checkpoints, downloads, frames, popups and old operation IDs.
   A newer browser can improve compatibility but can also change detection behavior.
   Search-indexed GitHub release pages lagged PyPI; do not rely on search snippets
   alone for version selection. [Official package](https://pypi.org/project/patchright/).
3. **SearXNG dated-image refresh.** Docker Hub showed
   `2026.10.30-ffa88e3ba`, newer than the current October 2 pin. Use a verified
   digest and rerun all six engine probes plus news/academic relevance checks.
   Updating SearXNG does not make deprecated upstream engines dependable.
   [Official image tags](https://hub.docker.com/r/searxng/searxng/tags).
4. **Framework dependency refresh, with a tested lock.** Media/Docling pin FastAPI
   0.121.3 and Uvicorn 0.38.0; newer packages exist, while API/browser workers
   already use different versions. Unify the tested dependency policy, without
   changing inference libraries just to make version numbers uniform.
   PyMuPDF's latest metadata reported 2.0, a major update from 1.28.2: validate
   table geometry, page selection, OCR and citation offsets before adopting it.
   [PyMuPDF changelog](https://pymupdf.readthedocs.io/en/latest/changes.html).

## More workers: add capabilities first

**The first correction should be local rendering admission.** Runtime values
confirm 40 Crawl4AI attempts per rolling hour, 60 seconds for a single page,
25 seconds for bulk page reads, one headed read at a time and an eight-page OCR
cap. Limits and pagination protect the service, but an hourly ceiling on local
rendering can prevent coverage even while hardware is available. Prefer a bounded
queue, per-client fairness, explicit cancellation, progress and resource-based
concurrency. Slow/large sources should continue as durable jobs with page/audio
windows, not silently exhaust a generic budget. Simply setting every limit to
unbounded would not be dependable.

**Add one general document fallback worker.** Benchmark Apache Tika against a
Rust document engine on currently weak formats: Outlook MSG/attachments, XLSB,
iWork, older Office variants, nested documents and unusual encodings. Add only
observed wins to the acquisition ladder. Tika advertises broad format coverage,
but broad detection/text extraction does not establish accurate table layout.
Use a sandboxed bytes-only interface and retained source hashes, and surface
actual parser/version/partial-output metadata. A separate LibreOffice conversion
worker can be justified where preserving Office page layout or chart rendering
wins tests; it is a different capability from raw text extraction.
[Apache Tika](https://tika.apache.org/).

**Improve scanned documents and visual evidence.** The current Docling pipeline
explicitly has OCR off. Core Tesseract can recover scan text, but that is not a
structured scan/table/chart-reading system. Test OCR-enabled layout recovery and
an independent OCR backend, then optional vision escalation for chart labels,
merged cells or conflicting readings. Provide source pixels and disagreement
metadata; do not average competing numeric readings into a guessed value.
A GPU or remote inference worker could help this quality tier, but need is not
established merely by spare RAM or the existence of a bigger model.

**Improve speech quality and lifecycle.** Test `medium` and `large-v3` as optional
quality profiles on accents, languages, noise and exact numbers; preserve `small`
for suitable inputs. Measure word/number errors and false speech on silence.
Add language hints, audio windows and selected retranscription. The current
server delegates to a Python thread, with no killable process deadline: cancelled
HTTP work can outlive the request, and the admission semaphore can be released
while that thread still exists. A model lock serializes inference, but does not
solve orphaned decoding/inference work. This is a code-level lifecycle risk,
not a reproduced production incident. Use a supervised worker/job design with
real cancellation before expanding heavy concurrency.
[Supported inference model loading](https://github.com/SYSTRAN/faster-whisper).

**Add worker readiness and tracing.** Media, Docling and SearXNG have no Docker
healthcheck configured. Media's health reports whether its model is loaded;
Docling's health does not prove model availability. API status mainly checks
SearXNG/news and does not represent the full worker graph. Add startup/model
readiness, queue depth, oldest-job age, cancellations, typed failures, exact model
revision and parser versions, joined by request/job IDs. The status response's
fixed zero-API-call cost fields also need updating now optional metered discovery
exists; per-request provider diagnostics do not constitute complete usage accounting.

**Evaluate multilingual corpus retrieval.** The live corpus has 10,187 passages
from 3,603 pages and currently uses MiniLM. Its implementation explicitly traded
away cross-language retrieval after a small earlier evaluation. That is worth
revisiting for this coverage-first objective. Benchmark an optional multilingual
model on English/Chinese/Malay and cross-language queries; calibrate thresholds
and version the index rather than reusing English similarity cutoffs.
[One candidate model card](https://huggingface.co/intfloat/multilingual-e5-small).

## Where Rust helps

**The strongest Rust opportunity is an additional document engine, not a full
rewrite of the API.** Two concrete candidates are
[docling.rs](https://github.com/docling-project/docling.rs) and
[Xberg/Kreuzberg](https://github.com/xberg-io/xberg). They expose document
conversion capabilities through language bindings or services and claim broad
format support. Their self-published speed/quality results are leads for our own
bake-off, not measured Dethrottled improvements. docling.rs itself describes
remaining conformance differences, and some of its scoring uses Python Docling
output as ground truth. Keep native/Python fallbacks until source values, merged
cells, reading order, geometry and pagination are demonstrably preserved.

Rust may also suit bounded archive traversal, streaming MIME/encoding work and
large-scale deduplication if profiling shows real Python CPU/memory pressure.
It will not fix blocked search engines, missing parser support, an undersized
ASR model or a source the agent never attempts. Much current heavy computation
already runs in native libraries: MuPDF, Resiliparse, ONNX Runtime, CTranslate2
and Chromium. A small isolated profile passed 22 parser tasks, totaling about
1.01 seconds in read_blob calls (median task 1.5 ms); the whole process, including
imports and fixture construction, took about 1.69 seconds under cProfile. This is
not a large-document performance benchmark, but does not justify replacing the
whole orchestration layer merely because it is Python.

Recommended sequence: renderer maintenance and queue/readiness corrections;
then a broad-format fallback bake-off, scanned-table/vision and ASR quality tiers;
then migrate individual components only where coverage, correctness or capacity
improves on recorded tests. Add browser/renderer replicas when sustained queue
measurements justify them, not to increase the container count.

## Evidence and limits

The accompanying evidence contains selected runtime inventory (no environment
secrets), PyPI version metadata, functional probe outputs, resource snapshots,
model-worker probes, runtime limits and the small native-parser profile.
No new engines or models were installed and no load/saturation test was run.
This audit establishes health at observation time and identifies upgrade/test
priorities; it does not certify future availability or candidate upgrade quality.
