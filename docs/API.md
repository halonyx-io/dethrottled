# HTTP API

The default local base URL is `http://127.0.0.1:8787`. It serves the raw,
unauthenticated API plus interactive `/docs` and `/openapi.json`. Public REST
and MCP are optional [adapters](PUBLIC-ACCESS.md) with identity and policy checks.

The [generated HTTP reference](HTTP-REFERENCE.md) lists every documented route,
request field, default and schema constraint from the implementation. Use the
connected installation's OpenAPI/capabilities when versions differ. Unknown
request fields receive 422; cross-field validators impose additional constraints.

## Discover sources

```sh
curl -sS http://127.0.0.1:8787/v2/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"Python sqlite3 documentation","profile":"web","limit":5,"fresh":true}'
```

`/search` returns an array; `/v2/search` returns a diagnostic envelope including
empty results. First-row telemetry on the array includes attempts/ranking.
Search defaults to web; news/balanced add news, thorough adds Mwmbl and academic
adds academic sources. Explicit comma-separated `engines` selects sources.
`categories="news"` and `language` remain supported controls. Use plural
`categories`; a misspelled field is not an engine choice.

Source order is default. `rank=true`/`ranking="bm25"` selects lexical ranking;
`ranking="fusion"` combines source and lexical order. `prefer_domains`, `recency`
and stored `corpus` candidates are explicit refinements. Neural `rerank=true`
is rejected. Optional keyed engines are never implicitly added to defaults.

## Read known URLs

```sh
curl -sS http://127.0.0.1:8787/fetch \
  -H 'Content-Type: application/json' \
  -d '{"urls":["https://docs.python.org/3/library/sqlite3.html"],"focus":"in-memory database","max_chars":8000}'
```

`/fetch` and `/extract` read one to ten URLs. `format` is `text`, `links` or
`html`; `/extract-with-links` retains links. REST accepts legacy `raw`/`links`
booleans; MCP uses canonical `format`. `focus` requires text format.

`render=auto|always|never` controls rendering; legacy booleans map true to
always and false to auto. `always` prioritizes Crawl4AI; `never` and read profile
`fast` prohibit rendering. Fetch profile defaults to balanced; thorough also
requests headed fallback. Challenges and script-only shells can trigger headed
recovery automatically. `headed_fallback=true` additionally requests it for other
failures. `wait_for` is a CSS readiness selector; `render_delay` configures the
Crawl4AI delay and is not a guarantee of complete dynamic content.

`fresh=true` refreshes/replaces cache entries. `cache_mode=use|refresh|bypass`
and `max_age` provide finer control; bypass neither reads nor writes.
`recovery=manual` disables the higher-level navigation/asset recovery layer,
not the underlying transport ladder. Explicit render and OCR restrictions remain
in force. See [reading and evidence](DEPENDABLE-WORKFLOWS.md) for file ranges,
OCR, captions, speech, retained text and source inspection.

## Interpret a read

| Field | Meaning |
|---|---|
| `quality` | `ok`: extracted; `thin`: short HTML with uncertain coverage; `suspect`: possible error-banner pollution retained after recovery; `failed`: no useful read |
| `tier` | Acquisition/extractor path, such as `headed/trafilatura` |
| `failure_reason`, `acquisition_attempts` | Actual failures and attempted tiers; a cache hit is not an invented acquisition |
| `warnings`, `extraction`, `source_partial` | Parser/OCR/layout limits and incomplete source coverage |
| `truncated`, `content_chars`, continuation | Response/source bounds; inspect alongside extraction metadata |
| `document_id`, `document_sha256` | Scoped retained version for continuation and citations |
| `workflow.next_actions` | Relevant follow-ups with exact tool names and arguments |
| `browser_recovery` | Queue/poll timing, ready state, checkpoint restoration and initial navigation |
| `content_assessment` | Non-destructive error-banner signals, exact full-extraction spans and text hash; not an answer verifier |

HTTP 200 does not mean every URL succeeded. Extraction success does not verify
the answer or complete source coverage. `response_format="concise"` reduces
duplicate representations; detailed is default and warnings/provenance remain.

`content_assessment.pollution` is `suspected`, `none_detected` or `not_assessed`.
Structured documents are not classified as website UI. A narrow set of leading
error instructions and small source HTML alert containers can flag mixed content;
quoted/code examples are excluded where identifiable. Unknown phrases and languages
can be missed. `none_detected` does not certify clean text. `completeness` remains
`unknown` and `usable_content` remains `unverified`.

Each span supplies `start`, `end`, `quote`, `kind`, `signal` and
`offset_in="full_extraction"`. Positions are Unicode character offsets in the full
retained extraction identified by `text_sha256`, before focus, clipping or HTML/link
output transforms. They may lie outside the returned excerpt. Use the retained
document to inspect the range. `unflagged_chars` counts characters outside suspect
spans; it does not measure usable evidence.

Suspect HTML automatically continues through available acquisition tiers, including
the headed browser when allowed and within budget. A substantial clean extraction
is preferred; if recovery fails, the mixed text is retained with `quality="suspect"`,
warnings and `workflow.state="needs_inspection"`. Short clean fragments do not silently
replace a richer mixed result. `render="never"` and the fast profile prevent rendering.
Cache hits retain diagnostics without pretending to attempt fresh recovery; old cached
text is assessed on read, with HTML-only signals unavailable if no HTML was retained.
Non-cache acquisition attempts include `elapsed_ms` and extraction assessment summaries
when text was produced. An attempted browser tier is not proof of successful navigation.

`research` returns suspect reads under `partial_sources`, preserving their content,
warnings and document references while seeking clean `sources`. These partial reads
are not silently indexed into the corpus or counted as clean evidence.

## Combine discovery and evidence

`POST /search-and-fetch` (alias `/search-and-extract`) ranks/selects before
reading and returns search metadata with each extraction outcome. OCR controls
are explicit; it is not a general prohibition on OCR in combined reads.

```sh
curl -sS http://127.0.0.1:8787/research \
  -H 'Content-Type: application/json' \
  -d '{"question":"How does Python sqlite3 create an in-memory database?","max_sources":4}'
```

Research defaults to thorough discovery. Supply up to three facet queries in
addition to the question. It returns source IDs, evidence windows, query
attempts, skipped sources and `coverage.facets`. Term matches are not semantic
verification; no model writes the answer. Two research requests can run at once;
excess work returns a typed 429 with a retry hint.

## Continue, inspect or operate

| Need | Routes |
|---|---|
| Retained text/focus or reparse | `POST /documents/read` |
| Exact blocks/citations/structure | `POST /documents/structure` |
| Supported source pixels | `POST /documents/image` |
| Bounded site traversal | `POST /site/crawl` |
| Durable read batches | `POST /jobs/fetch`, `/jobs/read`, `/jobs/resume`, `/jobs/cancel` |
| Browser interaction, downloads and app data | `POST /drive` |
| Stored semantic/lexical retrieval | `GET /corpus/search`, `/corpus/stats` |

[Browser operation](DRIVE.md) explains actions, state and replay. Public adapters
force caller namespaces and public-target policy; callers cannot impersonate
another identity with raw internal `evidence_namespace`/`public_only` fields.

## Diagnose the installation

`/health` proves liveness. `/ready` reports search-source readiness;
`/v2/status` probes configured workers and backfill; `/v2/capabilities` publishes
formats, providers and the agent contract. `/stats` includes cache/tier health,
renderer and headed admission. No single green health route proves web coverage.
Record request IDs, exact controls, timing and returned warnings for a failed task.

[Documentation home](README.md) · [Agent guide](AGENT-UPGRADES.md) · [API](API.md) · [Evidence](EVIDENCE.md)
