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

## Browser acquisition and historical broad search

The current search API caps the DDG provider family at ten choices before calling
its TLS/browser acquisition paths. It does not automatically paginate DDG to fill
a fifteen-result menu: the remaining choices come from the bounded supplementary
providers. Lite, HTML, TLS and browser fallbacks are acquisition alternatives
within that same DDG budget.

The private browser worker retains a broader collection path for direct requests
above twelve results, including bounded same-origin pagination. This is an
internal capability, not a way to raise the normal public search ceiling. The
[earlier broad-search evaluation](../evaluations/broad-search/results/2026-11-02/REPORT.md)
records its original behavior before compact menus were adopted. For broader
evidence now, refine queries, use research facets within their shared budget,
follow an observed site frontier or deliberately operate the browser.

## Corpus budgets and lifetimes

[Corpus v2](CORPUS.md) defaults to 50,000 embeddings per model, 32/96 selected
passages per ordinary/long source, a 256 MiB combined matrix budget and a 512 MiB
soft corpus SQLite target. These are separate from full-document retention and
model-process memory. Corpus passage/vector retention is 90 days; the search
cache remains six hours and extraction cache 21 days. HTTP/MCP corpus menus
remain at most ten results, including explicit broad support.


Selective HTML coverage checks sample up to 24 substantive blocks (start/end
anchors) on long structured pages; they do not establish exhaustive completeness.
Existing extracted-content cache entries are not retroactively reconstructed.
Use `cache_mode="refresh"` or `"bypass"` when reassessing older cached extraction;
`bypass` neither reads nor writes that cache. Cache lifetimes remain unchanged.

## Long PDF reads

Without an explicit `page_end`, native PDF text extraction considers up to 1,000
pages from `page_start`, stopping earlier at the extraction character budget
(default one million). Explicit HTTP/MCP page ranges remain limited to 100 pages.
Response character limits are separate: use focused reads or retained-document
`next_offset` to inspect text already extracted. Old cached extractions retain
their original coverage; use `cache_mode=refresh` or `bypass` to reassess them.

Native table analysis considers at most 100 pages per read, independently of the
larger text window. `extraction.native_table_scan` reports its range and whether
later extracted pages remain unanalysed for tables. Select later ranges when
those tables matter. OCR retains its existing eight-page default budget; the
larger native window does not authorize unlimited OCR or model inference.
When OCR runs out, `next_page` identifies the first unread scan rather than
skipping its missing text.

A character window stops before consuming a later page whose text would not fit,
so `extraction.next_page` can resume without skipping its tail. A single page
larger than the extraction budget remains clipped: `truncated_page` and a
`page_text_truncated` warning identify it; inspect source pixels. Successful
non-HTML document extraction uses document/range continuation rather than the
HTML browser recovery loop. Reparsed document versions refresh `content_status`
and `source_partial`; earlier retained versions remain accessible.
