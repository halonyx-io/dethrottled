# Dethrottled 0.6.0: six agent upgrades, implemented and tested

1 November 2026, Singapore time. Deployed to the existing service and public
`https://api.halonyx.io/mcp`. This is an initial concrete implementation across all
six roadmap areas, not completion of every possible feature in those categories.

## What changed and why

| Area | Implemented behavior | Evidence |
|---|---|---|
| Actual client compatibility | A reproducible real MCP Python SDK probe records handshake, schemas, workflow hash, fetch, inspection and document reopening. Capabilities publish which fields clients must preserve. | Complete public SDK workflows on Python HTML documentation and a W3C PDF; SDK 1.28.1. |
| Structured, citable evidence | New inspect_document tool returns headings/paragraphs/table rows with exact retained-text quotes, Unicode offsets, document hashes and citation selectors. PDF metadata includes bounded text-layer boxes in source page coordinates. | Exact Unicode slice/hash tests, a PDF geometry test and a fresh agent returning the correct sentence interval [0,45) with its version hash. |
| Stronger browser access | drive can list observed same-host XHR/fetch responses and read a body using a stable response_id. Captured bodies receive document handles. Checkpoint explicitly saves login state. | Real Chromium login, hidden JSON value 7341, retained response reopening, cookie/localStorage restoration after process restart. |
| Durable work and deployment | Read-job payloads persist separately from the existing jobs table. resume_fetch_job fetches missing positions while retaining committed results. Browser operation outcomes persist for 24 hours. Optional Compose services package MCP/REST adapters and local speech. | Restart/resume and namespace tests; cancellation/resumption fences stale in-flight results; completed browser operations replay and unknown outcomes remain blocked. All four image types built; adapter containers served a real SDK workflow. |
| Site coverage | New crawl_site follows same-origin links/sitemaps within bounds, retains evidence and reports success/failure, duplicates, pending frontier and continuation URLs. | Three linked fixture sources read, cycle/failure/depth/sitemap tests, public Python-documentation traversal, fresh-agent multi-page task. |
| Timed media | Fetch reads VTT/SRT cues with times; YouTube metadata retains available cue timing. An optional private faster-whisper worker reads direct audio/video files using local CPU inference. | Real 11-second speech sample transcribed with timed output, API and public MCP ingestion, silence producing no transcript, malformed input and video without audio returning 422. |

These capabilities are presented in MCP initialization, tool descriptions,
capabilities and relevant result follow-ups. Agents can choose them autonomously;
the preferred workflow still allows shortcuts and explicit endpoint control.
Existing search/fetch/research/browser tools remain available. MCP now exposes
**20 tools**, including inspect_document, crawl_site and resume_fetch_job.

## What a cold agent actually did

Three new conversations used deepseek-v4.1-flash:cloud through the existing Ollama
service. Each received the task, the normal published MCP instructions and tool
schemas. The task did not prescribe a tool name or give expected values.

| Task | Observed behavior | Required-answer review |
|---|---|---|
| Discover all reports linked beneath an index | Used fetch, links, crawl_site and inspect_document; reported ALPHA 7341 crates and BETA 291 tonnes and disclosed link-scoped coverage. | Correct required facts and coverage caveat; seven calls. |
| Read a caption with its supporting interval | Used fetch then inspect_document; returned 7341 crates at 5.0–7.5 seconds. | Correct; two calls. |
| Give an exact quote, positions and version | Used fetch then inspect_document; correctly calculated the sentence interval [0,45) within the returned block and disclosed that calculation. | Correct quote, positions and document hash; two calls. |

This is **3/3 author-reviewed required-answer completions on three synthetic
tasks**, with fresh conversations but potentially warm source caches. It is not
a baseline comparison, unseen-task holdout, multi-model study or general accuracy
estimate. The full prompts, published contracts, calls, results and final answers
are preserved. Provider private reasoning and credentials are excluded.

Core correctness does not validate every incidental sentence. The site response
overstated the absence of headings/metadata beyond what extracted text established.
The agent also made redundant calls before using site traversal. Those limitations
remain visible in the transcripts rather than being edited out. The earlier 44
conversations for 0.5.0 remain a separate evidence set, not new 0.6.0 trials.

## A relevant gateway problem was found and fixed

A late repeated public run reproduced slow control calls: tools/list and
capabilities took about **4.4 seconds**, and a REST read returned **503
admission_unavailable**. These control calls do not require a search engine.
The failed responses and correlation IDs are retained.

Inspection found synchronous admission-database work in the async gateway request
path. Opening and closing the last SQLite connection repeatedly forced WAL
checkpoint/disk work. Host sampling also showed substantial I/O wait. This is a
concrete local bottleneck and a plausible contributor to the reported variance;
it does not establish the cause of every historical request from Lumina's network.

The fix moves registry/admission/release work to threads, retains a WAL connection,
and uses NORMAL synchronization for ephemeral admission state. Atomic transactions
still enforce shared quotas; authentication and namespace isolation remain in place.
Cancellation releases a lease created by an already-running admission thread.
Evidence and job databases retain their existing durability settings. Ephemeral
admission counters can lose recent state on host power failure; they are not the
durable evidence store.

In 12 alternating local acquire/release trials per arm, baseline median was
**108.1 ms**, candidate median **7.5 ms**; maxima were 202.9 and 32.0 ms. This is a
small same-host admission microbenchmark, not an end-to-end percentile or a claim
that all remote requests become 14 times faster.

The final public smoke then completed all assertions:

| Operation | Wall time |
|---|---:|
| Initialize / tools list / capabilities | 115 / 83 / 112 ms |
| Inspect retained evidence | 241 ms |
| Read an MCP-created document through REST | 82 ms |
| Site traversal, one-page bounded probe | 760 ms |
| Fresh search | 693 ms |
| Fresh audio ingestion/transcription | 3.27 s |
| Browser checkpoint / close | 1,083 / 110 ms |

Recorded admission durations for final public calls ranged from 0.57 to 12.05 ms.
Server-Timing now exposes that duration alongside X-Request-ID; CF-Ray is recorded
when present. Measurements originate here and traverse the public internet route;
they do not reproduce Lumina's client network. The initial public audio test took
21.2 seconds including cold worker/model activity; a warm cached response took
153 ms. These are different acquisition conditions, not comparable speed claims.

## Validation and deployment state

- **510 regression tests passed**, 15 skipped, two network-marked tests deselected.
  Ruff and diff checks passed. Separate real-network/browser/audio/SDK checks are
  recorded rather than counted as unit tests.
- The headed browser search path still returned **10 results with DDG Lite as the
  winner** after the browser upgrade. Existing DDG/SearXNG/renderer/ranking settings
  were preserved.
- The real browser restart test covers stable response IDs, login cookies, local
  storage, completed-operation replay, unknown-outcome refusal and checkpoint deletion.
- Public workflow hashes agree between initialization and capabilities. MCP-created
  evidence reopens through REST using the same credential. This tests actual adapter
  interoperability, not just schema inspection.
- Runtime source hashes were checked against the checkout for API modules, browser,
  media worker, public adapters and shared admission code. Test-only fixture access
  exceptions were confined to isolated wrappers and were not deployed.
- The protected pre-upgrade backup is recorded in deployment.json. Previous API and
  browser images are retained for rollback. The production token registry is unchanged.
  The only existing environment-field change enables the local media-worker URL.
  New named volumes retain browser state and speech weights; the existing data volume
  continues holding evidence/jobs/corpus/cache.
- Existing systemd public adapters remain in use. The optional containerized adapters
  provide a portable deployment path without replacing this host's Caddy arrangement.

A stale X-server lock prevented an early browser restart; startup now removes stale
container-local lock/socket files, and restart verification passed. Harness/setup
failures included an initial missing MCP Accept header and a request during service
restart returning 502; readiness checks and corrected harness requests preceded final
successful runs. The meaningful admission failure is preserved separately.

## What remains limited

This does **not** establish that Dethrottled reads every source or file format.
Site traversal can miss unlinked and JS-only sources and always leaves whole-site
completeness unknown. Network body reads currently require a declared Content-Length
at most 2 MB; chunked responses need another path. Checkpoints retain cookies and
localStorage, not IndexedDB/sessionStorage/live DOM/sockets, and expire after 24 hours.
Unknown browser outcomes are fenced for the journal's 24-hour retention window.

Citation offsets identify retained extracted text, not original HTML bytes. Returned
table-row ordinals are not physical source-row claims. PDF boxes are bounded text-layer
geometry, not reconstructed tables or OCR alignment. Speech recognition can mishear
or hallucinate; video ingestion covers audio, not visual frames or speaker identity.
Blocked YouTube captions still require an obtainable caption/media source.

Lumina's actual remote plugin revision, execute signatures and metadata forwarding
remain unverified. Server and SDK success cannot certify that wrapper. The next
useful external validation is a proven-current remote plugin running these same
tasks, followed by a declared real-world, multi-model accuracy/coverage evaluation.

## Evidence and references

The accompanying data directory and evidence.zip retain test logs, original public
requests/responses and selected safe headers, successful and failed public runs,
SDK traces, Chromium restart evidence, real-audio/negative tests, three agent
conversations, fixtures, review notes and runtime provenance. Bearer tokens, token
registries, environment files and provider private reasoning are not included.
Temporary document IDs are test evidence, not durable public download links.
Nothing was pushed or published to GitHub.

Implementation references: [Playwright network](https://playwright.dev/python/docs/network),
[Playwright authentication state](https://playwright.dev/python/docs/auth),
[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk),
[faster-whisper](https://github.com/SYSTRAN/faster-whisper).
