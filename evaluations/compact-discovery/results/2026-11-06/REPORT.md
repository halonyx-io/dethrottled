# Concise responses and discovery investigation — 6 November 2026

Unreleased candidate based on 1.6.1 (`f5abf7b`). Production was not modified.
[Source hashes](source-hashes.json) identify the tested candidate files.
No ranking, provider order, model, dependency, cache lifetime or extraction limit
was changed. Measurements ran on native x86_64; ARM64 was not run for this change.

## Confirmed defects and changes

1. **PDF response bloat:** the 8,000-character excerpt limit did not constrain
   full-document PDF text-layer blocks in extraction metadata. Even concise mode
   returned these duplicate blocks. Concise now substitutes block counts, preserves
   every page summary and exposes an explicit presentation-omission diagnostic.
   Canonical metadata, retained text and detailed REST responses are unchanged.
   MCP fetch/research/read_document default to concise; explicit detailed remains
   supported. REST retains its detailed default for compatibility.
2. **Sparse browser discovery:** the worker required three links and at least two
   substantive snippets. Real one-/two-result pages were rejected until timeout,
   then reported as 503. One validated result with a substantive snippet now
   suffices. Empty, weak-snippet and challenge pages remain unsuccessful. Default
   source ordering, ten-primary/three-supplement limits and no-pagination policy
   are unchanged.
3. **Failure diagnostics:** worker 503s previously omitted service/queue timing;
   the API recorded zero milliseconds when those fields were absent. Failures now
   carry their actual timings and reason. Browser attempt counts are now tracked
   independently of DDGS fallback; a later fallback cannot overwrite the browser's
   failed status or attribute its own rows to the browser. Worker metrics retain at most 20 failure
   summaries, excluding queries and exception-message text.
4. **Readiness ambiguity:** additive observation_state and
   last_observed_availability distinguish expired evidence of success from a
   recently observed refusal. Existing booleans, 60-second observation TTL and
   no-probe policy remain unchanged.

## Paired offline observations

[Saved RFC response replay](pdf-observed.json), seven serialization repeats:

| Measurement | 1.6.1 projection | Candidate projection |
|---|---:|---:|
| JSON bytes, one row | 939,730 | 45,905 |
| Median projection + JSON encoding, ms | 53.73 | 3.18 |
| Peak Python allocations traced during operation, bytes | 4,694,694 | 108,282 |

The 95.1% byte reduction retains the same 8,000-character excerpt, 466,034-character
retained-document handle, all 194 page summaries, warnings and next_offset=8000.
These are helper timings with tracing enabled, not end-to-end fetch improvements.
Traced allocations are not RSS or container RAM. The private input is not published;
its SHA256 is retained in the result. [The synthetic replay](pdf-synthetic.json)
is fully reproducible without that response.

[Real Chromium, local fixtures](browser-local.json), one observation per case:

| Available validated sources | 1.6.1 | Candidate |
|---|---|---|
| 1 | failed, 0 returned, 6.69 s | success, 1 returned, 0.41 s |
| 2 | failed, 0 returned, 6.81 s | success, 2 returned, 0.52 s |

These narrow controlled cases establish a functional defect and its correction.
They do not estimate broad search latency or prove additional hostile-source reads.

## Live observations and decisions

Earlier browser-worker 503s were present in logs. One paced fresh search then
returned ten DDG candidates plus Yahoo/Yandex supplements in 0.993 seconds;
readiness immediately became healthy. Persistent primary outage was not reproduced.
The sparse-result defect can explain some 503s, but cannot retrospectively explain
all reported failures. No provider hammering, automatic recovery probes or extra
retries were introduced. Actual anti-bot refusals remain possible.

example.com reproduced the browser escalation: direct and TLS each extracted 156
characters (~61 ms each), labelled thin; Crawl4AI recovered 952 characters (~1,036
ms). Full request: 1.378 s; cached repeat: 0.191 s. The extra text included multiple
languages. The fetch/search modules were unchanged between 1.6.0 and 1.6.1, and the
new document-only planner shortcut does not apply to this HTML. No short-page
special case was added: doing so here would sacrifice demonstrated coverage.
Those samples do not establish a general release latency regression.

Full 194-page PDF parsing still has a cost; this work addresses response size,
not parser acceleration. A caller explicitly requesting a million characters can
still receive a large content field. Use focus/excerpt limits and retained-document
continuation. Detailed mode intentionally retains block-level evidence.

## Validation

- Final native x86_64 non-network suite: 890 passed, 15 skipped, two network tests deselected.
  [Validation summary](validation.json) retains the final gates and original fixture failure.
- Focused tests preserve canonical evidence and metadata, concise idempotence,
  page summaries, failures/timings and stale-versus-current readiness.
- Real Chromium fixture checks include one/two sources, ten/three caps, no
  pagination, 20-entry failure-history limit, query redaction and admission cleanup.
- MCP SDK stays pinned to 1.30.0; real adapter transport checks verify advertised
  concise defaults and existing access, diagnostics and large-read contracts.
- No new version, commit, push, publication or deployment was performed.

## Additional live refusal-recovery check

[The raw DDG observation](ddg-live.json) retains the exact queries, historical
query hashes, attempts, timings, filtering snapshot hash and returned source
choices. Two queries match HTTP 202 observations from the retained 3 November
study. Both now returned ten DDG results through normal TLS-first discovery
(1.038 s and 0.644 s), with filtering enabled and caches bypassed. Two separate
browser-control calls returned ten each (1.039 s and 1.046 s). A final HTML-only
browser control also returned ten sources, HTTP 200, 1.048 s engine time.

**No current refusal occurred in these five acquisitions.** They demonstrate
current availability after historical refusals, not fresh anti-bot defeat or
causal recovery. Browser-only/HTML-only controls are explicitly separated from
the ordinary ladder. No load-induced refusal, cooldown reset or retry-until-win
was attempted. Existing controlled refusal/fallback regressions prove routing;
fresh real refusal-and-recovery remains unproven.

The expanded overdelivery diagnostic assertions initially failed in two cases:
the existing response double omitted the HTTP `ok`/`status_code` properties, unused
when that test previously omitted diagnostics. The fixture now supplies successful
HTTP properties. The original failing run is retained privately; no runtime code
was weakened to accommodate the mock.

The [actual REST route projection check](api-projection.json) replayed the saved
acquisition fixture through `/fetch`: 45,907 concise bytes versus 939,732 default
detailed bytes. Both retain the same document handle, all 194 page summaries,
466,034 document characters and continuation offset 8,000. This isolates the real
HTTP presentation contract without repeating acquisition or mutating production.

A subsequent [DDG-specific follow-up](../../../ddg-recovery/results/2026-11-06/REPORT.md)
encountered real 202 challenges and measured automatic browser recovery under an
explicit plain-primary transport ablation. The earlier observations above are
preserved as recorded; their no-refusal result is not the final recovery evidence.
