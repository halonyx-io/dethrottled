# Similar projects: Hound and free-search-mcp

2026-11-09. Read-only review for S2/S3 and cross-layer improvements. No code was
copied. Both projects are MIT-licensed.

| Project | Version / commit | What it is |
|---|---|---|
| [Hound / master-fetch](https://github.com/dondai1234/master-fetch) | `86d1b1329c0e…`, package 12.4.1 | One local MCP server for fetch, crawl, keyless search, screenshots, PDFs and OCR; HTTP first, Patchright stealth browser on block |
| [free-search-mcp](https://github.com/sweetcornna/free-search-mcp) | `2c7fee99b890…` | Local-first MCP search/fetch/documents; multi-engine RRF, FTS5 cache, date provenance, decoy-bucket detection |

## What they do that is worth studying

### Hound

- **HTTP-first escalation.** Cheap HTTP first; Patchright only when blocked or
  the page is a JS shell. One warm browser, closed after five idle minutes
  (`HOUND_BROWSER_IDLE_TIMEOUT`, default 300s) and relaunched in ~2s.
- **Memory pressure after fetch.** Sends Chrome
  `Memory.simulatePressureNotification` after each fetch to trigger GC/cache
  drop; reports RSS decreasing over sequential fetches.
- **Cache discipline.** SQLite WAL; bad content is never cached; cache size cap
  evicts oldest entries; `cache_ttl=0` forces fresh; pagination served from
  cache.
- **PDF quality.** Structured markdown with tables, headings, ToC, page ranges,
  a `quality_score`, and **CID-corruption detection**: pages whose text is
  `(cid:NNN)` garbage are rendered and OCR'd automatically.
- **Query-focused extraction.** BM25 block selection with heading-aware
  boosting and table/code preservation; avoids re-fetching.
- **Agent signals.** `content_ok`, `page_type`, `next_action`, `summary`,
  `content_age_days`/`is_stale`, `source_type`/`is_official`,
  `relevance_score`/`fetch_relevance`.
- **Search quality.** Ten keyless backends in parallel, cross-engine consensus,
  intent-aware query fan-out, six-signal ranking, source-type detection,
  per-domain diversity cap, circuit breakers and persistent warm sessions.
- **Token economy.** ~2.7K tokens for six tools, hand-written definitions and a
  one-time connect-time instruction block.

### free-search-mcp

- **Whole-bucket decoy detection.** A CAPTCHA/empty result is obvious; the
  dangerous failure is HTTP 200 results that match only the first query token.
  It measures whether the bucket mentions query terms beyond the first and only
  drops a bucket when another healthy bucket proves the query can be echoed.
- **Date provenance.** `date_source` (`structured`, `snippet`, `none`),
  `dated_results`, `freshness_note`; a snippet date is never presented as a
  verified publication date.
- **Output shaping.** Token estimates, paragraph/sentence-aware truncation,
  Markdown-first responses, tool annotations and errors that name the next step.
- **Cache and TTL.** Exact SQLite cache plus FTS5 page search; freshness and
  category-specific TTLs (news shorter than general web, weather/rates shorter
  still).
- **Search hygiene.** RRF across engines, host-canonical and title-fuzzy
  deduplication, lead snippets, category routing, engine benches/reserves.
- **Browser fallback.** Persistent Playwright context with a real Chrome
  channel and per-session viewport changes.

## What Dethrottled already covers

Dethrottled already has a stronger fetch/document/browser surface than either:
multi-tier acquisition, scoped drive with checkpoints, PDF/Office/OCR/media,
documents with offsets, corpus v1/v2, worker isolation, admission control,
warnings and `workflow.next_actions`. The useful work is therefore **bugs,
resource discipline and small quality signals**, not more tools.

## Priority 0 — bugs and efficiency (do first)

Implementation record: P0.1-P0.4 and P0.6 are implemented; P0.5 was tested and
not adopted because `old.reddit.com` failed in this stack. P1.1-P1.5 are also
implemented in [P1-AGENT-SIGNALS.md](P1-AGENT-SIGNALS.md), and the P2 exploratory
set is in [P2-EXPLORATORY.md](P2-EXPLORATORY.md). Measurements and tests
are in [P0-BUGS-EFFICIENCY.md](P0-BUGS-EFFICIENCY.md).

### P0.1 Cache growth has no enforcement

**Observed in Dethrottled:** `Cache.purge()` exists but has no callers. TTL
expiry only turns a read into a miss; expired rows remain on disk. There is no
size cap. A long-lived stack can grow the cache without bound.

**Borrowed from Hound:** bad content is not cached, cache size is capped, oldest
entries are evicted.

**Work:** periodic expired-row purge; a configurable size ceiling (start at
512 MiB); delete oldest rows when over the ceiling; compact only when needed;
report cache bytes in `/stats` or `/v2/status`; test with a tiny cap. Map to S7
and S9.

### P0.2 Browser memory and idle lifecycle

**Observed in Dethrottled:** the ten-minute soak held ~495-619 MiB in one
browser; the new crawl/drive split uses ~1.0 GiB. The browser stays warm forever.

**Borrowed from Hound:** close an idle browser after a timeout and relaunch on
demand; send a CDP memory-pressure notification after fetch/drive.

**Work:** measure `Memory.simulatePressureNotification` after `/crawl` and
`/drive`; close idle browsers after a configurable timeout; measure next-request
latency and RSS. Keep the health endpoint truthful during relaunch. Map to S8.

### P0.3 PDF CID-corruption pages are not detected

**Observed in Dethrottled:** no `(cid:` handling. A paper with broken font
ToUnicode maps can return long, confident-looking garbage and never trigger the
OCR fallback because the text length is high.

**Borrowed from Hound:** detect CID garbage, render the page and OCR it.

**Work:** detect a high `(cid:` density, force OCR for that page, preserve the
native text and add a `cid_garbage_recovered` warning; test with a synthetic
PDF or a mocked page. Map to S3/S5.

### P0.4 Error pages that look like success

**Borrowed from Hound:** universal error detection so 404/bot/auth/paywall pages
do not return fake content.

**Work:** audit a labelled set of 404, 403, 429, login, paywall, access-denied and
maintenance pages; compare `quality`, `content_status` and warnings. Fix any
case that returns `ok` with the error page as the article. Map to S2/S3.

### P0.5 Reddit is expensive

**Borrowed from Hound:** rewrite Reddit URLs to `old.reddit.com`, which is much
smaller, and skip straight to the appropriate acquisition path.

**Work:** measure bytes/CPU on a fixed Reddit thread with and without the
rewrite. Add the rewrite only if content and warnings stay equivalent. Map to
S2/S3.

### P0.6 Tool-definition token cost

**Observed in Dethrottled:** 20 MCP tools; Hound ships six tools in ~2.7K tokens.
Dethrottled's definitions and docstrings are not measured.

**Work:** add a no-dependency `tools/list` token counter (chars/4 Latin, CJK
aware), record the baseline, then trim duplicated workflow text from tool
descriptions while keeping the one-time instructions. Map to S1/S10.

## Priority 1 — correctness and agent usefulness

### P1.1 Date provenance per search result

Add `date_source` (`structured`/`snippet`/`none`), `dated_results` and a warning
when most results are undated. This prevents an undated snippet from reading as
a current fact. Map to S6/S10.

### P1.2 Source/page type and fetch relevance

Add `source_type` (`docs`/`paper`/`repo`/`blog`/`forum`/`reference`/`news`) and
`page_type` (`article`/`list`/`js_shell`) where the pipeline already knows them.
Do not add a new classifier; derive from the URL host and extraction result.
Map to S10.

### P1.3 Decoy-bucket detection

Adopt free-search-mcp's whole-bucket signal, not per-result lexical scoring.
Only drop or warn on a bucket when another healthy bucket proves the query can
be echoed. Requires a labelled query set first. Map to S2/S6.

### P1.4 Query normalization for cache identity

Collapse whitespace and normalize case for the cache key only, not the upstream
query. Measure hit-rate gain on a recorded query log. Map to S2.

### P1.5 Token estimates and boundary-aware truncation

Add an approximate token count and truncate at paragraph/sentence boundaries
where the response already reports `content_chars`. Do not change canonical
retained text or cache payloads. Map to S3/S10.

### P1.6 Reddit and error-page results in the read plan

If P0.4/P0.5 identify a repeatable failure, encode the successful recovery as a
read-plan action rather than a bespoke fetch rule. Map to S2/S3.

## Priority 2 — exploratory, only after P0/P1

### P2.1 Search consensus / multi-query fan-out

Hound's cross-engine consensus and intent-aware fan-out can improve recall, but
Dethrottled already has source profiles and ranking. Measure against the frozen
query set before adding requests or latency. Map to S6.

### P2.2 Neural reranking

Hound uses a local ONNX cross-encoder. Dethrottled deliberately ships
`rerank=false`. Run it as an experiment only; require a clear MRR/nDCG gain over
the existing lexical/corpus ranking and document the model/latency cost. Map to
S6.

**Measured:** on 100 SciFact queries, full-precision GTE reached 0.8030 nDCG@10
and 0.7837 MRR@10; universal fp32 Ettin 68M reached 0.7930/0.7699 at 261 MB and
no AVX requirement. Source order scored 0.7222/0.6913 and 1.7.1's optional BM25
ranker 0.6470/0.6108. Keep it opt-in.

### P2.3 Semantic query cache

A two-level exact+semantic cache can catch paraphrases. Use the existing
MiniLM/E5 weights, but measure false-hit precision at 0.90-0.95 and keep it in a
separate namespace from evidence retrieval. Map to S6.

### P2.4 Persistent browser profile / stealth

Hound's persistent context and JS patches improve some anti-bot flows but
conflict with Dethrottled's owner/session isolation and privacy expectations.
Needs a separate security review; do not make it the default. Map to S4/S8.

### P2.5 Proxy and key rotation

Useful for heavy search use, but Dethrottled already treats optional providers
as opt-in and must not send queries to third parties by default. Keep as an
operator option, not an automatic route. Map to S6/S9.

## Deliberately rejected as defaults

- **Title-fuzzy syndication dedup.** Dethrottled's rule that titles alone cannot
  prove syndication is correct. At most add a `possible_mirror` warning.
- **Persistent shared browser profile.** Cross-caller cookie leakage is a
  security regression.
- **Dozens of vertical search engines.** Dethrottled's source menus are bounded;
  add only a measured gap.
- **Category engine explosion / paid backends by default.** Keep the keyless,
  no-account default.

## Suggested execution order

1. P0.1 cache ceiling, P0.2 browser memory/idle, P0.3 CID OCR, P0.4 error pages.
2. P0.5 Reddit and P0.6 tool-definition tokens.
3. P1.1 date provenance, P1.2 source/page type, P1.3 decoy buckets.
4. P1.4 query normalization, P1.5 token/truncation polish.
5. P2 experiments only after the P0/P1 suite is stable.

Every item needs the paired before/after measurement in
[CANDIDATE-BENCHMARK-PLAN.md](CANDIDATE-BENCHMARK-PLAN.md); no release action is
authorised by this note.

## Sources

- <https://github.com/dondai1234/master-fetch> (MIT, 12.4.1, commit `86d1b132…`)
- <https://github.com/sweetcornna/free-search-mcp> (MIT, commit `2c7fee99…`)
