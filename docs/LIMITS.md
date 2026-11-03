# Coverage limits and continuation

Defaults control the first amount of evidence returned; ceilings describe what
an agent may deliberately request when that evidence is insufficient. A ceiling
is not a promise that a publisher supplies that many results or that every read
will succeed. Inspect actual coverage, partial flags and continuation handles.

| Operation | Default | Supported ceiling |
|---|---|---|
| Search choices | HTTP/MCP 15 | DDG family 10; each supplement 3; supplements 6 total; complete menu 15 |
| Local corpus search | HTTP 10; MCP 5 | 10 matches |
| Research sources | 10 | 20 readable sources; 24 unique candidates across facets; at most four replacement primary URLs |
| Research additional facets | Automatic primary-source probe | 10 additional queries, plus the question |
| Research excerpt per source | 12,000 characters | 120,000 characters |
| Fetch text | HTTP 8,000; MCP 12,000 characters | 1,000,000 characters per URL |
| Retained-document text read | 12,000 characters | 1,000,000 characters per call |
| Browser snapshots/network lists | 10 items | 10 items; Bing snapshots 3 |
| Browser text/HTML action | Worker action default | 1,000,000 characters per action |
| Explicit URL batch | Caller supplied | 10 URLs per fetch request |
| Site crawl | 10 pages | 50 pages per run; continue with returned frontier URLs |

`/v2/capabilities` exposes `request_limits` and research ceilings. Request schemas
show parameter-specific bounds. MCP operators may explicitly lower `MCP_MAX_RESULTS`
or `MCP_MAX_CHARS`; these settings cannot raise the core API above its ceilings.
A client or reverse proxy may impose its own deadline or result-size constraint.
Research and combined search/read requests can use up to a 600-second adapter
backend timeout; individual page and browser-operation budgets remain bounded.

## How an agent should request more

Start with a focused question and assess the returned evidence. If discovery is
narrow, refine the question, select a fitting specialist profile or follow an
observed site frontier. Additional facets share the same research candidate budget;
they do not create another ten-choice menu each. If a known document is truncated, use `read_document` with
`document_id`, `offset`, page or row controls. Use larger `max_chars` when the
agent needs to examine more context together; an extraction may still be partial
because of parser, file, page, model or publisher limits.

Research prefers publisher diversity, then fills remaining capacity with additional
primary documents when fewer publishers are available. It does not discard every
third document from the same publisher. Duplicate content is still assessed.

Keep batches bounded and continue them. A larger batch or more workers does not
make an upstream block disappear. Shared admission, finite queues, parser input
limits, concurrent-browser limits and timeouts protect useful work from exhausting
the service. They remain separate from evidence-size and discovery ceilings.

[Documentation home](README.md) · [Agent integration](AGENT-UPGRADES.md) · [Configuration](CONFIGURATION.md)

## Broad browser discovery

Browser search requests above 12 results collect usable results from the existing
engines, deduplicate URLs and follow same-origin next-page controls when available.
Each engine has at most five pages within its existing six-second service budget.
A blocked or failed later page retains the earlier usable results and reports its
reason. Smaller requests keep the first-usable-engine path and do not paginate.
The API forwards the requested count; upstream availability and the finite page/time
budgets can still produce fewer results than requested. Use facets, refined queries
or deliberate browser interaction when further discovery is needed.

Cheap TLS discovery also respects broad intent: when a request above 12 results
gets fewer cheap results than requested, the API invokes the broader browser path
automatically and merges unique URLs. It retains cheap results if browser recovery
fails. Search diagnostics expose `breadth` counts and fulfilled/partial status;
small usable cheap requests still return immediately.
