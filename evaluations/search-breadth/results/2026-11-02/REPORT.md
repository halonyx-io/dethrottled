# Automatic discovery breadth — 2 November 2026

The final public MCP check after 1.1.1 failed its greater-than-ten-results
assertion. The new browser worker could return 50, but cheap TLS discovery was
enabled in production and the core returned its first ten immediately. The worker
fix was published before this whole-path check; the new evidence corrects that
gap rather than presenting private-worker success as public-pipeline success.

1.1.2 keeps small usable cheap searches fast. For requests above 12 results, a
cheap result set smaller than the requested count now triggers browser breadth
recovery automatically. Merge/deduplicate both sets, preserve the cheap results
if the browser fails, and report requested/cheap/browser/returned counts with
fulfilled or partial status in diagnostics. Old browser-cache entries are not
reused for the changed broad-search semantics. Explicit DDGS engine selections
retain their existing behavior.

[Baseline core envelope](baseline-core-envelope.json) records ten results and the
cheap TLS attempt on production 1.1.1. Before publishing this correction, a fresh
isolated API and MCP adapter were run against the existing production browser,
with cheap discovery enabled and the same query. The [actual SDK/MCP envelope](staged-mcp-envelope.json)
records TLS=10, browser=50 and 50 unique returned URLs in about 4.36 seconds. That
exercises MCP → API → TLS → browser → merged results, without changing production
credentials or attaching production data volumes. It is a live retrieval
observation, not proof of 50 independent facts or answer correctness.

The [full regression suite](regression.log) passes **658 tests**, with 15 skips and
two network tests deselected. Added contracts verify automatic breadth escalation,
small-request fast paths, retained cheap results on failure, and old short-cache
invalidation. Native release CI and a public endpoint recheck gate promotion.
No dependency, browser engine or document-recovery change is included here.
