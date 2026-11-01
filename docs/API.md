# Local HTTP API

Base URL in the default Compose deployment: `http://127.0.0.1:8787`.
FastAPI also serves `/openapi.json` and `/docs`. These are the **raw local API**
routes, not a promise about which routes a public gateway exposes. The raw API
does not require or check a bearer token.

All POST bodies below are JSON. Unknown body fields are rejected with 422. A
fetch failure normally appears as a row with `quality: "failed"`, not an HTTP
error for the whole batch. A search that finds nothing returns `[]`.

## Route map

| Route | Purpose |
| --- | --- |
| `POST /v2/search` | Search with diagnostics even for empty results |
| `POST /search` | Discover and order URLs; no page bodies are fetched |
| `POST /fetch` | Read one or more URLs and extract content |
| `POST /extract` | Alias for `/fetch` |
| `POST /extract-with-links` | `/fetch` with links retained |
| `POST /search-and-fetch` | Search, rank, then read selected URLs |
| `POST /search-and-extract` | Alias for `/search-and-fetch` |
| `POST /research` | Collect a cited evidence bundle without generating an answer |
| `POST /drive` | Run bounded browser actions, optionally in a reusable session |
| `GET /corpus/search` | Search locally stored extracted passages |
| `GET /corpus/stats` | Count locally stored corpus material |
| `GET /health` | Process liveness |
| `GET /ready` | Search-source readiness report |
| `GET /v2/status` | Configured components, providers, and profiles |
| `GET /v2/capabilities` | Installed/configured capabilities and read formats |
| `GET /stats` | Cache, tier, budget, and domain-health counters |

## Search

```sh
curl -sS http://127.0.0.1:8787/search \
  -H 'content-type: application/json' \
  -d '{"query":"Python 3.12 documentation","limit":3}'
```

`query` is required. Result count defaults to 8; `limit` takes precedence over
the older `max_items` and `num_results` names. `categories: "news"` interleaves
web and news results. `language` is a SearXNG hint, not a strict filter.
`fresh: true` refreshes the cache and replaces stored results. `cache_mode`
is `use` (default), `refresh`, or `bypass` (neither read nor write); `max_age`
sets the maximum acceptable cache age in seconds.

`profile` selects `web` (default), `fast` (web), `balanced` (web/news),
`news` (web/news), `thorough` (web/Mwmbl), or `academic`
(web/Crossref/OpenAlex/arXiv). Explicit comma-separated `engines` overrides
that selection: `web`, `news`, `mwmbl`, `crossref`, `openalex`, `arxiv`.
Optional `exa`, `tavily`, and `parallel` sources require server-side keys and
explicit selection; default profiles never call those metered providers.
Capabilities reports their configuration, and attempts report individual failures.
Legacy `engines: "auto"` selects web. News is no longer fetched for every
ordinary web query. `site:` and `-site:` constraints apply after all merges.

Source order is retained by default. `rank: true` or `ranking: "bm25"`
uses title/snippet lexical ranking; `ranking: "fusion"` combines source and
lexical order. `prefer_domains` is an explicit list of preferred hosts.
`corpus` adds up to 20 already-fetched passages; `0` disables the merge.
`recency` is bounded to 0–1. `rerank: true` is rejected: neural reranking
remains disabled because the local evaluation did not show a quality gain.
Search limits are 1–10; invalid controls receive 422.

Version 0.7 adds `document_mode=auto|native|layout` on PDF fetches, retained
document reparsing, and fetch jobs; structured cells and page boxes are available
through `inspect_document`. Research defaults to thorough discovery and returns
`coverage.facets` with unread sources, failed reads and suggested follow-ups.
Those retrieval/lexical states never verify an answer. See
[coverage and document workflows](DEPENDABLE-WORKFLOWS.md) for bounds and examples.

The response is an array of rows with `url`, `title`, `snippet`,
`publishedDate`, `engine`, `from_corpus`, and related metadata. The **first**
row carries `search_attempts`, `search_elapsed_ms`, and `ranking` telemetry.
Use `POST /v2/search` with the same body for an envelope with `results`,
`attempts`, `status`, and `elapsed_ms`, including when no results survive.
An HTTP 200 alone does not prove that a source supplied useful results.

## Fetch and extraction

```sh
curl -sS http://127.0.0.1:8787/fetch \
  -H 'content-type: application/json' \
  -d '{"urls":["https://example.com/"],"format":"text"}'
```

`urls` holds 1–10 URLs. `format` is `text` (default), `links`, or `html`.
`max_chars` defaults to 8000. `render` is `auto` (escalate when needed),
`always` (try the renderer first), or `never` (skip rendering). Boolean
`true` and `false` are accepted as older aliases for `always` and `auto`.
`fresh: true` refreshes and replaces the extraction cache; `cache_mode` and
`max_age` have the same semantics as search. Older `raw` and `links` booleans
are accepted; `format` takes precedence when set to `links` or `html`.

Successful rows have `quality: "ok"`, `content`, `content_type`, `tier`,
`cached`, and possibly `title` and `published`. The `tier` value identifies the
fetch and extraction path, such as `direct/trafilatura` or
`crawl4ai/crawl4ai-native`. Failed rows have `quality: "failed"`, empty
`content`, and `failure_reason`. Check these fields; a response status of 200
does not mean every URL was read. Fetch may return a short best-available
result when every tier yields only thin content.

Successful rows also report `retrieved_at`, `cache_age_seconds`, `content_chars`,
`truncated`, `content_status`, `assets`, and `warnings` when available. HTML and
prose fields each obey `max_chars`. Small valid pages can succeed without
meeting an article-length threshold. Image-based timetables expose their asset
URLs and a warning; these are not reliable OCR transcriptions.

`wait_for` is a CSS selector for Crawl4AI readiness; `render_delay` is 0–5
seconds (default 0.5). `headed_fallback: true` permits an ephemeral read through
the existing headed browser after the headless tier fails. It is opt-in.
The raw API permits trusted LAN targets. Public adapters set `public_only`
and validate redirects; headed public sessions also filter subrequests. These
checks do not provide complete renderer network isolation or DNS pinning.

The API reads HTML; PDF (with OCR available for scans); XLSX/XLS; CSV/TSV;
DOCX/PPTX; ODT/ODS/ODP; EPUB; and RTF when the relevant dependencies are
installed. The image includes those dependencies. Legacy `.doc` and `.ppt`
are detected but not parsed. CSV/TSV lack a dependable binary signature and
need a URL or content-type hint. YouTube video URLs use available captions;
this does not transcribe audio and a remote block or absent caption is reported
as failure. Check `/v2/capabilities` on the running installation.

## Search and fetch

```sh
curl -sS http://127.0.0.1:8787/search-and-fetch \
  -H 'content-type: application/json' \
  -d '{"query":"Python 3.12 release notes","limit":3,"rank":true}'
```

This accepts search fields plus `render`, `raw`, and `max_chars` (default 3000).
It orders results before reading them and returns an array combining search
metadata with fetch fields. Selected scanned sources can use OCR by default; set `ocr_mode: "never"`
when OCR is unwanted. Use `/fetch` for specific page/row ranges. Page reads use a shared worker pool and preserve
row order in the response.

## Research evidence bundle

```sh
curl -sS http://127.0.0.1:8787/research \
  -H 'content-type: application/json' \
  -d '{"question":"What changed in Python 3.12?","max_sources":4}'
```

`question` is required (3–500 characters). Optional `queries` holds up to
three search facets; the question is searched as well, for at most four total
queries. Without facets, Dethrottled adds an `official source` probe.
`max_sources` is 1–6 (default 6), `max_chars` 500–6000 (default 5000).
`fresh`, `language`, and `categories: "news"` are also accepted.

The response has `question`, per-query `queries` telemetry, `sources`,
`skipped`, and `summary`. Each accepted source gets an `id` such as `S1`, its
URL and extracted content, and selected `evidence` windows with offsets and matched terms. Passage
selection examines the full bounded extraction before applying `max_chars`;
`offset_in: "full_extraction"` identifies the offset coordinate system. It favors diverse hosts, rejects private/local source targets,
and removes near-duplicate content. `summary.model_used` is `false`: no prose
answer or citations are invented by a model. At most two research requests run
at once; excess requests receive HTTP 429. Invalid research input receives
HTTP 422.

## Browser drive

`/drive` gives an agent a bounded browser primitive without exposing arbitrary
JavaScript evaluation. Prefer `snapshot`, `text`, `attr`, and event telemetry
for navigation; inspect source pixels whenever layout, charts, or OCR uncertainty
could change the answer.
See [DRIVE.md](DRIVE.md) for the recommended agent loop and complete action
reference.

```sh
curl -sS http://127.0.0.1:8787/drive \
  -H 'content-type: application/json' \
  -d '{
    "session":"airtable-check",
    "url":"https://staging.airtable.com/",
    "allowed_hosts":["staging.airtable.com"],
    "screenshot":"canary",
    "canaries":["DRIVE_CANARY_7f13"],
    "steps":[
      {"action":"snapshot","limit":100},
      {"action":"fill","selector":"input[name=q]","value":"test"},
      {"action":"press","selector":"input[name=q]","value":"Enter"},
      {"action":"wait_for","selector":"main"},
      {"action":"text","selector":"main","limit":200}
    ]
  }'
```

Supported actions are `goto`, `click`, `fill`, `type`, `press`, `select`,
`check`, `uncheck`, `hover`, `wait`, `wait_for`, `text`, `html`, `attr`,
`count`, `snapshot`, `url`, `title`, and `download`. Each response records per-step timing,
the final URL and title, failed requests, HTTP errors, console messages, page
errors, and automatically dismissed dialogs. A matched canary is returned in
`canary_matches`; matches in dialogs, console output, or page errors are marked
as execution signals.

On `click`, `html`, or `snapshot` failure, the step can include structured
`diagnostics`. Click timeouts classify hidden, unstable, covered,
out-of-viewport, disabled, detached, and malformed-selector failures and report
the timeout stage, geometry, hit-test target, pointer-events value, and bounded
browser error. For `snapshot`, a supplied selector is a scope: the response
includes that visible node and its visible interactive descendants.

`fill` follows the browser-native value path, emits `input`, and then explicitly
emits `change`, so React-controlled inputs and commit-on-change forms observe
the update in the same step.

Set `session` to reuse cookies, storage, tabs, and DOM state between calls.
Named sessions are serialized, kept only in worker memory, and expire after 30
minutes by default; the default limit is eight live sessions. Send
`{"session":"airtable-check","close_session":true,"steps":[]}` to release
one immediately. If a navigation omits `session`, Dethrottled creates a
persistent `auto-*` session and returns its ID in `session.id`; reuse that ID
for follow-up inspection and interaction. A stateful request such as
`snapshot` without a session or navigation returns `422`. Set
`"close_session":true` on an unnamed navigation to make it a one-shot request.
Auto-created sessions are evicted before explicitly named sessions if the
session pool fills. An unknown, expired, or evicted session ID returns `409`
for a stateful call instead of creating a blank replacement context.

`screenshot` accepts `never`, `failure` (default), `canary`, or `always`.
Legacy booleans map to `always` and `never`. Screenshots are returned as base64
PNG. `allowed_hosts` restricts top-level navigation for a session and should be
set for autonomous work; subdomains of an allowed host are included. A named
session's allowlist cannot be changed while it is live. `timeout_ms` bounds the
whole run, and each step can set a smaller `timeout_ms` and `delay_ms`.

The local API has no authentication and `/drive` controls a real browser. Keep
it on a trusted network or place an authenticated, policy-enforcing gateway in
front of it. Target allowlists and programme authorization still belong to the
calling agent; this endpoint does not decide whether a target is in scope.

## Corpus and diagnostics

```sh
curl -G http://127.0.0.1:8787/corpus/search \
  --data-urlencode 'q=Python 3.12' --data-urlencode 'limit=5'
curl http://127.0.0.1:8787/corpus/stats
curl http://127.0.0.1:8787/stats
```

`/corpus/search` does not fetch the web. `mode` is `auto` (default),
`semantic`, or `lexical`. Auto uses lexical FTS for opaque identifiers rather
than returning unrelated semantic neighbors. Only canonical prose is indexed;
HTML/link representations do not replace it. Its optional `floor` overrides the
default semantic relevance floor for that call. A successful response has
`ok`, `count`, and `results`; an internal corpus error is reported with
`ok: false` and `reason` in the JSON body. `/health` is liveness; use
`/ready`, `/v2/status`, `/v2/capabilities`, and real queries to judge whether
the configured pipeline is serving useful results.

## Coverage and agent reads in 0.4

`/fetch` now supports `focus` for a question about a known URL. It examines the
retained extraction before selecting returned passages. Successful reads return
`document_id`, `document_sha256`, `document_chars` and `document_expires_at`.
`POST /documents/read` accepts that ID plus `focus`, or `offset` and `max_chars`.
`next_offset` continues a sequential read. Retained text is versioned and scoped;
it does not assert that the current website is unchanged. Re-fetch with the
appropriate freshness policy when current information matters.

The default retained extraction ceiling is 1,000,000 characters. Individual
responses still obey their requested cap. Existing extraction-cache entries are
lazily refreshed for the new representation/provenance schema. Full source files
are not retained by the document-text store. Its retention is up to seven days,
subject to a 200 MB storage budget and earlier eviction.

Explicit rendered/readiness requests reject incompatible cached extractions.
`page_start` and `page_end` select a PDF range of at most 100 pages. Extraction
reports page numbers, total pages, OCR/native method, next_page and partial
coverage. `ocr_mode` is `auto`, `always`, or `never`: always renders PDF pages
for OCR and keeps native text too; never forbids OCR. `ocr_language` selects
installed Tesseract data, such as eng, msa, chi_sim or chi_tra. Confidence values
are OCR word scores, not probabilities that a fact or table is correct.

Additional formats include plain text/Markdown, JSON/JSONL, XML (including SVG
text/data), EML, ZIP/TAR/GZIP, raster images through OCR, and legacy DOC/PPT when
local converters are installed. Native OOXML/OpenDocument/EPUB readers remain;
embedded raster images can also be OCRed, with explicit caps and provenance.
XLSX cached values are preferred; an uncached formula is returned as a formula,
never silently turned into a missing numeric result. EPUB short chapters follow
spine order and no longer depend on article-length heuristics.

For archives, inspect member names, skipped_members and partial. Files are read
without extracting archive paths to disk; expansion, nesting and member counts
are bounded. Unsupported/encrypted files fail explicitly. Image OCR and SVG XML
are not reliable reconstructions of visual charts or table relationships.

`response_format: "concise"` is optional on fetch, research and document reads.
It removes duplicate representations: HTML source appears once, and evidence
can refer to source-content ranges. Detailed remains the default. Source and
text hashes, extraction warnings and source_partial help distinguish a successful
read from complete source coverage.

## Progressive read jobs

`POST /jobs/fetch` accepts fetch controls plus an optional `operation_id`.
`POST /jobs/read` takes `job_id` and `cursor`; consume results and reuse
`next_cursor`, respecting `poll_after_ms`. Results arrive in completion order;
`source_index` maps them to the original URL list. Continue polling for full
coverage even if an early source already appears useful.

Identical submissions with the same operation ID and identity reuse the job;
changed payloads conflict with 409. `POST /jobs/cancel` stops scheduling new
work. In-flight HTTP, renderer and OCR work may still finish. Jobs persist across
client disconnects; a server restart marks unfinished jobs interrupted while
keeping completed rows. Resubmit remaining URLs explicitly after interruption.

Results are scoped by caller and retained for up to 24 hours, with a 200 MB
storage budget that can evict older terminal jobs. Defaults permit two active
jobs per identity and four globally. These are workload limits, not paid quotas.
Public wrappers inject identity; caller-provided namespaces cannot override it.

## Browser target hints, downloads and retry behavior

Snapshots now include semantic selector hints, implicit roles and ambiguity
counts/indexes for supported controls. Existing CSS, XPath and role selectors
remain available. Duplicate labels require contextual inspection or scoping.
Text/HTML steps accept `max_chars` and report content_chars/truncated; default
limits preserve existing behavior.

A `download` step clicks its selector and waits for an actual browser download,
including a browser-generated blob. The worker monitors a 32 MB download budget;
the API parses the file using the same format readers and returns source text,
filename, source/file hashes, warnings and a document handle. Binary transport
is private between worker and API. Closing the browser session removes its
browser files; retained extracted text remains accessible until expiry/eviction.

An explicit named session plus `operation_id` enables replay of an identical
completed drive request within the live worker. Changed payloads conflict;
in-progress/unknown outcomes must be inspected rather than blindly retried.
The bounded journal is in memory and does not survive worker restart. Very large
responses can preserve the known outcome without retaining replayable evidence.
This is not an exactly-once guarantee across process crashes or external systems.

### Spreadsheet and CSV ranges

Use `sheet` for XLS/XLSX and `row_start`/`row_end` for CSV/XLS/XLSX. Row numbers
are physical, one-based source positions, including any header row. A request
selects at most 2,000 rows; `extraction.tables[].next_row` continues the source.
A later range includes source row 1 as explicitly labeled context. Sheet names,
returned rows, physical extent and partial flags remain visible. Worksheet
extent can include formatted/empty rows; it is not a count of nonempty records.

Empty cells are preserved between explicit table boundaries. Pipe characters
and ampersands inside cells use reversible HTML entity escapes. The default
cell cap is 32,767 characters; `max_cell_chars` can request up to one million.
Truncated cells set partial/truncated_cells, so the agent can request a larger
cell budget instead of accepting a silently shortened value. Range selection
rejects non-table formats rather than claiming to have applied an ignored option.

Retained browser downloads also preserve source bytes (up to the download cap)
in a separate scoped 200 MB artifact budget. `/documents/read` can reparse a
download with PDF page/OCR or table row/sheet controls without another export.
HTTP reads initially retain extracted text. A later reparse or image inspection
can reacquire source bytes on demand when their hash matches the retained version.
Unavailable bytes return 410; a changed source returns 409.

`POST /documents/image` returns a PNG rendering of a retained PDF page or raster
image, with the source-file hash, page number, original/output sizes and optional
crop. PDF coordinates use a 200-DPI rendered image. The MCP `view_document_image`
tool returns native image content, so vision-capable agents can inspect charts
and check OCR rather than trusting numeric transcriptions. Crops refer to the
original pixels before scaling. These views use retained or freshly hash-verified
source bytes and preserve caller isolation.

Browser captures remain available for image inspection even when text conversion
fails. Check capture_succeeded separately from the step's parse status. File
versions with identical extracted text still receive different document handles
when their source-file hashes differ. The text hash remains a hash of the
returned retained text, not the original binary artifact.

## Evidence-led agent workflow (0.5)

MCP `initialize` publishes the service workflow; clients should forward its
`instructions` to their model along with the tool descriptions and input schemas.
REST clients can read the same policy from `/v2/capabilities.workflow`. A client
that lists tools but drops both descriptions and instructions loses this guidance.

Known URLs can go directly to `fetch`, preferably with `focus` set to the question.
Discovery can use `search` or `research`; corpus lookup is optional. Reading
performs normal transport/format/OCR escalation. Default `recovery: "auto"` adds
one rendered retry for navigation-only content and up to two image/document asset
attempts for an image-content page. It never guesses which UI button to click.
Set `recovery: "manual"` for explicit acquisition control. Rendering prohibitions,
OCR choices, and caller-selected ranges remain effective.

Read results include a `workflow` object:

- `state` describes observed extraction gaps, not answer correctness.
- `answer_verified` is always false: the caller must judge whether evidence
  supports the question.
- `source_complete` is false for known gaps and otherwise null; successful
  extraction does not establish that every relevant part of a source was read.
- `next_actions` provides `tool`, REST `endpoint`, `arguments`, `reason`, and
  `automatic: false`. Choose the suggestions relevant to the question.
- `source_bytes_retained` and `source_bytes_reacquirable` distinguish stored
  artifacts from sources whose bytes can potentially be reacquired by hash.

For example, a truncated text result may suggest `read_document` with its exact
`document_id` and next `offset`. A partial table or PDF suggests a later row/page
range. Read errors, no focus matches, navigation-only content, and OCR uncertainty
provide appropriate inspection or stronger-acquisition suggestions. Acquisition
retries are reported in `recovery_attempts`; recovered assets preserve their
`parent_url` and `parent_document_id`.

`read_document` reparsing and `view_document_image` first use retained source bytes.
If bytes are absent but an original file hash exists, they can reacquire the source
through the HTTP/TLS readers, checking public-target policy on public adapters and
verifying the exact hash. A changed source returns HTTP 409 instead of silently
substituting a newer document. Unavailable or unhashed sources return HTTP 410;
refetch the current source or capture an export through browser `download`.
A plain retained-text read needs no origin request.

MCP browser screenshots now use native image content with structured metadata,
like `view_document_image`, so vision-capable clients can inspect actual pixels.
Drive can derive an omitted `allowed_hosts` list from validated navigation URLs;
explicit lists are still enforced. Host entries contain names without ports.

See `evaluations/agent-workflow/` for the cold-agent evaluation harness, synthetic
fixture generation, scoring rules and evidence-recording methodology. This
workflow is intended to guide autonomous agents, while preserving direct tools
for deliberate shortcuts and recovery. Its presence is not proof that every
model/client will follow it successfully.

## 0.9 result and error refinements

HTML results below the ordinary content threshold can be returned as
`quality: "thin"` with text, retained evidence and warnings. They are not silently
promoted to `ok`; structured files retain their existing treatment. Blank prose
and detected interstitials do not count as successful text extraction.
`acquisition_attempts` records only tiers actually called, with `tier`, `reason`,
`outcome`, and challenge provider when observed. `browser_recovery` adds polling,
checkpoint and restoration metadata when the headed read succeeds.

Default reads automatically try bounded same-browser recovery after a detected
challenge. Explicit rendering restrictions win. Residual challenges remain failures
with workflow actions for inspection. Success means recovered content, not a solved
question or a guarantee that every bot wall can be bypassed.

Use `format` as the cross-transport fetch spelling. Capabilities advertise REST
`raw`/`links` under `compatibility_fields.rest_fetch_aliases`. Unknown MCP arguments
return tool errors before the backend is invoked; REST body typos return 422.
Busy responses retain HTTP 429 and add machine-readable reasons/limiter identity;
clients should distinguish polling from rate-window waiting.
