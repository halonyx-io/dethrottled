# Post-1.6.0 findings and cumulative changes — 6 November 2026

Candidate based on released `0006cdf`, branch `fix/161-retrieval-review`.
**Uncommitted, not pushed, not published, not deployed; version remains unchanged.**
[Harness](../../README.md). Raw JSON/logs are beside this report. Earlier
[PDF/corpus evidence](../../../retrieval-review/results/2026-11-06/REPORT.md)
is preserved as its original candidate observation, not silently rewritten.

## New confirmed issues

**Unchanged blocklist reloads:** a 304 persists check metadata by atomically
rewriting the snapshot. Reader workers see a new file signature and previously
parsed all rules again. Identical 200 responses also reparsed unnecessarily.
Validated equal body hashes now reuse the compiled immutable set, while still
checking the snapshot body digest, refreshing durable metadata and preserving
atomic activation. Changed bodies and first loads after restart still parse.
`last_update` retains successful HTTP 200 refresh time, even for identical
bodies; HTTP 304 advances only the check time. `last_check` tracks attempts. A 304 cannot activate mismatched cached digest/source metadata.

Three paired observations on the same 222,452-rule snapshot, one updater and
three simulated readers, in fresh isolated processes:

| Measurement | 1.6.0 | Candidate |
|---|---:|---:|
| Full reader parses, each refresh | 3 | 0 |
| Median total CPU seconds | 0.812 | 0.068 |
| Median elapsed seconds | 0.867 | 0.169 |
| All reader rule-set objects reused | No | Yes |

This is roughly 0.74 CPU seconds saved per simulated four-worker refresh, not a
whole-engine speedup. It removes transient rule-set allocations; no whole-stack
RAM reduction was measured. Stable-state rule storage remains the same.

**Active streams:** the proxy checked hostname policy for every data chunk. A
list change could terminate an established encrypted download/WebSocket without
an application-level policy response. Policy admission now lasts for the
connection. New connections are checked before dialing; page navigation checks
remain. Existing tunnels are not immediately revoked, and encrypted requests
reusing one retain its admission until closure. No TLS inspection is introduced.

In all three local socket runs:

| Outcome during rule change | 1.6.0 | Candidate |
|---|---:|---:|
| HTTP body received | 65,536 / 4,194,304 bytes | 4,194,304 / 4,194,304 bytes |
| Full-body SHA-256 matches | No | Yes |
| WebSocket messages delivered | 1 / 9 | 9 / 9 |
| Fresh connection to newly blocked host | Refused | Refused |

Focused tests also verify a redirect's new connection is refused, unchanged
upstream proxy refusal/chaining, corrupt/offline snapshots, disabled behaviour,
changed-body activation and restart. These are deterministic local transfers,
not a new claim about general anti-bot success or browser throughput.

**MCP admission interoperability:** authenticated caller/global/rate rejection
previously returned a flat HTTP error. HTTP transport errors are legitimate, but
an ID-bearing JSON-RPC error is more useful for correlation. The MCP adapter now
returns `jsonrpc=2.0`, server error `-32000`, matching ID when a valid bounded
POST body supplies one, and original retry diagnostics in `error.data`.
429/503, Retry-After, limiter and request-ID headers remain. REST's flat contract
is unchanged. Body parsing occurs only on rejection, bounded to 256 KiB/one
second. Notifications/malformed/oversize/stalled bodies and GET do not invent IDs.
Accepted request streams and authentication handling are unchanged.
See the [MCP transport specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports).

**Request discoverability:** extend the earlier corpus example to a compact
OpenAPI-derived `request_contracts` list: HTTP methods, required/accepted body
names and query names for canonical routes. This resolves guessing across
`question`/`query`/`q`, `urls`, `document_id`, `job_id` and `limit` without adding
aliases or duplicating the model definitions. Full constraints remain in OpenAPI.

**Crawl short navigation:** the crawler only followed links from `quality=ok`
pages. A legitimate short index rated `thin` therefore prevented discovery of its
longer report. It now follows bounded, in-scope links from retained thin/suspect
pages too, without upgrading their quality. In the same fixture, baseline visited
one page with zero `ok` pages; candidate visited two with one `ok` page.

Crawl adds `operation=site_crawl` and an explicit `outcome` (`pages_read`, `partial`,
`no_ok_pages`), retaining the existing sources/coverage/frontier structure. Warnings
and policy refusal metadata survive on source entries. `no_ok_pages` means none
was rated `ok`, not proof that thin evidence is useless. Legacy `coverage.failed`
still counts non-`ok` rows. The reported research-route substitution/zero-attempt
response was not reproduced: a failed seed yields one attempt and a failed source
in the actual API regression. No speculative route remapping was added.

## Reviewed and deliberately unchanged

- **Multi-URL jobs:** a controlled two-URL job exposes running 1/2 progress, then
  reaches completed 2/2, retaining one successful and one failed read. Completion
  counts finished positions, not successful evidence. No job defect confirmed.
- **Two-second DNS/connect cutoff:** not justified. Current host resolution for
  `gnu.org` returned both IPv4 and IPv6, so the earlier IPv6-only observation was
  not reproduced. A core ConnectionError is not proof that differently routed
  workers cannot recover the source. Existing bounded tier deadlines remain;
  no broad preflight or timeout reduction sacrifices coverage.
- **Admission caps:** preserved. A rejected call is a transport/policy result,
  not an empty successful tool call. Clients still need to inspect HTTP status.
- **GTM/DoubleClick:** selected HaGeZi PRO policy remains unchanged. No ad hoc
  blocklist expansion, registrable-domain overblocking or extra profile added.

## Everything changed since 1.6.0

1. Extend bounded implicit native PDF text reads beyond 100 pages (up to 1,000,
   still subject to the existing character limit); RFC 9110 retains 3/3 fixed
   facts versus 1/3, including an actual fixture-backed `/fetch` test.
2. Stop before clipping later pages, expose a single oversize clipped page, and
   resume OCR at the first unread scan rather than consuming missing evidence.
3. Bound table analysis separately to 100 pages and report its scan coverage;
   preserve native text and request narrower ranges for oversized layout work.
4. Skip inappropriate HTML browser recovery for successfully acquired documents;
   preserve their exact format/range continuation.
5. Refresh reparse status/character counts and remove stale recovery-gap metadata
   on the new version, retaining original handles. Target source-image inspection
   at the actual selected/clipped page.
6. Add bounded corpus literal-overlap diagnostics and explicit retrieval-candidate
   semantics. All 72 earlier paired mode/support configurations retain identical
   ordered results; useful paraphrases remain. No answer-verification claim.
7. Make HTTP route/parameter discovery explicit, including corpus examples and
   OpenAPI-derived contracts across the API; keep REST/MCP naming compatible.
8. Eliminate unchanged-list rule reparsing and guard 304 cached metadata.
9. Preserve admitted streams across rule updates while refusing new connections.
10. Frame MCP admission errors with correlated JSON-RPC IDs and retained retry data.
11. Follow thin/suspect navigation links within crawl bounds, retain warnings and
    policy refusals, and explicitly distinguish no-`ok` outcomes.
12. Reconcile agent/MCP instructions, API/public-access/filtering/limits/corpus/
    requirements guides, generated references, evidence links and doc inventory.
    Clarify full eight-container memory observations versus the five-service
    default; no fabricated comparative hardware requirements.

## Validation and release gates

- Combined relevant native x86_64 suite: **296 passed**, before the final
  corrupt-metadata guard and extra stalled-body/redirect test cases were added.
- Final affected API/access/adblock/crawl/jobs groups: **122 passed**, including
  those additions. Earlier PDF/corpus regressions remain retained; these counts
  overlap and must not be summed as independent tests.
- Actual pinned MCP SDK **1.30.0** and REST adapter integration verifier: passed;
  20 tools, argument strictness, auth/revocation, public-target rejection, version
  mismatch/match detection, diagnostic search, evidence and native images.
- Targeted lint, generated references, agent coverage and docs/examples checked.
- Native ARM64 execution remains blocked by SSH authentication, as recorded in
  the earlier review. No architecture-specific dependency was added. Fresh ARM64
  and full release CI remain gates before any future publication.

No new runtime dependencies, services, models, API-key reliance, ranking policy,
cache lifetime or corpus-retention change. No production containers were restarted.
