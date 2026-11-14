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
In 1.6.0, research `queries` also preserve `outcome` and
`degraded` per query, including `indeterminate` for a local search exception.
Search defaults to `profile="web"`: DDG Lite/HTML/TLS/browser acquire up to ten
primary choices while SearXNG Yahoo and Yandex each contribute up to three.
The normal menu defaults to and is capped at **15 unique URLs**. Duplicate
supplements do not displace primary choices in the candidate menu. Before
reranking, novel Yandex/Yahoo choices alternate after DDG. Partial provider failures leave
healthy sources available; fewer than fifteen results is normal.

`profile="news"` is the exception to primary-first order: dated news engines
(DuckDuckGo News, Google News, Qwant News, Reuters, Bing News) lead, interleaved,
inside the same caps, fresh stories (dated within a week) first, then undated,
then older, with front pages, social posts and headline roundups last and at
most two leading places per site; `ordering` in that metadata counts each,
and undated front and topic pages go last. `policy.engine_order` in the search
metadata shows the order used and any engine demoted for low dated yield.

Search rows carry additive `source_type`, `fetch_relevance`, `snippet_tokens`,
`date_source` (`structured`, `snippet`, `none`), `published_age_days`,
`engines_consensus` and `consensus_score`.
Use `published_at` for a parseable provider-reported calendar date. `date_hint`
separately labels provider or snippet text. A relative snippet date ("3 days
ago") is resolved when the result is captured: the hint keeps the original text
as `value` and adds `resolved`, `precision` and `observed_at`. Both are
unverified. Fetch the source when the publication date is material.
A date more than a day in the future, or a snippet date that contradicts a
provider date for the same page, is reported under `date_hint_rejected` instead
of being used.
`/v2/search`, and the first row of `/search`, also expose `dated_results`,
`date_coverage` (`provider`, `page`, `snippet`, `none`, `rejected` counts for the
returned rows), `deduplication`, `freshness_note` and `decoy_buckets`. A snippet
date is a lead, not a verified publication date.

One page reached under several addresses (scheme, `www`/`m`/`amp` host,
tracking parameters, index page, query order) is one result. The first copy
keeps its place and absorbs what the others carried: a missing date or snippet
and their provenance. A copy at a different address is listed under the row's
`duplicates` (`url`, `provider`, `reason`); `deduplication` counts the merges. A decoy bucket is dropped only when another provider proves the
query can be echoed.

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

Provider order is the baseline. `rank=true`/`ranking="bm25"` selects lexical ranking;
`ranking="fusion"` combines source and lexical order. `prefer_domains`, `recency`
and stored `corpus` candidates are explicit refinements. Neural `rerank=true`
is rejected as a request flag. Compose enables the local Ettin reranker by default.
Check `ranking.rerank` in capabilities and `neural_score` and the ranking trace
in search responses. Provider ordering remains available on model failure.
Optional keyed engines require explicit selection.
The [ranking evaluation](../evaluations/search-policy/results/2026-11-03/REPORT.md)
records the earlier comparison of lexical and fusion policies.

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
always and false to auto. `always` prioritizes browser rendering; `never` and read profile
`fast` prohibit rendering. Fetch profile defaults to balanced; thorough also
requests headed fallback. Challenges and script-only shells can trigger headed
recovery automatically. `headed_fallback=true` additionally requests it for other
failures. `wait_for` is a CSS readiness selector; `render_delay` configures the
renderer delay and is not a guarantee of complete dynamic content.

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
| `content_assessment` | Non-destructive error-banner and gate-page signals, exact full-extraction spans and text hash; not an answer verifier |
| `source_type`, `page_type` | URL-shape source class and extraction shape (article/list/document/unreadable) |
| `date_source`, `published_age_days` | `page` when the page declares a date (meta, JSON-LD, microdata or the extractor's reading), otherwise `none`; and its age. A future date, or an extractor's guess whose year appears nowhere in the page, is reported under `date_hint_rejected` |
| `page_metadata.published`, `page_metadata.modified` | Publisher-declared publication and modification dates, as written |
| `tokens_estimated` | Character-based approximate LLM token cost, not a tokenizer count |
| `gate_page:*` warning | Login, paywall, access-denied or maintenance wall; content may be partial even when long |

Batch reads keep input URL order and at most four active reads per request;
completed slots are refilled while slower reads continue. Link-format output
resolves relative anchors against the final acquired URL after redirects.

Malformed or incompatible cached search/extraction records fall through to
normal acquisition instead of becoming evidence. Valid cached empty search lists
remain hits; the cache lifetimes and request freshness controls still apply.

HTTP 200 does not mean every URL succeeded. Extraction success does not verify
the answer or complete source coverage. `response_format="concise"` reduces
duplicate representations, including full-document PDF text-layer blocks that
would otherwise bypass the excerpt limit. Page numbers, methods, text counts,
warnings, retained-document handles and continuation remain. REST defaults to
`detailed`; MCP fetch, research and document reads default to `concise`. Request
`detailed` explicitly when you need block text and coordinates. Concise mode does
not shorten the canonical retained document or certify completeness. For detailed
layout from a long PDF, reparse a small explicit page range rather than requesting
all page blocks at once. Detailed fetch, retained-read, job and research source
responses add `large_detailed_response` to `warnings` when known text
representations total at least 131,072 characters. This is a conservative
lower bound, not an exact JSON-size measurement; other metadata can also be
large. The warning recommends `response_format=concise` and `max_chars`; it
does not discard detailed fields or alter retained evidence.

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
attempts, skipped sources and `coverage.facets`. A read that is the same page
as an accepted source (same address, or a same-site declared canonical) or has
the same or nearly the same text is skipped as `duplicate_content` with
`duplicate_of` and `duplicate_reason` (`same_url`, `same_text`, `near_text`);
the kept source lists it under `duplicates`, and `summary.deduplication` counts
them. Texts under 80 words are never treated as copies. Term matches are not semantic
verification; no model writes the answer. Two research requests can run at once;
excess work returns a typed 429 with a retry hint.

## Continue, inspect or operate

| Need | Routes |
|---|---|
| Retained text/focus or reparse | `POST /documents/read` |
| Exact blocks/citations/structure | `POST /documents/structure` |
| Supported source pixels | `POST /documents/image` |
| Bounded site traversal | `POST /site/crawl` |
| Programmatic resolve and bulk exports | [DPR](DPR.md), `POST /v1/dpr/jobs`, `POST /v1/dpr/resolve` |
| Retained metadata and version comparison | `POST /documents/status` or MCP `document_status` |
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
renderer and headed admission, waymark and engine-policy counts. Domain names in
`domain_health` are shown only to the local operator; adapter callers get counts. No single green health route proves web coverage.
Record request IDs, exact controls, timing and returned warnings for a failed task.

[Documentation home](README.md) · [Agent guide](AGENT-UPGRADES.md) · [API](API.md) · [Evidence](EVIDENCE.md)

[Corpus v2](CORPUS.md) adds public-admission reports,
coverage/provenance, explicit `mode=hybrid`, domain filtering, and durable-job
status. `support=standard` checks model/source agreement or query terms;
`support=broad` includes warned single-model candidates when more coverage is
needed. Neither verifies that an answer is present. Existing response envelopes
and the ten-result limit remain.

## Outbound domain-filter diagnostics

The [native adblock layer](ADBLOCK.md) adds `adblock` state to capabilities,
status and stats. Refused fetches retain `quality=failed`, add
`policy_blocked=adblock` and an `adblock_blocked:` failure reason. Their workflow
has `state=policy_blocked` with no retry actions. This is distinct from an upstream
network failure. No new request arguments or endpoints are required.

## Corpus diagnostics

`GET /corpus/stats` is the canonical stats route; `v2` describes the corpus schema,
not a `/v2/corpus` HTTP namespace. Capabilities advertise `corpus.endpoints`.
For schema 2 the stats envelope adds `lifetimes`: search/extraction cache default
TTLs, actual document TTL/size policy, configured corpus days and independent-clock
semantics. Existing `models`/`index` fields and schema-1 responses are preserved.
See [lifetime diagnostics](CORPUS.md#lifetimes-are-independent).

## Corpus discovery and candidate diagnostics

`GET /v2/capabilities` exposes `corpus.requests.search` and `.stats` alongside the
unchanged `corpus.endpoints`. Search requires the REST query parameter `q`, for
example `GET /corpus/search?q=land%20patent&mode=lexical`; MCP names it `query`.
The search envelope reports `result_kind=retrieval_candidates`, a `support_note`
and `answer_support=unverified`. Schema-2 hits add bounded `query_anchors` literal
overlap diagnostics. Neither counts, overlap nor model agreement verify answers.
See [corpus semantics](CORPUS.md#candidates-are-not-answer-coverage).

## Request discovery, crawl outcomes and progressive jobs

`/v2/capabilities.request_contracts` is generated from OpenAPI and describes
methods, required/accepted body fields and query names. It complements the
corpus-specific example without duplicating a hand-maintained parameter list.
REST names differ deliberately: `question` for research, `query` for search, `q`
for corpus lookup, `urls` for fetch/crawl/job submission, `document_id` for retained
reads and `job_id` for job polling. Use `limit`, not an invented `maxResults`.

`/site/crawl` identifies `operation=site_crawl` and reports `outcome=pages_read`,
`partial` or `no_ok_pages`, alongside the existing `sources`, coverage ledger and
continuation URLs. `no_ok_pages` means no attempted source was rated `quality=ok`;
it does not erase thin/suspect evidence. Short navigation pages can still supply
bounded same-origin links. Per-source warnings and policy refusals are retained.
The legacy `coverage.failed` count includes every non-`ok` row. HTTP 200 means the
bounded traversal ran, not that pages were acquired or an answer was verified.

The same distinction applies to batch fetches and jobs. Inspect each URL's
quality/failure diagnostics. Job `completed` counts finished positions, including
failed reads; a running 1/2 job may legitimately await its second URL. Poll using
`next_cursor`/`poll_after_ms` and preserve each returned source's outcome.

## Constrain source choices

`/search`, `/v2/search`, `/search-and-fetch` and `/research` accept `domains` and
`exclude_domains` (up to 20 hostnames each). Includes match the exact hostname and
its subdomains; exclusions win. Use hostnames, not URLs, ports or wildcards.
Internationalized hostnames are normalized to IDNA. Includes intersect existing
`site:` operators; they do not broaden them. `prefer_domains` remains a ranking
preference and is not a filter.

```sh
curl -sS http://127.0.0.1:8787/v2/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"climate observations","domains":["nasa.gov","noaa.gov"],"exclude_domains":["blogs.nasa.gov"],"limit":10}'
```

Constraints rewrite the provider query and validate candidate hostnames before
provider/menu caps, including corpus additions. Filtering scans the already acquired
first page; it adds no automatic searches or pagination. Providers may ignore query
operators, so fewer matching sources is normal. Diagnostics preserve provider
failures and add `constraint_outcome=no_matching_candidates` if no eligible sources
survive. This does not prove that the wider web has no matching sources. Mutually
exclusive constraints return `outcome=constraints_unsatisfiable` without an upstream
request. Use the diagnostic envelope to inspect empty responses.

## Extract named HTML fields

`/fetch` and its `/extract` alias accept `selectors`, a dictionary of named CSS
field specifications. This is deterministic text/attribute extraction, not JSON
Schema inference or an LLM. It works for non-agent applications too.

```sh
curl -sS http://127.0.0.1:8787/extract \
  -H 'Content-Type: application/json' \
  -d '{"urls":["https://example.org"],"response_format":"concise","selectors":{"title":{"selector":"title"},"destinations":{"selector":"a[href]","attribute":"href","all":true,"required":false,"max_matches":10}}}'
```

Each specification has `selector`, optional `attribute` (otherwise text), `all`
(default false), `required` (default true), `max_matches` (20, at most 100), and
`max_chars` (2,000, at most 10,000 per value). Up to 32 fields and 64,000 total value
characters are returned. Attribute values are literal source values: relative links
remain relative. Selectors run on acquired HTML, independently of the prose excerpt;
requesting them bypasses the prose-only extraction cache because it contains no HTML.
The usual acquisition and recovery policy still applies. Recovered non-HTML evidence
may have no eligible HTML; no second request is invented to satisfy the fields.
Small acquired HTML documents remain eligible for selectors even when there is
too little prose for the article extractors. Selector success does not upgrade
short prose to `quality=ok`; clipped HTML retains its partial-source flag.

Results add `structured`, `structured_status` and `structured_provenance` (selectors,
match counts, acquired HTML hash, source URL and retained document handle when present).
Missing required fields do not change `quality`; their values are null or empty lists.
Check `satisfied`, `missing`, `reason` and `truncated_fields` independently of transport
and prose quality. HTML selectors are not canonical prose offsets. Invalid selector
syntax or malformed specifications receive 422 before acquisition; unsupported
`schema` inference is rejected. Fetch jobs accept the same specifications.

## Map candidates before reading a site

`POST /site/crawl` and MCP `crawl_site` accept `mode="map"`; omitted mode preserves
existing crawling. `max_pages` limits the returned URL menu (default 10, maximum 50).
`max_discovery_requests` separately limits seed/nested-sitemap acquisitions (default
5, maximum 20); `max_depth` bounds nested sitemap traversal. Mapping reads supplied
HTML seeds and sitemap indexes/urlsets, but does not recursively fetch each linked
HTML candidate or automatically guess sitemap locations. Supply a known sitemap as
a seed when useful. Same-origin/path-prefix scope and public-target policy remain.

```sh
curl -sS http://127.0.0.1:8787/site/crawl \
  -H 'Content-Type: application/json' \
  -d '{"urls":["https://example.org/sitemap.xml"],"mode":"map","max_pages":10,"max_discovery_requests":3,"render":"never"}'
```

Map sources are URL candidates, without evidence quality or document IDs. No corpus
indexing or retained evidence is created. `coverage.attempted=0` counts evidence
reads, **not network requests**: inspect `discovery_requests`, `discovery_attempts`,
failures, truncation, frontier and limits. Acquisition may still use more than one
tier per discovery URL. The existing ladder/parser is reused; this is not a new
zero-cost HTML transport. Follow selected candidates with fetch. Sitemap exhaustion
never establishes whole-site completeness.

Field status also reports `source_html_partial` when the acquired DOM/HTML was
clipped; filled fields do not establish completeness. When browser recovery adopts
a new DOM, selectors use that adopted capture rather than stale initial HTML.

Malformed URL and explicit network-policy refusals stop further automatic attempts;
`policy_blocked=network` distinguishes the latter from an upstream outage. Their
workflow gives no transport retry. Ordinary connection/DNS failures retain bounded
recovery rather than being declared permanent after an arbitrary short timeout.
