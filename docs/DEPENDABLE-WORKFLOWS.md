# Reading and evidence

Use `fetch` for a URL, then retain its document handle and inspect whether the
returned evidence covers the question. The same read controls are available
through the HTTP API, MCP and fetch jobs, with transport-specific parameters in
the [HTTP](HTTP-REFERENCE.md) and [MCP](MCP-REFERENCE.md) references.

## Formats and prerequisites

| Source | Reader and important limits |
|---|---|
| HTML | Direct/TLS/render/headed acquisition with local extraction; partial snapshots, challenges and thin content remain explicit |
| PDF | Text layer, native table detection, bounded page selection and Tesseract OCR; optional Docling layout/table inference |
| CSV, TSV, XLS, XLSX/XLSM | Row windows, sheet selection and cell limits; cached values preferred, uncached formulas remain formulas |
| DOCX, PPTX, ODT, ODS, ODP, EPUB, RTF | Local document readers; preserve warnings and bounded embedded-image OCR provenance |
| Legacy DOC/PPT | Local antiword/catppt converters included in the API image; source installs need those tools |
| Plain text/Markdown, JSON/JSONL, XML/SVG | Text/data extraction; SVG text does not reconstruct visual chart relationships |
| EML | Message text and bounded attachment handling; inspect archive/attachment completeness |
| ZIP, TAR, GZIP | Bounded member/nesting/expansion handling without extracting paths to disk; encrypted/unsupported members can fail |
| Raster images | Tesseract OCR when enabled; layout and chart relationships need pixel inspection |
| VTT/SRT and YouTube captions | Timed text when available; a blocked YouTube page or missing caption is not a universal media download path |
| Direct audio/video files | Optional local speech worker; transcription covers speech, not video frames or verified speaker identity |
| MSG/XLSB | Tika worker in the default stack; external worker needed for standalone Python; attachment completeness and physical cell structure unverified |

Byte signatures take precedence where reliable. CSV/TSV require a URL or MIME
hint. An HTML error page advertised as an Office file is not parsed as a valid
spreadsheet. Supported does not mean arbitrary corrupted/encrypted files work.
Check capabilities and per-source warnings on the actual installation.

## Text, focus and citations

Fetch retains up to 1,000,000 extracted characters independently of the response
budget by default. A `document_id` identifies scoped retained text with its
`document_sha256`. `read_document` can select `focus`, or sequential `offset`
and `max_chars`; continue with `next_offset`. Positions are Unicode character
offsets in the retained version, not byte offsets in live HTML.

`inspect_document` returns blocks, exact text selectors and supported table/page
structure. A returned table-row ordinal is not necessarily a physical spreadsheet
row. Retained text defaults to seven-day retention and a 200 MB storage budget;
earlier eviction is possible. Re-fetch deliberately when current information is
needed. A document hash does not assert that a website is unchanged.

## PDF pages, OCR and layout

Use `page_start`/`page_end` for at most 100 selected pages. Inspect total pages,
methods, `next_page`, partial coverage and warnings. `ocr_mode=auto|always|never`
controls OCR; `always` keeps native text as well. `ocr_language` selects installed
Tesseract data. The API image includes English, Malay, simplified/traditional
Chinese and orientation data. OCR confidence is a word score, not fact accuracy.

`document_mode=native` skips optional layout analysis; `layout` requests Docling;
`auto` applies bounded heuristics, including multicolumn and scanned-table cases.
Native parsing/table detection does not require that worker. Failed or incomplete
layout inference preserves native evidence with warnings. Lost-text/numeric
checks catch gross failures, not every incorrect cell. Neural/scanned table
inference is not a general chart-understanding model.

Use `view_document_image` for supported retained source pixels. Where source
bytes were not retained, a re-acquisition must match the source hash before
reparsing or image inspection. Changed bytes are not silently substituted. Some
sources cannot provide pixels or an additional page later; follow the returned
prerequisites rather than assuming every handle contains the original file.

## Spreadsheet windows and large cells

Use `sheet`, `row_start`, `row_end` and `max_cell_chars`. Row positions are
one-based physical source positions, including a header; a window selects at
most 2,000 rows. Continue with table metadata's `next_row`. Later windows can
include explicitly labeled row-1 context. Extent can include formatted empty rows.

Empty cells retain their columns. Pipes and ampersands in cells use reversible
HTML entity escapes. The default cell cap is 32,767 characters; requests can
raise it to one million. Truncated cells remain flagged. Unsupported range
requests fail rather than claim to have selected a page or row.

## Speech and captions

Captions retain cue timing when available. Direct media files use the optional
local Faster-Whisper worker: CPU int8, model `small` by default, one active job,
50 MiB input and at most 30 minutes decoded audio. The supervisor deadline is
570 seconds. Speech weights may download on first use and are cached locally.
Use jobs for slow media, and inspect ASR warnings, segment timing and content.
ASR can mishear or hallucinate; timestamps are estimates.

## Durable jobs and site coverage

`start_fetch_job`/`POST /jobs/fetch` takes normal fetch controls and an optional
`operation_id`. Read with `job_id` and cursor, then reuse `next_cursor` and
respect `poll_after_ms`. Results arrive in completion order; `source_index`
maps to the input URL list. Defaults allow two active jobs per identity and four
globally, with 24-hour result retention and a 200 MB budget.

Identical operation submissions reuse the job; conflicting payloads return 409.
Cancellation stops scheduling new work; in-flight acquisition may finish.
After interruption, resume explicitly: committed results remain, missing
positions can be read again, and browser mutations never resume automatically.

`crawl_site` follows bounded observed links and sitemaps within one origin and
path prefix. Inspect failed reads, frontier and continuation URLs. Hidden,
unlinked and JavaScript-only sources can be absent; whole-site completeness
remains unknown. Research `coverage.facets` reports readable candidates, failed
or unread URLs and term matches. It does not verify semantic support.

## Partial evidence

`source_partial`, `truncated`, extraction metadata and `workflow.next_actions`
are model-visible controls. A loading browser snapshot or HTML capture limit
must not become a complete-source claim. HTML `quality=thin` preserves a short
best-available result; structured short documents can still be valid. Preserve
warnings even when the expected number appears in the returned excerpt.

[Documentation home](README.md) · [Agent guide](AGENT-UPGRADES.md) · [API](API.md) · [Evidence](EVIDENCE.md)
