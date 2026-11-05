# Retrieval reliability investigation — 2026-11-05

**Status: validated candidate; publication/deployment authorized for 1.5.2.**
Baseline runtime: v1.5.0. Local native/live captures identify the tested pre-release
candidate as 1.5.1. Final 1.5.2 includes the earlier public-document namespace fix;
recorded identities are preserved rather than relabelled.
Discovery ranking, source budgets, cache lifetimes, corpus policy, model weights
and browser pacing intervals are unchanged. No dependencies or services were added.

## Findings

| Concern | Verdict and root cause | Candidate change | Limits |
|---|---|---|---|
| Search health | Confirmed. `search.health()` queried SearXNG/default news and Bing News, never primary DDG. It reported ready with DDG down and not ready with DDG up. | Observe actual searches for 60 seconds; separate process, primary, supplementary and news state. Status reads issue no upstream queries. Cold/stale is unknown; cached evidence does not prove upstream recovery. | Idle/restarted instances need a real search before discovery is observed. This is deliberately different from process liveness. Explicit `python -m dethrottled.health` remains an active diagnostic command. |
| Search degradation | Confirmed. Any non-empty envelope said `ok`; empty, failed and indeterminate discovery shared one label. DDGS failures/cooldowns were not fully included in attempts. | Preserve legacy `status` and add authoritative `outcome`, `degraded`, provider availability and richer acquisition attempts. Keep useful partial rows and their order. | These are acquisition observations, not relevance/answerability verification. A provider can still return plausible unrelated material. |
| Extraction completeness | Confirmed on frozen RFC 9110 and split article/main HTML. A first successful extractor omitted labelled evidence despite substantial output. | On long structured HTML, sample substantive block starts/ends outside known furniture. Multiple missing samples selectively compare alternates; an alternate must preserve matched samples and add coverage. Expose unverified/suspected completeness and inspect unresolved gaps. | Samples are not exhaustive. Ambiguous `<aside>` material remains deliberately excluded. No claim of complete extraction; no automatic browser replay solely because samples are missing. Old cached extractions remain until refreshed or expired. |
| DDG cooldown coordination | Confirmed under controlled correlated refusals: three requests made ten family attempts despite repeated 429s. Existing per-engine DDGS/SearXNG rest did not cover TLS/browser alternatives. | Rest only after TLS Lite and both browser Lite/HTML paths explicitly refuse. Persist adaptive 30/60/120-second rest, capped by existing engine rest; respect longer TLS Retry-After up to one day. One default recovery per API process; a fresh DDG success clears rest. Cached choices and independent providers remain usable. | Controlled observations do not prove faster real DDG recovery. Private direct-worker callers and separate API processes do not share the process-local recovery guard. News failure correlation is unproven and left separate. |

Sound behaviour retained: `/health` already reports liveness; partial rows were
already kept; DDG pacing was already coordinated through the worker; engine-health
writes were already atomic/locked; extraction assessment already avoided declaring
verified completeness. None of these was replaced speculatively.

## Controlled search comparisons

`benchmark_search.py` replays identical provider lists/refusals into actual search
orchestration and API-envelope functions. It is offline: provider delay is an
explicit synthetic 5 ms, not a measured upstream latency. Every scenario's visible
URL order must remain identical before/after.

| Scenario | Baseline primary-ready claim | Candidate | Candidate outcome |
|---|---|---|---|
| DDG down; alternatives up | ready | not ready; supplements available | partial_results |
| DDG up; alternatives down | not ready | primary ready; degraded supplements | partial_results |
| Complete outage | not ready | not ready | unavailable |
| All healthy | ready | ready | results |
| Successful empty replies | ready | upstream available; zero choices | no_results |

Five status reads after each search made **10 upstream probe calls before, zero
after**. Three searches against correlated refusal fixtures made **10 family
attempts before, four after**. The first request still tries the alternatives;
subsequent default requests respect the shared rest. This is request suppression,
not proof of defeating a CAPTCHA. Tests also cover TLS failure/browser success,
HTTP 500 without refusal, Retry-After, cached choices, explicit non-DDG fallbacks,
SearXNG DDG filtering, concurrent recovery, persistence and unsuccessful recovery.

## Extraction measurements

Nine frozen HTML fixtures carry three independently selected passage/fact labels
each: seven controlled layouts and two public RFC snapshots. Passages are graded
by normalized word sequence, so harmless inline-markup whitespace does not create
false misses. Each fixture/variant runs in a fresh native process with three timed
extractions. Peak RSS includes the interpreter and native extractor libraries.
Both native architectures retained **21/27 before and 25/27 after**. The remaining
two misses are in the ambiguous aside fixture. Six sound fixtures retained all
labels without switching extractors; two incomplete fixtures improved.

| Architecture / fixture | Before → after median, ms | Before → after peak RSS, MiB | Labelled passages |
|---|---:|---:|---:|
| x86_64 / split article-main | 15.3 → 18.3 | 41.2 → 47.9 | 2/3 → 3/3 |
| x86_64 / RFC 9110 | 463.8 → 539.0 | 135.9 → 147.3 | 0/3 → 3/3 |
| x86_64 / RFC 8446 | 115.1 → 127.2 | 55.5 → 59.3 | 3/3 → 3/3 |
| ARM64 / split article-main | 21.8 → 26.6 | 41.3 → 46.5 | 2/3 → 3/3 |
| ARM64 / RFC 9110 | 843.1 → 1026.2 | 136.0 → 145.5 | 0/3 → 3/3 |
| ARM64 / RFC 8446 | 189.3 → 232.6 | 54.3 → 58.6 | 3/3 → 3/3 |

These are the existing x86_64 mini PC and ARM64 edge-device test hosts described
in the [hardware guide](../../docs/BENCHMARKS.md).

The RFC 9110 baseline retained about 5,200 characters; the selected alternate
retained about 406,000. Raw text length did **not** select the alternate. The
structural samples and retained labelled passages did. These are extraction-only
numbers, not web-fetch latency promises. Background production load was not
sampled continuously; the small repetition count and fixed baseline-first order
limit timing comparisons. No statistical confidence interval or universal memory
minimum is claimed. Results are a correctness/coverage gate, not a broad web census.

Navigation-heavy and ordinary long articles did not run alternate extractors in
the measured sound cases. Additional regression fixtures reject promotion of
related prose outside explicit primary content and preserve useful text/warnings
when alternatives fail. They do not establish zero pollution on arbitrary sites. Independent replay of
retained text found **0/15 predefined furniture labels retained** in both variants
on both architectures. Those labels are known control-page navigation/footer
strings; they are not a general-purpose pollution detector. The original noise
marker was absent from the fixture and was replaced with these source-verified
labels before freezing the evidence.

## Validation and release boundary

Both final native suites passed **797 tests**, with **15 skips** and **two network tests excluded**
each. Package/image verification and isolated real API/MCP results
are recorded in `results/validation.json`. The isolated authenticated MCP/API
workflow passed cold readiness, actual default DDG + SearXNG search diagnostics,
live RFC recovery (406,026 canonical characters and all three labelled passages),
matching initialization instructions, cross-caller retained reads, exact character
offsets, cached repeat fetch and both native corpus models (96 passages each).
This is a local bridge test; the public Caddy endpoint was not switched to the
candidate. An initial smoke harness incorrectly expected `cache_mode=bypass` to
populate the cache. It correctly did not; the original failed record is retained.
The repeat explicitly used `refresh` before testing a cache hit. Production cache
behaviour was not changed to satisfy that assertion. Original failures and
corrections are recorded there rather than overwritten. The previous Corpus v2
[quality study](../corpus-v2/results/2026-11-05/REPORT.md) remains dated evidence;
this work does not rebrand its results or claim ranking improvements.

The 1.5.1 release command had already started when the additional hold instruction
arrived. Its GitHub release was returned to draft and the workflow was cancelled
before PyPI publishing. The existing tag is untouched. Human sign-off subsequently authorized the complete release and production rollout.
The final version is 1.5.2 so the existing 1.5.1 tag remains untouched. Production
was still on 1.5.0 during these captures; final publication/deployment verification
belongs to the 1.5.2 GitHub release assets, not this pre-release benchmark record.

## Reproduce and verify

Build clean baseline/candidate native API images with identical dependencies and
pinned model assets. Keep production images, services and volumes untouched.
All commands below disable external networking; the benchmark reads frozen gzip
fixtures and controlled provider responses.

```sh
mkdir -p /absolute/path/to/results
# Repeat with the baseline image/source, then the candidate on each architecture.
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$PWD/evaluations/retrieval-reliability:/lab:ro" \
  -v /absolute/path/to/results:/output \
  dethrottled:baseline python /lab/benchmark_extraction.py \
  --label baseline --output /output/extraction-baseline.json

docker run --rm --network none --user "$(id -u):$(id -g)" \
  -e PYTHONPATH=/candidate/src -v "$PWD:/candidate:ro" \
  -v "$PWD/evaluations/retrieval-reliability:/lab:ro" \
  -v /absolute/path/to/results:/output \
  dethrottled:candidate python /lab/benchmark_search.py \
  --label candidate --output /output/search-candidate.json

python evaluations/retrieval-reliability/verify.py
```

For extraction candidate replay, use the first command with the candidate image,
label and output filename, or mount candidate source as in the second command.
Run search baseline replay with its baseline image and label. Linux is required
for the recorded native RSS units. Actual package contents, runtime source hashes
and installed dependency inventories accompany the final gate; do not infer a
tested version solely from the container's tag.
