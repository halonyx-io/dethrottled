# MCP tool reference

Generated from the adapter tool signatures. The connected server's
`tools/list` schemas are authoritative for runtime validation. Selected numeric
controls are additionally bounded/clamped by adapter/backend code.
Unknown tool arguments are rejected. Caller identity and public-target policy
are injected by the adapter; they are not caller-selectable tool arguments.

This adapter registers **20 tools**. See [agent integration](AGENT-UPGRADES.md)
for the autonomous workflow and [public access](PUBLIC-ACCESS.md) for setup.

## search

Find pages. Returns ranked results with url, title and snippet.

| Argument | Type/choices | Required/default |
|---|---|---|
| `query` | str | required |
| `limit` | Annotated[int, Field(ge=1, le=MAX_RESULTS)] | 10 |
| `fresh` | bool | False |
| `rank` | bool | False |
| `corpus` | int | 0 |
| `recency` | float | 0.0 |
| `categories` | str | '' |
| `language` | str | '' |
| `profile` | Literal['fast', 'web', 'balanced', 'thorough', 'news', 'academic'] | 'web' |
| `engines` | str | '' |
| `ranking` | Literal['source', 'bm25', 'fusion'] | 'source' |
| `prefer_domains` | list[str] \| None | None |
| `diagnostics` | bool | False |
| `cache_mode` | Literal['use', 'refresh', 'bypass'] | 'use' |
| `max_age` | float \| None | None |
## fetch

Read pages you already have URLs for.

| Argument | Type/choices | Required/default |
|---|---|---|
| `urls` | list[str] | required |
| `max_chars` | Annotated[int, Field(ge=1, le=MAX_CHARS)] | 12000 |
| `format` | Literal['text', 'links', 'html'] | 'text' |
| `render` | Literal['auto', 'always', 'never'] | 'auto' |
| `fresh` | bool | False |
| `cache_mode` | Literal['use', 'refresh', 'bypass'] | 'use' |
| `max_age` | float \| None | None |
| `wait_for` | str | '' |
| `render_delay` | Annotated[float, Field(ge=0, le=5)] | 0.5 |
| `headed_fallback` | bool | False |
| `focus` | str | '' |
| `response_format` | Literal['detailed', 'concise'] | 'detailed' |
| `recovery` | Literal['auto', 'manual'] | 'auto' |
| `ocr_language` | str | '' |
| `document_mode` | Literal['auto', 'native', 'layout'] | 'auto' |
| `ocr_mode` | Literal['auto', 'always', 'never'] | 'auto' |
| `page_start` | Annotated[int, Field(ge=1)] | 1 |
| `page_end` | Annotated[int \| None, Field(ge=1)] | None |
| `row_start` | Annotated[int, Field(ge=1)] | 1 |
| `row_end` | Annotated[int \| None, Field(ge=1)] | None |
| `sheet` | str | '' |
| `max_cell_chars` | Annotated[int \| None, Field(ge=1, le=1000000)] | None |
## extract_with_links

Read public URLs while retaining resolved outbound links.

| Argument | Type/choices | Required/default |
|---|---|---|
| `urls` | list[str] | required |
| `max_chars` | Annotated[int, Field(ge=1, le=MAX_CHARS)] | 12000 |
| `render` | Literal['auto', 'always', 'never'] | 'auto' |
| `fresh` | bool | False |
## search_and_fetch

Find pages and read them in one call.

| Argument | Type/choices | Required/default |
|---|---|---|
| `query` | str | required |
| `limit` | Annotated[int, Field(ge=1, le=MAX_RESULTS)] | 5 |
| `max_chars` | Annotated[int, Field(ge=1, le=MAX_CHARS)] | 3000 |
| `rank` | bool | False |
| `render` | Literal['auto', 'always', 'never'] | 'auto' |
| `fresh` | bool | False |
| `document_mode` | Literal['auto', 'native', 'layout'] | 'auto' |
| `ocr_mode` | Literal['auto', 'always', 'never'] | 'auto' |
| `ocr_language` | str | '' |
| `profile` | Literal['fast', 'web', 'balanced', 'thorough', 'news', 'academic'] | 'web' |
| `engines` | str | '' |
| `ranking` | Literal['source', 'bm25', 'fusion'] | 'source' |
| `prefer_domains` | list[str] \| None | None |
| `cache_mode` | Literal['use', 'refresh', 'bypass'] | 'use' |
| `max_age` | float \| None | None |
## research

Gather cited sources and relevant excerpts across multiple searches.

| Argument | Type/choices | Required/default |
|---|---|---|
| `question` | str | required |
| `queries` | list[str] \| None | None |
| `max_sources` | Annotated[int, Field(ge=1, le=16)] | 10 |
| `max_chars` | Annotated[int, Field(ge=500, le=120000)] | 12000 |
| `fresh` | bool | False |
| `engines` | str | '' |
| `profile` | Literal['web', 'balanced', 'thorough', 'academic', 'news'] | 'web' |
| `follow_assets` | bool | True |
| `categories` | Literal['', 'news', 'academic'] | '' |
| `response_format` | Literal['detailed', 'concise'] | 'detailed' |
## drive

Operate a stateful browser using bounded steps and structured evidence.

| Argument | Type/choices | Required/default |
|---|---|---|
| `steps` | list[BrowserStep] \| None | None |
| `session` | str | '' |
| `url` | str | '' |
| `allowed_hosts` | list[str] \| None | None |
| `canaries` | list[str] \| None | None |
| `screenshot` | Literal['never', 'failure', 'canary', 'always'] | 'failure' |
| `screenshot_full_page` | bool | False |
| `include_events` | bool | True |
| `close_session` | bool | False |
| `timeout_ms` | Annotated[int, Field(ge=1000, le=180000)] | 45000 |
| `operation_id` | str | '' |
| `ocr_language` | str | '' |
## read_document

Reopen retained source evidence without another origin request.

| Argument | Type/choices | Required/default |
|---|---|---|
| `document_id` | str | required |
| `focus` | str | '' |
| `offset` | int | 0 |
| `max_chars` | Annotated[int, Field(ge=1, le=1000000)] | 12000 |
| `response_format` | Literal['detailed', 'concise'] | 'detailed' |
| `reparse` | bool | False |
| `row_start` | int | 1 |
| `row_end` | int \| None | None |
| `sheet` | str | '' |
| `max_cell_chars` | int \| None | None |
| `page_start` | int | 1 |
| `page_end` | int \| None | None |
| `document_mode` | Literal['auto', 'native', 'layout'] | 'auto' |
| `ocr_mode` | Literal['auto', 'always', 'never'] | 'auto' |
| `ocr_language` | str | '' |
## view_document_image

Inspect retained PDF/image pixels to verify OCR, charts and numeric tables.

| Argument | Type/choices | Required/default |
|---|---|---|
| `document_id` | str | required |
| `page` | int | 1 |
| `crop` | tuple[int, int, int, int] \| None | None |
| `max_dimension` | int | 2400 |
## start_fetch_job

Start durable page reads and receive sources as they finish via read_fetch_job.

| Argument | Type/choices | Required/default |
|---|---|---|
| `urls` | list[str] | required |
| `operation_id` | str | '' |
| `focus` | str | '' |
| `render` | Literal['auto', 'always', 'never'] | 'auto' |
| `max_chars` | Annotated[int, Field(ge=1, le=1000000)] | 12000 |
| `wait_for` | str | '' |
| `fresh` | bool | False |
| `ocr_language` | str | '' |
| `page_start` | int | 1 |
| `document_mode` | Literal['auto', 'native', 'layout'] | 'auto' |
| `ocr_mode` | Literal['auto', 'always', 'never'] | 'auto' |
| `page_end` | int \| None | None |
| `headed_fallback` | bool | False |
| `row_start` | int | 1 |
| `row_end` | int \| None | None |
| `sheet` | str | '' |
| `max_cell_chars` | int \| None | None |
## read_fetch_job

Read new completed sources; reuse next_cursor and respect poll_after_ms.

| Argument | Type/choices | Required/default |
|---|---|---|
| `job_id` | str | required |
| `cursor` | int | 0 |
## cancel_fetch_job

Stop scheduling new reads. In-flight network/OCR calls may still finish.

| Argument | Type/choices | Required/default |
|---|---|---|
| `job_id` | str | required |
## resume_fetch_job

Resume an interrupted/cancelled read job, retaining completed source rows.

| Argument | Type/choices | Required/default |
|---|---|---|
| `job_id` | str | required |
## inspect_document

Get structured retained-text blocks, exact quotes and versioned citation selectors.

| Argument | Type/choices | Required/default |
|---|---|---|
| `document_id` | str | required |
| `focus` | str | '' |
| `offset` | int | 0 |
| `limit` | Annotated[int, Field(ge=1, le=100)] | 30 |
## crawl_site

Discover and retain linked/sitemap sources within one site and report coverage.

| Argument | Type/choices | Required/default |
|---|---|---|
| `urls` | list[str] | required |
| `max_pages` | Annotated[int, Field(ge=1, le=50)] | 10 |
| `max_depth` | Annotated[int, Field(ge=0, le=5)] | 2 |
| `path_prefix` | str | '/' |
| `render` | Literal['auto', 'always', 'never'] | 'auto' |
## corpus_search

Search passages already stored in the local semantic corpus.

| Argument | Type/choices | Required/default |
|---|---|---|
| `query` | str | required |
| `limit` | Annotated[int, Field(ge=1, le=10)] | 5 |
| `floor` | float \| None | None |
| `mode` | Literal['auto', 'semantic', 'lexical'] | 'auto' |
## corpus_stats

Return local corpus page and passage counts.

| Argument | Type/choices | Required/default |
|---|---|---|
## ready

Return search-source readiness, distinct from process liveness.

| Argument | Type/choices | Required/default |
|---|---|---|
## capabilities

List installed search, read, browser-drive, and extraction capabilities.

| Argument | Type/choices | Required/default |
|---|---|---|
## status

Return configured components, providers, and profiles.

| Argument | Type/choices | Required/default |
|---|---|---|
## stats

Return cache, fetch-tier, budget, and domain-health counters.

| Argument | Type/choices | Required/default |
|---|---|---|

[Documentation home](README.md) · [Agent integration](AGENT-UPGRADES.md)
