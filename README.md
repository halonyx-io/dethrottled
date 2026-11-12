# Dethrottled

<picture>
  <img src="https://raw.githubusercontent.com/halonyx-io/dethrottled/main/docs/assets/hero.svg" alt="Dethrottled: discover, read, drive and retain web evidence">
</picture>

**Dethrottled is an open source, self-hosted web retrieval and evidence engine
for AI agents, applications and automation.** It discovers sources, reads pages
and files, operates a real browser, and retains evidence for follow-up.
It returns source references, warnings and concrete continuation steps. Your agent
or application decides what the evidence supports.

The default stack needs **no API key, paid search subscription or model API**.
It runs on native AMD64 and ARM64 Docker hosts. Public sites can still block
requests; retries, queues and storage have limits. Optional paid discovery
integrations remain opt-in and are not required by the default workflow.

For a first installation or ordinary script/HTTP use, start with the
[quick start](https://github.com/halonyx-io/dethrottled/blob/main/docs/QUICKSTART.md).

Native [HaGeZi ad/tracker filtering](docs/ADBLOCK.md) is enabled by default in this
release, with one switch to disable it. Coverage and measured resource costs
are described in that guide.

## Install the complete engine

Install [Docker Engine and Compose](https://docs.docker.com/engine/install/), then:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install dethrottled
dethrottled stack up
dethrottled stack status
```

The Python distribution includes matching deployment sources: **no Git clone is
needed**. `stack up` builds/downloads the four default services (API, DNB, SearXNG and format reader) and waits for
readiness. Installing the package alone starts nothing and downloads no models.

```sh
dethrottled stack up --profile full  # add local speech and PDF layout workers
dethrottled stack down               # keep documents, cache and model volumes
```

Use `--project NAME --port PORT` for an isolated installation. Speech/layout model
weights initialize on first use; status reports this separately from readiness.
See [installation choices](https://github.com/halonyx-io/dethrottled/blob/main/docs/PYTHON.md)
and [measured requirements](https://github.com/halonyx-io/dethrottled/blob/main/docs/REQUIREMENTS.md).
Standalone Python/library use remains available, with capabilities determined by
its installed libraries, system tools and external workers.

Prefer a checkout? Both routes run the same default services:

```sh
git clone https://github.com/halonyx-io/dethrottled.git
cd dethrottled
docker compose up -d --build
```

The API listens on **`127.0.0.1:8787`**. Connect locally over REST, or configure the
optional [authenticated REST/MCP adapters](https://github.com/halonyx-io/dethrottled/blob/main/docs/PUBLIC-ACCESS.md)
for remote agents. The raw API has no caller authentication.

## Follow the evidence

| Capability | What the agent receives |
|---|---|
| Search | Compact source choices: up to ten DDG results, at most three per supplementary engine, fifteen unique URLs total |
| Read | Extracted pages, documents, tables, archives, captions and media; quality and provenance remain attached |
| Recover | Observed publisher alternatives, TLS acquisition, JavaScript rendering and scoped headed-browser interaction |
| Drive | Native controls, frames, tabs, application responses, downloads, screenshots and checkpointed sessions |
| Retain | Document IDs with text, page and table ranges; focused follow-up without fetching the source again |
| Remember | Public Corpus v2 with bounded lexical coverage, sampled semantic retrieval and explicit support/coverage metadata |
| Research | A bounded evidence bundle with explicit coverage gaps; ten sources by default, twenty on request |

<picture>
  <img src="https://raw.githubusercontent.com/halonyx-io/dethrottled/main/docs/assets/escalation.svg" alt="Automatic acquisition, assessment, recovery and agent continuation">
</picture>

A normal fetch runs the recovery policy automatically. When content remains
incomplete, `read_plan` and `workflow.next_actions` expose useful continuations,
including reuse of the same browser session. Agents can also operate `/drive`
directly. Read the [agent client playbook](https://github.com/halonyx-io/dethrottled/blob/main/docs/AGENT-PLAYBOOK.md)
for tool selection and response contracts. The repository [agent skill](SKILL-dethrottled.md)
provides an installable client workflow covering discovery, extraction, documents,
site mapping, browser control and diagnostics.

```sh
curl -sS http://127.0.0.1:8787/fetch \
  -H 'Content-Type: application/json' \
  -d '{"urls":["https://docs.python.org/3/library/sqlite3.html"],"focus":"in-memory database"}'
```

Preserve `quality`, `warnings`, `source_partial`, `truncated`, `document_id` and
continuation metadata. A successful HTTP response is not proof of a complete,
relevant or correct read. OCR and speech may need checking against source pixels
or audio. Interactive challenges can remain unresolved.

## Reuse evidence across tasks

Corpus v2 retains eligible public passages for 90 days, with bounded SQLite
lexical indexing and representative MiniLM/E5 embeddings. Indexing runs in the
background; public document handles can be reopened across agent identities.
Private/authenticated reads are excluded from automatic sharing.

Standard retrieval checks source/model corroboration or meaningful query terms.
When evidence is missing, `support="broad"` exposes additional warned candidates,
including cross-language matches. Neither mode verifies an answer. The
[controlled evaluation](https://github.com/halonyx-io/dethrottled/blob/main/evaluations/corpus-v2/results/2026-11-05/REPORT.md)
records recovered facts and the precision/coverage tradeoff. See
[Corpus operation](https://github.com/halonyx-io/dethrottled/blob/main/docs/CORPUS.md)
for budgets, retention, migration and rollback.

## Measured on two machines

The [current installation and benchmark report](https://github.com/halonyx-io/dethrottled/blob/main/evaluations/install-showcase/results/2026-11-04/REPORT.md)
compares an ARM64 edge device with an x86_64 mini PC. It preserves
installation failures and fixes, controlled browser/document checks, 50 live
search questions, 30 fixed fetch targets and six research tasks per device.
Fresh acquisition, cache-enabled repeats and optional workers are reported
separately. Every plotted value is generated from retained case data.

<picture>
  <img src="https://raw.githubusercontent.com/halonyx-io/dethrottled/main/docs/assets/hardware.svg" alt="ARM64 edge device: eight Cortex-A55/A78 cores and 11.29 GiB OS-visible RAM. x86_64 mini PC: Ryzen 7 5800U, eight cores and sixteen threads, 30.76 GiB OS-visible RAM.">
</picture>

| Recorded check | ARM64 edge device | x86_64 mini PC |
|---|---:|---:|
| Browser/document contracts, three runs | 63/63 | 63/63 |
| Controlled format fact retained, eleven fixtures × three runs | 33/33 | 33/33 |
| Worker-restart storage restoration | 3/3 | 3/3 |
| Nonempty live search menus | 50/50 | 50/50 |
| Fresh public fetches assessed `ok` | 26/30 | 27/30 |

The live `ok` label is the engine's assessment, not verified answer correctness.
The report separately records topic-marker retention, thin results and failures.

<picture>
  <img src="https://raw.githubusercontent.com/halonyx-io/dethrottled/main/docs/assets/latency.svg" alt="Measured latency on ARM64 edge device and x86_64 mini PC, including failed requests">
</picture>

These are observed workloads, not universal minimum requirements or a paid-service
superiority claim. Earlier evaluations proved native Reddit interaction and
recovery on specific pages; Crunchbase and G2 remained blocked. Current live
outcomes, historical reports and limits are linked in the
[evidence index](https://github.com/halonyx-io/dethrottled/blob/main/docs/EVIDENCE.md).
Neural live-web reranking remains disabled by default; 1.8.0 adds an opt-in Ettin reranker.

## 1.8.1 stabilization

GitHub Compose and the PyPI managed stack both build DNB from bundled source.
DNB provides browser discovery, rendering and interaction. Compose generates
a signing key in the API data volume and gives DNB the public verifier.

## Historical 1.8.0 validation

The release candidate was frozen at commit `735d420` (tag
`phase5-candidate-20261109`) and then extended with the OCR fixes and the opt-in
Ettin reranker. Candidate images are
`dethrottled-dnb:1.8.0-candidate-20261109` (`sha256:c6633da3…`) and
`dethrottled-dnb-api:1.8.0-candidate-20261109` (`sha256:bb859007…`). The
test-bed API with the OCR improvements is
`dethrottled-dnb-api:1.8.0-dev-20261109`; the frozen images were not overwritten.

| Layer | 1.8.0 result against the frozen 1.7.1 reference |
|---|---|
| Browser parity | Both sides passed 27 facts, 27 drive actions, exact download, network fact, concurrency and checkpoint restore |
| PDF concise | Same 213 content characters, `direct/direct-native`, quality `ok`; reference kept one raw table array, candidate reported `native_pdf_table_count=1` and omitted the raw array |
| Office / OCR | PDF, DOCX, XLSX and PPTX facts, quality and tier matched; the frozen baseline OCR returned the same text and warning on both sides, misreading `hotel-905` as `hote-005` (the test-bed fix below now reads it correctly) |
| Layout / mixed batch | `parser=docling`, 158 characters and the same two inference warnings; a four-file mixed batch matched |
| Media / speech | Same language `en`, duration 3.812875 s, transcript and speech-uncertainty warning; one-byte response-length difference |
| HTML ceiling | A 13.7 MB page returned HTTP 200 with `html_capture_limit`, 300 characters and no post-limit fact on both sides |
| Live / hostile | Two paced passes over the frozen five-URL protocol; controlled hostile routes matched exactly. CarGurus and Expedia remained failed on the repeated pass; no new hostile-source success is claimed |
| Neural rerank | Opt-in Ettin 68M fp32: 0.7930 nDCG@10 / 0.7699 MRR@10 over 100 SciFact queries versus 0.7222/0.6913 for source order; no default change |
| ARM64 | Native build on `q6a` (aarch64, Docker 29.9.3), reference `sha256:b9e0fe2a…`, candidate `sha256:9fb7c41b…`; llvmpipe WebGL, real crawl fact retained, 29/29 focused tests |
| Packaging / install | Wheel and sdist built, `twine check` and `scripts/verify_stack_package.py` passed (979 context files, 56 copy sources); the 1.8.0 wheel installed in a clean venv and both CLI entry points ran, while the 1.7.1 PyPI/GitHub routes remain available for rollback |
| Mixed load | 3-minute run: reference 859 requests / 0 failures / 20 ms median; candidate 829 / 0 / 20 ms |
| Soak / crash | 10-minute API memory flat at ~238 MiB, browser 495-619 MiB without restart; injected browser kill caused 33/333 drive requests to fail explicitly while 999/999 fetches succeeded, API stayed healthy, recovery took 4.3 s |
| Rollback | Marker and legacy databases survived reference → candidate → reference; candidate read the reference cache, schema 2 created `corpus-v2.sqlite` alongside `corpus.sqlite`, and 1.7.1 read it after rollback |
| Offline suite | 915 passed, 139 skipped, 2 deselected on the host; 1,066 passed, 15 skipped, 2 deselected in the candidate API image |

Known differences and limits: the concise PDF table change is an intentional
presentation change, not a capability loss. On the first live pass the candidate
returned a readable Crunchbase/Expedia result where 1.7.1 returned a partial or
failed result; the reversed second pass matched, so this is recorded as
upstream/order variability rather than a claimed improvement. The frozen baseline OCR was identical but wrong on one generated token; the
test-bed fix now reads it, and the warning remains. ARM64
used software rendering, not verified hardware acceleration. Package metadata
and the Compose user agent are 1.8.0.

The candidate uses roughly 6.8-7.2 CPU-seconds per 10 renders versus 2.4-2.8 for
1.7.1 at similar latency; this is a measured target for improvement, not a
speedup claim. Controlled direct extraction is within 3% (0.803 versus 0.780
CPU-seconds per request) and the extraction worker itself is about 0.019
CPU-seconds per request, so the renderer, not the reader, owns that gap. A
separate headed non-GL crawl browser cut render CPU from 0.706 to 0.370
CPU-seconds per request at the same latency, while drive keeps verified WebGL and
Crunchbase still reads; browser memory rises from about 0.52 to 1.0 GiB.

Test-bed improvements after the freeze are tracked in
[CANDIDATE-CHANGES.md](https://github.com/halonyx-io/dethrottled/blob/main/experiments/dnb/results/2026-11-09/CANDIDATE-CHANGES.md).
The first one recovers low-resolution OCR digits (`hotel-905`, reference read
`hote-005`) with a bounded 2x upscale for standalone images; PDF page rasters
keep their existing OCR-DPI resolution. The frozen images were not overwritten.
P0 test-bed hardening now also enforces cache expiry/size, closes the idle crawl
browser, adds CID-corrupted PDF OCR, warns on long login/paywall/access-denied
pages, and offers a six-tool MCP profile. P1 adds date/source/page signals,
fetch relevance, decoy-bucket filtering, normalized search cache identity, token
estimates and boundary-aware truncation. See
[P0-BUGS-EFFICIENCY.md](https://github.com/halonyx-io/dethrottled/blob/main/experiments/dnb/results/2026-11-09/P0-BUGS-EFFICIENCY.md)
and [P1-AGENT-SIGNALS.md](https://github.com/halonyx-io/dethrottled/blob/main/experiments/dnb/results/2026-11-09/P1-AGENT-SIGNALS.md).
P2 keeps search fan-out, neural rerank, semantic cache, persistent search
profiles and provider key/proxy rotation opt-in. The 1.8.0 prototype supports one
neural reranker, Ettin 68M fp32, at 512 tokens, title+text up to 3,000
characters and the top 30 candidates. On 100 SciFact queries it reached 0.7930
nDCG@10 and 0.7699 MRR@10 versus 0.7222/0.6913 for source order, but it remains
opt-in. Results are in
[P2-EXPLORATORY.md](https://github.com/halonyx-io/dethrottled/blob/main/experiments/dnb/results/2026-11-09/P2-EXPLORATORY.md).
The full record is in [PHASE-6.md](https://github.com/halonyx-io/dethrottled/blob/main/experiments/dnb/results/2026-11-09/PHASE-6.md),
and the next layer-by-layer comparison is in
[CANDIDATE-BENCHMARK-PLAN.md](https://github.com/halonyx-io/dethrottled/blob/main/experiments/dnb/results/2026-11-09/CANDIDATE-BENCHMARK-PLAN.md).
No release or deployment happens without fresh approval.

## Explore the engine

| Guide | Purpose |
|---|---|
| [Documentation home](https://github.com/halonyx-io/dethrottled/blob/main/docs/README.md) | Find the right integration or operations guide |
| [Architecture](https://github.com/halonyx-io/dethrottled/blob/main/docs/PIPELINE.md) | Service boundaries, search, reading, research and corpus |
| [HTTP API](https://github.com/halonyx-io/dethrottled/blob/main/docs/API.md) | Routes, examples and generated request reference |
| [Browser operation](https://github.com/halonyx-io/dethrottled/blob/main/docs/DRIVE.md) | Actions, scope, sessions, checkpoints and downloads |
| [Requirements and measurements](https://github.com/halonyx-io/dethrottled/blob/main/docs/REQUIREMENTS.md) | Tested hardware, memory, disk and optional-profile costs |
| [Configuration](https://github.com/halonyx-io/dethrottled/blob/main/docs/CONFIGURATION.md) | Workers, models, profiles and workload controls |
| [Operations](https://github.com/halonyx-io/dethrottled/blob/main/docs/OPERATIONS.md) | Updates, backups, verification and remote deployment |

The default API image includes native document readers, Tesseract and MiniLM/E5
corpus models. Mutable evidence, jobs, cache and corpus use a named data volume;
browser checkpoints and optional model caches have their own volumes. GPU access
is optional. No `.env` file or worker URL is required for the default stack.

The fetch ladder does not consult `robots.txt`. Raw API access to trusted LAN
targets requires care; public adapters enforce narrower policies, alongside
operator-provided network isolation. See [operations](https://github.com/halonyx-io/dethrottled/blob/main/docs/OPERATIONS.md).

This checkout is **1.8.1**. Check `/health` and `/v2/capabilities` on the service you
actually use; deployed services and remote plugins can differ from a checkout.

[MIT license](https://github.com/halonyx-io/dethrottled/blob/main/LICENSE) · Maintained by [Halonyx](https://github.com/halonyx-io)
