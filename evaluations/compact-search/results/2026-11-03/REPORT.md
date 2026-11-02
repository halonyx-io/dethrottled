# Compact source choices — 3 November 2026

This policy replaces 1.1.3's supported larger discovery requests. It implements
an explicit product constraint on agent context, not a new accuracy claim or a
claim that a particular language model necessarily suffers lost-in-the-middle
at a particular number of URLs. Historical larger-pool evaluation records remain
unchanged.

The shared DDG Lite/HTML/TLS/browser family contributes at most **ten** choices.
Every supplementary engine contributes at most **three**, with **six** supplements
total and **sixteen** unique choices in the complete menu. Normal discovery and
research default to web-only. Bing/Brave are not automatic general-web supplements;
the headed discovery race now uses only DDG Lite/HTML. The direct DDGS fallback
default is DuckDuckGo, not its opaque multi-engine `auto` selection. Deliberately
configured other DDGS backends receive the three-choice supplementary budget.

The limit is applied before requesting cheap/browser discovery, when consuming
worker/cache results, and at final API ranking. It is not just response truncation.
Browser discovery reads one result page and does not automatically paginate to
fill a larger request. The worker rejects `limit=50`; direct internal helpers
clamp oversized requests too. Optional ranking cannot create a fifty-row pool.

SearXNG results are limited per engine after canonical deduplication. Supplement
budgets do not reset for cached results or acquisition aliases. Bing News RSS
and SearXNG Bing News share one normalized family. A new URL is not treated as
proof that a supplementary result is relevant.

Research interleaves query candidates into one shared family/menu budget before
selection, reads and the coverage ledger. Each facet does not contribute another
visible ten-choice menu. Its summary counts unique admitted candidates. Requested
source counts above sixteen are rejected. Source quality, failures and incomplete
coverage remain explicit; the bounded ledger is not an exhaustive search census.

Drive snapshot/network-list steps accept at most ten items; Bing snapshots are
further capped at three. Narrow selectors can inspect different controls. This
limits inspection lists, not the amount of a document an agent can read. Local
corpus search also returns at most ten matches. HTML/text reading, retained-document
continuation, OCR and file-format coverage are not reduced by the search policy.

## Controlled checks

- Oversized worker response: fifty DDG rows become at most ten, fifty browser
  Bing rows become at most three. Cached overdelivery obeys the same budgets.
- Ten cheap DDG rows do not launch browser breadth recovery for a fifty-row
  internal request.
- Lite/TLS/browser variants share one ten-row quota; each supplementary engine
  has three and the complete unique pool has sixteen.
- Oversized SearXNG live/cache responses are limited per engine.
- Research mocks provide distinct candidate URLs across eleven query facets;
  only sixteen unique candidates reach reads and the coverage ledger, with ten
  DDG and six supplementary choices total.
- HTTP/MCP/worker oversize requests are rejected. Snapshot50 is rejected; local
  corpus requests cannot return fifty matches even if a backend overdelivers.
- A real headed-browser fixture with pagination controls verifies ten DDG /three
  Bing extracted choices and no automatic next-page requests.

The full-image suite and adapter tests are recorded with the release. Native
AMD64/ARM64 CI gates promotion. These checks establish enforcement of the policy,
not universal retrieval accuracy.

## Small live supplementary check

An isolated default Compose project used fresh volumes, the actual API/browser/
SearXNG images and no GPU override. These five requests are functional checks,
not a new held-out ranking benchmark:

| Request | Returned DDG | Supplement | Total |
|---|---:|---|---:|
| Python pathlib recursive glob, web | 10 | None | 10 |
| Same query, thorough | 10 | Mwmbl3 | 13 |
| Docker Compose healthcheck, web | 10 | None | 10 |
| Same query, thorough | 10 | Mwmbl3 | 13 |
| Attention Is All You Need, academic | 10 | Crossref1, arXiv3, OpenAlex2 | 16 |

The Docker supplement's first page contained a relevant readiness/healthcheck
example. The Python first supplement was about S3 recursive globbing rather
than pathlib. The academic supplements included unrelated and withdrawn papers;
the first supplementary read failed. These observations do **not** justify
switching supplementary engines on for every request. General-web and research
defaults stay web-only. Specialist profiles are deliberate options whose returned
choices still require an agent's relevance assessment.

[Live menus and read hashes](live-caps.json),
[actual oversize rejections](oversize-rejections.json), and
[headed-browser fixture](browser-fixture.json) retain the observations. Full read
bodies and the initial no-display test-harness failure are preserved locally;
source page bodies are not republished here. No credentials are included.
