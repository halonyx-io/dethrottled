# Using Dethrottled from an agent

Dethrottled returns source choices, readable evidence and browser operations.
It does not supply a language-model answer or verify a proposition. This guide
helps select a tool and its controls; exact fields, bounds and defaults belong
in the generated [HTTP](HTTP-REFERENCE.md) and [MCP](MCP-REFERENCE.md) references.
Check the connected installation before relying on an optional worker.

## First connection

For MCP, initialize and retrieve `tools/list`. Forward initialization instructions,
full tool schemas, structured results and native image blocks to the agent.
For HTTP, inspect `/v2/capabilities` and `/v2/status`. Compare API and adapter
application versions; the MCP SDK version is a separate dependency. Compare the
initialization workflow hash with `client_contract.workflow_sha256` when available.
Refresh clients that retain old tool descriptions. Follow [public access](PUBLIC-ACCESS.md)
for remote bearer identity, scopes, proxy routes and namespace handling.

## Pick the shortest useful workflow

| Situation | Start with | Continue when needed |
|---|---|---|
| URL already known | `fetch`, usually with `focus` | Inspect quality, retained document and recovery actions |
| Need source choices | `search` | Read the promising candidates; refine around missing facts |
| Need sources read immediately | `search_and_fetch` | Inspect each read independently |
| Multi-source question | `research` | Inspect coverage/facets, clean/partial sources and unread candidates |
| One site's bounded collection | `crawl_site` | Inspect frontier/failures; continue deliberately within scope |
| Long or previously read document | `read_document`, `inspect_document` | Request offsets, page/row ranges or source images |
| Interaction, export, application data | `drive` | Reuse session; snapshot/read state before acting |
| Slow media or independent reads | `start_fetch_job` | Poll by cursor; resume interrupted work explicitly |
| Previously indexed local evidence | `corpus_search` | Read the retained/original source and check its date |

Known URLs do not require a preliminary search. Returned `workflow.next_actions`
and `read_plan` give concrete continuations, not a compulsory script. Select
what advances the actual task; expert controls remain available through schemas.

## Reuse public evidence with Corpus v2

Corpus is optional: normal web search does not require a corpus lookup. Call
`corpus_search` for previously indexed public material. Start with `mode="auto"`
and `support="standard"`; opaque identifiers use lexical lookup, other queries
use the configured MiniLM/E5 retrievers. `mode="lexical"` searches full bounded
text, including unembedded sections; `mode="hybrid"` explicitly fuses lexical
and semantic candidates. Use `domains` for source restrictions and `limit` for
the compact menu. `floor` overrides MiniLM's candidate floor, not E5's or the
support checks. Changing it is not a truth-probability adjustment.
The HTTP equivalent is `GET /corpus/search` with `q` instead of MCP's `query`.

If evidence is empty or incomplete, request `support="broad"`, refine query terms
or use live search. Broad retrieval can recover useful one-model translations
that standard corroboration rejects; it can also return irrelevant candidates.
Inspect `support_status`, `model_scores`, `retrieval_warning` and response-level
`retrieval_warnings`. `answer_support="unverified"` applies to both policies.
Standard checks and model agreement do not establish answer presence or truth.

Review `coverage`, omissions, offsets, freshness and `document_available`.
Reopen a valid `document_id` with `read_document`; if the handle has expired,
the indexed passage can still be useful or the original URL can be fetched again.
Corpus passages/vectors last 90 days; this does not extend the independent
six-hour search cache, 21-day extraction cache or retained-document expiry.
Public handles may be reused across callers; private/authenticated/interactive
reads are not automatically promoted into the shared corpus. See [Corpus](CORPUS.md)
for operator budgets, indexing jobs, repair and rollback.

## Search controls

Normal discovery starts with `profile="web", limit=15, ranking="source"`.
DDG Lite/HTML/TLS/browser are acquisition alternatives within one ten-choice
provider-family budget. Yahoo and Yandex supply small supplements, at most three
URLs each, six total; the complete menu never exceeds fifteen unique URLs.
No automatic DDG pagination fills that menu. Fewer usable results is normal.

| Control | Use and consequence |
|---|---|
| `query` | State the actual information need; refine around a missing fact instead of requesting a huge menu |
| `limit` | 1–15 displayed choices; changing this is not a promise of more upstream searches |
| `profile="fast"` | DDG-family route only |
| `profile="web"` or `"balanced"` | DDG plus Yahoo/Yandex supplements |
| `profile="thorough"` | Also requests Mwmbl; the same compact display and supplement budgets apply |
| `profile="news"` | Web plus news discovery/resolution paths |
| `profile="academic"` | Web plus Crossref/OpenAlex/arXiv specialist discovery |
| `engines` | Explicit comma-separated selection: web/news/mwmbl/crossref/openalex/arxiv/yahoo/yandex; optional exa/tavily/parallel require operator configuration |
| `engines="web"` | Request the primary family without default supplementary providers |
| `categories` | Empty, `news` or `academic`; follow the transport schema, not a guessed singular `category` |
| `language` | Provider hint; it does not uniformly constrain all primary discovery paths |
| `ranking` | `source` default; `bm25` or `fusion` deliberately opt into alternate ordering |
| `rank` | Legacy lexical-ranking switch; prefer the explicit ranking field when choosing a policy |
| `prefer_domains` | Explicit caller preference, not evidence that a domain supports a claim |
| `recency` | 0–1 freshness bias; inspect publication dates and source relevance yourself |
| `corpus` | 0–20 optional stored-passage candidates before final menu bounding; default 0 |
| `fresh` | Request refresh rather than using cached acquisition |
| `cache_mode` | `use`, `refresh`, `bypass`; bypass avoids both cache reads and writes |
| `max_age` | Optional cache-age bound in seconds; inspect returned cache provenance |
| `diagnostics` (MCP) | Request the richer search envelope; inspect `outcome`, `degraded` and per-provider reports rather than inferring success from legacy `status` |

REST also retains `num_results`/`max_items` compatibility fields; MCP does not
accept every REST alias. A neural `rerank=true` request is unsupported. Do not
invent an XGBoost, model-ranking or pagination parameter. Upstream result lists
and provider agreement are not verified page evidence. Legacy `status="ok"`
means a nonempty menu, not healthy providers. MCP `isError=false` means the tool
ran; decode the diagnostic JSON envelope and inspect `outcome`/`degraded`.
Research reports these diagnostics separately for each query. Corpus hits retain
extraction uncertainty at `provenance.extraction.completeness`; distinguish it
from indexing coverage and answer verification.

Example HTTP request body for a focused specialist menu:

```json
{"query":"structured concurrency task cancellation","profile":"academic","limit":10,"ranking":"source","cache_mode":"use"}
```

## Request controls versus operator settings

Request fields above select supported behaviour for one call. Deployment settings
select which capabilities exist and their resource/admission policy; they are not
extra JSON arguments. Change operator settings only within an authorized deployment
task. Inspect [configuration](CONFIGURATION.md), the selected Compose files and the
running capabilities instead of assuming an exported shell variable reaches a service.
The managed stack isolates its environment; a checkout's `.env` only interpolates
names actually mapped into its services.

| Operator controls | Scope |
|---|---|
| `DETHROTTLED_CHEAP_DISCOVERY` | Enable the static DDG probe before browser fallback; deployment default differs from standalone |
| `DETHROTTLED_SEARXNG_URL`, `DETHROTTLED_BROWSER_SEARCH_URL`, `DETHROTTLED_CRAWL4AI_URL` | Configured worker endpoints, not arbitrary per-request proxy choices |
| `DETHROTTLED_READ_PLAN_SECONDS` | Extra recovery admission budget; in-flight transports retain their own deadlines |
| `DETHROTTLED_RENDER_CONCURRENCY` | Shared renderer work capacity; more slots do not defeat upstream blocking |
| `DETHROTTLED_DRIVE_SESSION_TTL`, `DETHROTTLED_DRIVE_MAX_SESSIONS` | Session expiry/capacity and resource pressure |
| `DETHROTTLED_BROWSER_GRAPHICS` | Verified graphics policy; GPU device exposure remains a deployment concern |
| `MCP_MAX_RESULTS`, `MCP_MAX_CHARS` | Adapter ceilings can restrict the core ceilings, not raise them |
| `DETHROTTLED_CLIENT_CONCURRENCY`, `DETHROTTLED_GLOBAL_CONCURRENCY`, `DETHROTTLED_REQUESTS_PER_MINUTE` | Public caller/shared admission and retry behaviour |

These are common operator controls, not an exhaustive replacement for source and
configuration references. Worker CLI profiles, search profiles and read profiles
are different concepts. Do not call a private worker directly to circumvent the
compact public search policy or a caller's security/namespace boundary.

## Read controls

The normal read pipeline automatically assesses and attempts eligible recovery.
Use controls for a concrete need rather than preemptively forcing every expensive
path. Explicit rendering/OCR restrictions still apply during automatic recovery.

| Controls | When to use them |
|---|---|
| `urls` | One to ten known URLs; choose sources for the task rather than fetching every candidate |
| `focus`, `max_chars` | Question-oriented text and an appropriate response budget; text ceilings do not guarantee complete acquisition |
| `format="text"`, `"links"`, `"html"` | Prose, outbound-link discovery, or source inspection; `focus` requires text |
| `render="auto"`, `"always"`, `"never"` | Default escalation, renderer-first, or no rendering |
| `wait_for`, `render_delay` | Known CSS readiness condition and bounded renderer delay; do not use arbitrary long sleeps as proof of readiness |
| `headed_fallback` | Deliberately request headed recovery for additional failures; challenges/shells can already trigger automatic recovery |
| `recovery="auto"` or `"manual"` | Higher-level navigation/asset recovery on/off; manual does not turn off the underlying acquisition ladder |
| `fresh`, `cache_mode`, `max_age` | Refresh, bypass or bound cached evidence; use the same cache semantics as search |
| `response_format="detailed"` or `"concise"` | Presentation control; preserve warnings, provenance and continuation either way |
| `document_mode="auto"`, `"native"`, `"layout"` | Native document extraction or optional layout inference when available |
| `ocr_mode="auto"`, `"always"`, `"never"`, `ocr_language` | Explicit OCR policy and installed language choice; verify uncertain numbers against source pixels |
| `page_start`, `page_end` | Bounded page windows; request another window for later pages |
| `row_start`, `row_end`, `sheet`, `max_cell_chars` | Bounded spreadsheet/table windows and cell clipping controls |
| Read `profile` (REST core) | `fast`, `balanced`, `thorough`; fast prohibits rendering; this is distinct from search profiles and is not a universal MCP argument |

Legacy REST `raw`/`links`/boolean-render aliases are not MCP argument names.
Public adapters set `public_only` and `evidence_namespace` from policy/identity;
clients cannot forge a namespace or disable public-target enforcement. Trusted
raw-API callers have a different boundary. Do not copy those expert raw-core
fields into public MCP calls.

Fetch permits up to 1,000,000 response characters per URL; the normal defaults
are smaller and differ by transport. Research sources default to ten, up to twenty,
with a shared 24-candidate pool and at most four replacement primary URLs.
Research excerpts allow up to 120,000 characters per source. These are ceilings,
not a request to fill every budget. See [limits](LIMITS.md).

## Interpret and continue

- `quality=ok` means extraction succeeded. It does not mean the answer is true,
  complete, current or relevant. `thin` retains short HTML evidence; `suspect`
  retains possible mixed-content pollution; `failed` records an unsuccessful read.
- Preserve `warnings`, `source_partial`, `truncated`, `extraction`, acquisition
  attempts/URLs, source dates, hashes and `read_plan`. A long page may still include
  an error banner. Inspect the exact retained ranges rather than deleting a phrase.
- Retain `document_id`/hash and use `read_document` with `offset`/`next_offset`,
  focus and ranges. Use `inspect_document` for blocks, tables and citation positions.
- `view_document_image` needs retained or reacquired matching source bytes. Forward
  its native image blocks to a vision-capable consumer. Changed source bytes need a
  new fetch; text-only clients cannot verify pixels by receiving a placeholder.
- Research's facet ledger and term matches expose evidence/gaps. `partial_sources`
  remain distinct from clean sources; neither constitutes semantic answer verification.

## Drive deliberately

Start with an observed URL, then `snapshot` or `read_state`; inspect real selectors,
frames, tabs or same-host application responses before choosing actions. `ok` reports
execution; `access.status` separately describes observed content, challenges or login
walls. A successful click does not establish that the desired page data loaded.

| Action family | Current actions |
|---|---|
| Navigation/context | `goto`, `url`, `title`, `tabs`, `switch_tab` |
| Observe | `snapshot`, `read_state`, `text`, `html`, `attr`, `count`, `network`, `history` |
| Interact | `click`, `fill`, `type`, `press`, `select`, `check`, `uncheck`, `hover` |
| Readiness/expansion | `wait_for`, `wait`, `scroll`, `expand_details` |
| Retain/export | `download`, `checkpoint` |

Step controls include `selector`, `frame`, `value`, `url`, `ms`, `delay_ms`,
`name`, `index`, `limit` and `max_chars`; applicable fields depend on the action.
Use `ms`, not a guessed `timeout` step field. `network` lists captured same-host
XHR/fetch responses; use `name="body"` and an observed index to read one.
Use a frame CSS selector to scope supported operations; inspect tabs before switching.
See [drive](DRIVE.md) for action-specific value conventions.

Top-level controls include `url`, `steps`, `timeout_ms`, `session`, `operation_id`,
`close_session`, `allowed_hosts`, `canaries`, `include_events`, `screenshot`,
`screenshot_full_page` and `ocr_language`; transport policy supplies namespace/target
controls. `allowed_hosts` contains hostnames without ports. Omit it when validated
navigation can establish the scope. Screenshots support booleans or
`never|failure|canary|always`; preserve the returned image blocks.

Reuse the returned session ID. Use `operation_id` for retrying an identical operation
in an explicit named session; inspect unknown outcomes before repeating a mutation.
Checkpoint retains browser storage/action history, not a live DOM or every tab.
Close sessions when done. Do not navigate directly to a file expecting an HTML app;
read the URL or capture an export through `download`.

A minimal observation request:

```json
{"url":"https://example.com/","steps":[{"action":"snapshot","limit":5}],"screenshot":"never","close_session":true}
```

## Endpoint and tool map

These are core routes. Public REST has its own allowlist; the generated references
and connected server control which fields are supported. Framework `/docs` and
`/openapi.json` are separate from the application route table.

| Core method/path | MCP tool or use |
|---|---|
| `POST /search` | `search` |
| `POST /v2/search` | `search` with `diagnostics=true` |
| `POST /fetch` | `fetch` |
| `POST /extract` | Compatibility alias for fetch |
| `POST /extract-with-links` | `extract_with_links` |
| `POST /search-and-fetch` | `search_and_fetch` |
| `POST /search-and-extract` | Compatibility alias for combined search/read |
| `POST /research` | `research` |
| `POST /drive` | `drive` |
| `POST /site/crawl` | `crawl_site` |
| `POST /documents/read` | `read_document` |
| `POST /documents/structure` | `inspect_document` |
| `POST /documents/image` | `view_document_image` |
| `POST /jobs/fetch` | `start_fetch_job` |
| `POST /jobs/read` | `read_fetch_job` |
| `POST /jobs/cancel` | `cancel_fetch_job` |
| `POST /jobs/resume` | `resume_fetch_job` |
| `GET /corpus/search` | `corpus_search` |
| `GET /corpus/stats` | `corpus_stats` |
| `GET /ready` | `ready` |
| `GET /v2/capabilities` | `capabilities` |
| `GET /v2/status` | `status` |
| `GET /stats` | `stats` |
| `GET /health` | HTTP identity/liveness; MCP initialization and local adapter health expose separate identity |

## Retry and failure discipline

Poll read jobs using their returned cursor and retry hint. Resume interrupted jobs
without restarting completed positions. Respect 429/Retry-After and distinguish
caller/global admission from upstream refusal. A cooldown expiry is not proof that
an upstream provider recovered. Report exact arguments, timing, versions, request ID,
quality and warnings; exclude credentials/browser storage from evidence archives.

Parse each complete MCP JSON text block separately; do not concatenate blocks
into invalid JSON. Prefer structured content when supplied and retain native image
blocks. The engine supports ordinary HTTP/software clients too; a language model
is not needed to execute these workflows.


## Interpreting readiness and extraction coverage

Readiness uses recent real-search observations; cold/stale means unknown, not down.
Status polling sends no upstream search probes. Perform one relevant search when
current evidence is needed. Cached results and timer expiry do not prove recovery.
`extraction.completeness` describes sampled structural coverage, not verified
completeness. Missing samples request inspection; they do not justify blindly
repeating browser actions. Preserve warnings and inspect relevant source HTML or
another representation when the missing evidence matters.

## Domain-filter refusals

With [native adblock filtering](ADBLOCK.md), `policy_blocked=adblock` and
`adblock_blocked:` identify a filtering decision. Report it or choose another
source; retrying other tiers cannot override it. `/v2/status`, capabilities and
`/stats` expose list availability and errors. Enabled without valid rules permits
acquisition while retaining existing public-target security.
