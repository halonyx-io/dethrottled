# Ideas from similar projects

2026-11-09. Read-only review of two open-source projects for S2/S3 improvements.
No code was copied; both are MIT-licensed and this note records design ideas and
the tests that would justify adopting them.

- **mcp-web-hound** (`ilgizar-valiullin/mcp-web-hound`): unified MCP search with
  provider fallback, exact + semantic cache, NLI reranking and rate budgets.
- **free-search-mcp** (`sweetcornna/free-search-mcp`): local-first MCP search,
  fetch and document reading with multi-engine RRF, FTS5 cache, date provenance,
  decoy-bucket detection and LLM-shaped output.

"hound" is ambiguous; the code-search, GPS and BloodHound projects are not
comparable to this retrieval stack. The review below uses `mcp-web-hound`.

## What Dethrottled already does

| Idea | Dethrottled status |
|---|---|
| Multi-engine search with fallback | Already has DDG/SearXNG/browser sources, engine rest and bounded menus |
| Exact search/extraction cache | Already has SQLite cache with TTL and validators |
| Reuse extracted text | Already has documents, corpus, focus excerpts and offsets |
| Reader-mode extraction | Already Trafilatura/Resiliparse/Selectolax cascade |
| Tool errors with next steps | Already has `workflow.next_actions` and structured failure reasons |
| Provider health/backoff | Already has engine health and cooling |
| Rate/budget gates | Already has admission, concurrency and search budgets |
| PDF/Office/OCR/media | Already broader than either project |
| Browser/drive | Already a first-class scoped browser, stronger than either |

The useful gap is therefore in **search-result quality signals**, **cache
freshness**, and **small output-shaping details**, not in basic fetch coverage.

## Implemented this round

### News search cache ceiling (Hound/free-search-mcp)

Hound shortens TTLs by query intent; free-search-mcp does the same for
`freshness=day/week/month`. Dethrottled kept every search result for six hours,
including `categories="news"` and `profile="news"`.

Implemented: news searches now use a **30-minute** search-cache ceiling; a
tighter caller `max_age` still wins. Capabilities expose
`news_cache_ttl_seconds`, and the agent playbook documents the behaviour. Tests
cover news, profile-news, tighter caller bounds and the unchanged general case.

This is a low-risk freshness improvement, not a ranking claim.

## Prioritized ideas still to evaluate

### P1. Whole-bucket decoy detection

**Source:** free-search-mcp `coherence.py`.

Some engines answer HTTP 200 with well-formed results that match only the first
query token (Bing returning the game "Rust" for "rust ownership borrowing"). Per
result lexical scoring was measured and rejected there; the useful signal is the
whole bucket.

**Proposed test:** capture real provider buckets for a fixed query set, label
healthy vs decoy, compute the share of results mentioning a non-first query term.
If Dethrottled's sources separate cleanly, add a bucket-level warning/drop that
only removes a bucket when another healthy bucket proves the query can be
echoed. Never drop a bucket on a single result.

**Value:** search precision and fewer confidently wrong source menus.

### P2. Date provenance per search result

**Source:** free-search-mcp `date_source`, `dated_results`, `freshness_note`.

Dethrottled carries `publishedDate` but does not say whether it came from
structured metadata or was parsed from a snippet, and does not summarise how many
results are dated.

**Proposed test:** for a fixed result set, classify dates as `structured`,
`snippet` or `none`, compare with hand-labelled dates. Add `date_source`,
`dated_results` and a warning when most results are undated. Keep the existing
date value unchanged.

**Value:** agents stop treating an undated snippet as a current fact. This fits
Dethrottled's existing warning-first design.

### P3. Search query normalisation for cache keys

**Source:** mcp-web-hound query normaliser.

Dethrottled cache keys use the raw query. Collapsing whitespace and normalising
case for cache identity (not for the upstream query) would turn
`"python  asyncio"` and `"Python asyncio"` into one cache entry.

**Proposed test:** cache hit-rate improvement over a recorded query log, with a
check that upstream query text and ranking are unchanged. Low risk; do not
normalise semantically or strip operators.

### P4. Token estimate and boundary-aware truncation

**Source:** free-search-mcp `formatting.py`.

Dethrottled reports characters and truncation but not an approximate token cost,
and some paths still cut at a character boundary. A cheap CJK/Latin char
heuristic plus paragraph/sentence-aware truncation would help agents budget and
avoid half-sentences.

**Proposed test:** measure truncation boundary quality and token-estimate error
on English/CJK fixtures. Add estimates only where the response already reports
`content_chars`; do not change canonical retained text.

### P5. Semantic search cache

**Source:** mcp-web-hound two-level cache.

Exact cache misses on paraphrases. A semantic layer would need an embedding
model and a similarity threshold; Dethrottled already has MiniLM/E5 weights for
the corpus, so the marginal model cost is small but the false-hit risk is real.

**Proposed test:** fixed paraphrase pairs and unrelated-topic pairs; measure hit
precision/recall at thresholds 0.90-0.95. Only adopt if precision is very high
and the cache namespace is separate from evidence retrieval. This is a larger
change than P1-P4 and should not be bundled with release work.

### P6. NLI reranking

**Source:** mcp-web-hound NLI reranker (DeBERTa-v3-xsmall).

Dethrottled deliberately ships `rerank=false` and a deterministic lexical/
corpus ranking. A neural reranker adds a model, latency and a new failure mode.
It would need a controlled MRR/nDCG gain over the existing ranker before it is
worth considering. Keep this as an experiment, not a default.

### P7. Title-fuzzy syndication dedup

**Source:** free-search-mcp title/host canonical dedup.

This conflicts with Dethrottled's deliberate rule that titles alone cannot prove
syndication and independent URLs are preserved. Do not adopt it as a default.
A safer variant is a warning-level `possible_mirror` annotation, never a silent
merge.

### P8. Persistent browser profile

**Source:** free-search-mcp `launch_persistent_context`.

Persistent cookies improve some anti-bot flows but create a privacy and
cross-caller isolation problem. Dethrottled already has checkpoints and
owner-scoped sessions. Do not make the shared browser profile persistent without
a separate security review.

## Not worth adopting

- **Download/paper-graph tool surfaces:** Dethrottled's drive downloads and
  research coverage already cover the use case.
- **Hand-rolled MCP transport / no SDK:** Dethrottled's adapter contract is
  settled.
- **Category engine explosion:** Dethrottled's profiles and source menus are
  already bounded; adding dozens of vertical engines would increase latency and
  maintenance without a measured gap.

## Suggested order

1. P2 date provenance and P3 query normalisation (small, testable).
2. P1 decoy buckets (quality gain, needs a labelled set).
3. P4 token/truncation polish.
4. P5 semantic cache and P6 NLI only as separate experiments.

Each item gets a paired before/after measurement and the same
[benchmark rules](CANDIDATE-BENCHMARK-PLAN.md). None of these authorise a release.

## Sources

- <https://github.com/ilgizar-valiullin/mcp-web-hound> (MIT)
- <https://github.com/sweetcornna/free-search-mcp> (MIT)
