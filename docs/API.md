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
  -d '{"query":"Python sqlite3 documentation","profile":"web","limit":10,"fresh":true}'
```

`/search` returns an array; `/v2/search` returns a diagnostic envelope including
empty results. First-row telemetry on the array includes attempts/ranking.
The envelope retains legacy `status` (`ok` or `no_results_or_degraded`) for existing
clients. Use additive `outcome` (`results`, `partial_results`, `no_results`,
`unavailable`, `indeterminate`), `degraded` and `discovery.providers` for precise
interpretation. `no_results` requires successful empty provider responses; unknown
or failed discovery is not silently classified as an empty web. Partial useful
results keep their original order. Attempts retain acquisition-path failures,
HTTP status, refusal/cooldown diagnostics and provider provenance.
MCP callers select this envelope with `search(diagnostics=true)`; successful
tool execution is distinct from discovery health. The legacy MCP search return
can carry the envelope in a JSON text block rather than `structuredContent`.
In the unreleased candidate, research `queries` also preserve `outcome` and
`degraded` per query, including `indeterminate` for a local search exception.
Search defaults to `profile="web"`: DDG Lite/HTML/TLS/browser acquire up to ten
primary choices while SearXNG Yahoo and Yandex each contribute up to three.
The normal menu defaults to and is capped at **15 unique URLs**. Duplicate
supplements do not displace primary choices. Source order is preserved, with
novel Yandex/Yahoo choices alternating after DDG. Partial provider failures leave
healthy sources available; fewer than fifteen results is normal.

`profile="fast"` uses DDG alone. `balanced` uses the normal web combination;
`thorough` also requests Mwmbl. Explicit news and academic profiles retain their
specialist sources. `engines="web"` deliberately requests only the primary route;
`engines="web,yandex,yahoo"` explicitly requests the default combination.
`categories="news"` and `language` remain supported controls. Unknown fields and
requests above fifteen are rejected. Existing cached provider rows obey the caps.

SearXNG supplements use separate explicit engine calls and one first page, with
`language="all"` when no language is supplied. Their SERPs may contain more rows,
but Dethrottled admits at most three per engine. No search pagination or article
fetching is triggered just to fill a menu. DDG acquisition alternatives count as
one provider family. Provenance records supplementary engine, original rank and
page before URL deduplication. Bing/Brave/Google are not automatic web supplements.

Source order is default. `rank=true`/`ranking="bm25"` selects lexical ranking;
`ranking="fusion"` combines source and lexical order. `prefer_domains`, `recency`
and stored `corpus` candidates are explicit refinements. Neural `rerank=true`
is rejected. Optional keyed engines are never implicitly added to defaults.
The [ranking evaluation](../evaluations/search-policy/results/2026-11-03/REPORT.md)
does not justify adding XGBoost or semantic inference to the default runtime.

Research uses up to fifteen choices per query and interleaves facets into a
**24-URL global candidate pool**. `max_sources` defaults to ten and allows up to
twenty. It selects at most `max_sources + 4` primary URLs (never above 24), using
replacement candidates only when reads fail or duplicate earlier content.
This ceiling concerns selected primary URLs; automatic transport recovery and
optional attachment reading can make additional acquisition attempts. Known-URL
fetching and retained-document text limits are separate from discovery menus.

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

Ordinary text reads use the [autonomous read planner](READ-PLANNER.md) after initial
acquisition. `read_plan.decisions` records the selected strategies, triggers, timings
and adoption outcomes. `read_plan.stop_reason` explains why recovery stopped; it does
not verify an answer. Retain `acquisition_url` and publisher-alternative provenance.

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
can be missed. `none_detected` does not certify clean text. `usable_content` stays
`unverified`. Completeness is `unknown`, or `suspected_incomplete` when multiple
substantive structural samples remain absent. Neither is a completeness proof.

For long structured HTML, `extraction.completeness` records whether structural
sampling ran, how many anchors were sampled/missed, which extractors were compared,
and whether selection changed. Missing samples selectively trigger alternate
extraction before response clipping; normal successful pages do not run every
extractor. An alternate must retain every previously matched sample and add coverage.
Known furniture is excluded; ambiguous or unstructured material can remain missed.
Warnings and canonical-text offsets remain available. This does not automatically
repeat browser actions: a local extraction gap is not evidence that rendering again
will help. `workflow.state=needs_inspection` surfaces unresolved suspected gaps.

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

Research defaults to web-only discovery. Supply up to ten facet queries in
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
| Stored semantic/lexical/hybrid retrieval | `GET /corpus/search`, `/corpus/stats` |

[Browser operation](DRIVE.md) explains actions, state and replay. Public adapters
force caller namespaces and public-target policy; callers cannot impersonate
another identity with raw internal `evidence_namespace`/`public_only` fields.

## Diagnose the installation

`/health` proves liveness. `/ready` reports recent real-search observations,
separating primary discovery from supplements/news. Status reads issue **no upstream
search probes**. Cold or stale observations are `unknown`; successful cached results
do not establish fresh upstream availability. The observation window is 60 seconds.
Use one normal search to obtain current evidence, rather than polling readiness.
`ddg_family` distinguishes active cooldown from recovery due; timer expiry does not
establish recovery. Worker liveness is reported separately;
`/v2/status` probes configured workers and backfill; `/v2/capabilities` publishes
formats, providers and the agent contract. `/stats` includes cache/tier health,
renderer and headed admission. No single green health route proves web coverage.
Record request IDs, exact controls, timing and returned warnings for a failed task.

[Documentation home](README.md) · [Agent guide](AGENT-UPGRADES.md) · [API](API.md) · [Evidence](EVIDENCE.md)

[Corpus v2](CORPUS.md) adds public-admission reports,
coverage/provenance, explicit `mode=hybrid`, domain filtering, and durable-job
status. `support=standard` checks model/source agreement or query terms;
`support=broad` includes warned single-model candidates when more coverage is
needed. Neither verifies that an answer is present. Existing response envelopes
and the ten-result limit remain.

## Outbound domain-filter diagnostics

The unreleased [adblock candidate](ADBLOCK.md) adds `adblock` state to capabilities,
status and stats. Refused fetches retain `quality=failed`, add
`policy_blocked=adblock` and an `adblock_blocked:` failure reason. Their workflow
has `state=policy_blocked` with no retry actions. This is distinct from an upstream
network failure. No new request arguments or endpoints are required.

## Unreleased corpus diagnostics

`GET /corpus/stats` is the canonical stats route; `v2` describes the corpus schema,
not a `/v2/corpus` HTTP namespace. Capabilities advertise `corpus.endpoints`.
For schema 2 the stats envelope adds `lifetimes`: search/extraction cache default
TTLs, actual document TTL/size policy, configured corpus days and independent-clock
semantics. Existing `models`/`index` fields and schema-1 responses are preserved.
See [lifetime diagnostics](CORPUS.md#lifetimes-are-independent).
