# Coverage and document workflows (0.7)

Default discovery still uses the existing keyless sources and headed DDG path.
Independent URLs with identical titles survive discovery. Duplicate URLs merge
provider/query provenance; research can still collapse mirrors after reading
and comparing actual content.

## Optional independent providers

Set one or more server environment variables (`DETHROTTLED_EXA_API_KEY`,
`DETHROTTLED_TAVILY_API_KEY`, `DETHROTTLED_PARALLEL_API_KEY`). These are optional
external, potentially metered services. Agents select them explicitly through
`engines`, for example `web,exa,tavily`, on search, search_and_fetch or research.
Default profiles never call them. Capabilities reports configuration booleans;
keys are never tool arguments or response fields. Provider failures preserve
other engines' results, and attempts distinguish not_configured, empty and failed.
Prices are not estimated: diagnostics report cost=unknown for metered requests.

This release tests contracts with synthetic responses. No paid-provider quality,
quota, billing or availability comparison has been performed without account keys.
Official interfaces: [Exa](https://exa.ai/docs/reference/search),
[Tavily](https://docs.tavily.com/documentation/api-reference/endpoint/search),
[Parallel](https://docs.parallel.ai/api-reference/search/search).

## PDF structure and optional Docling

`document_mode=auto` adds native table cells and source page boxes to PDF reads;
inspect_document exposes native_pdf_tables. Text retains the original extraction
and appends detected tables when space permits. Critical values still need source
inspection: both native table detection and neural layout inference can be wrong.
Use page_start/page_end and larger read budgets when table output is partial.
`native` skips layout analysis. `layout` explicitly requests Docling.

To enable the local worker:

```sh
# In .env:
# DETHROTTLED_LAYOUT_WORKER_URL=http://docling-worker:19891
docker compose -f docker-compose.yml -f docker-compose.agents.yml \
  --profile layout build docling-worker dethrottled
docker compose -f docker-compose.yml -f docker-compose.agents.yml \
  --profile layout up -d docling-worker dethrottled
```

The private worker accepts PDF bytes, never URLs. It uses Docling 2.145.0 and
CPU PyTorch, with one conversion at a time, a 50 MiB input ceiling, at most 100
selected pages and a 180-second child-process deadline. Compose limits it to
8 GiB and four CPUs. Downloaded model weights persist in layout-models (about
506 MiB in this evaluation); initial use requires access to the model repository.
The layout worker performs native-text layout/table inference; scanned PDF OCR
continues through the existing native/OCR pipeline. It is not a vision model
for arbitrary charts. ARM64 installation has not been tested for this worker.

Auto mode invokes Docling for observed multicolumn PDFs of at most ten selected
pages, after native parsing, when native tables were not already recovered.
Explicit layout mode can request larger bounded ranges. Failed/incomplete
conversion, lost numeric tokens, major text loss, or lost native tables preserve
the native text with a warning. These guards catch gross losses, not all errors.
A missing worker also preserves native output. read_document(reparse=true),
fetch and durable fetch jobs expose the same mode through MCP and REST.
Acquisition cache compatibility includes the selected mode and whether the
worker was configured, so enabling it does not silently reuse an incompatible
old extraction.

## Browser recovery and scope

Use `drive` with normal public URL/host policy:

1. Navigate and snapshot to identify controls.
2. For iframe locator actions, set `frame` to the iframe's CSS selector.
3. `tabs` lists current tabs; `switch_tab` selects an allowed tab by index.
   Inspect tabs after a popup opens. Indexes are live positions, not durable IDs.
4. `network` lists observed same-scope fetch/XHR responses. Set name=body and
   selector=response_id to read one. Text/JSON bodies no longer require a
   Content-Length header. Both declared and decoded sizes are checked against
   2 MB; this is an acceptance limit, not streaming browser-memory isolation.
5. `checkpoint` saves cookies, localStorage, IndexedDB and the active page's
   allowed-frame sessionStorage for 24 hours. Wait for navigation to finish first.
   Restore with the same session ID and original host scope. Other tabs and live
   DOM state are not restored. Checkpoints are private local files, not response data.
6. `history` lists up to 200 recent action outcomes. A checkpoint retains this
   history. It omits typed values, selectors and response bodies and does not
   replay actions. An operation_id can replay an already completed result;
   unknown outcomes remain fenced. Pre-0.7 operation IDs remain compatible when
   the new optional frame selector is omitted.
7. Close the session to remove its retained checkpoint.

Allowed hosts must include any target iframe/popup host from the beginning.
Navigation outside that scope is blocked, including popup and frame navigation;
public-only network policy still applies. Checkpoint state is sensitive and
belongs on protected persistent storage. Cross-protocol browser session IDs
remain separate; retained document namespaces work across MCP and REST.

## Research coverage

Research now defaults to thorough keyless discovery. Supply explicit queries
for facets and engines for deliberate provider selection. coverage.facets records
candidate count, readable source references, lexical matched/missing terms,
unread URLs, failed/duplicate reads and executable next_actions. The status
`evidence_available` says text was read; answer_verified is always false.
It neither certifies semantic support nor enumerates every source on the web.
The caller must assess agreement, dates, primary-source authority and whether
returned excerpts actually answer the question. Truncation and partial-source
flags remain visible. MCP initialization instructions and capabilities explain
these workflows without requiring a client-specific skill.
