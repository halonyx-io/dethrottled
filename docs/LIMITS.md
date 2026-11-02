# Coverage limits and continuation

Defaults control the first amount of evidence returned; ceilings describe what
an agent may deliberately request when that evidence is insufficient. A ceiling
is not a promise that a publisher supplies that many results or that every read
will succeed. Inspect actual coverage, partial flags and continuation handles.

| Operation | Default | Supported ceiling |
|---|---|---|
| Search results | HTTP 8; MCP 10 | 50 results |
| Research sources | 10 | 30 sources |
| Research additional facets | Automatic primary-source probe | 10 additional queries, plus the question |
| Research excerpt per source | 12,000 characters | 120,000 characters |
| Fetch text | HTTP 8,000; MCP 12,000 characters | 1,000,000 characters per URL |
| Retained-document text read | 12,000 characters | 1,000,000 characters per call |
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
narrow, increase `limit`, add distinct research facets, or follow an observed
site frontier. If a known document is truncated, use `read_document` with
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
