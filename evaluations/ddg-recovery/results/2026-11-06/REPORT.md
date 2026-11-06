# DDG refusal and autonomous recovery — 6 November 2026

Unreleased follow-up to the [earlier ordinary acquisition checks](../../../compact-discovery/results/2026-11-06/REPORT.md).
The previous checks never encountered a refusal. This investigation does; it also
fixes three additional defects. No publication or production deployment occurred.

## Real public DDG observations

[Static controls](static-probes.json) used the identical question, Lite URL and
outbound IP. Ordinary Python HTTP received **202**, no result links, and DDG's
`anomaly.js` / `bots use duckduckgo` / image-selection CAPTCHA markers. Four seconds
later, curl's Chrome impersonation received **200 and ten results**, in 0.887 s.
The two clients differ in both request headers and TLS profile; this comparison
cannot attribute the result to TLS alone. Body hashes and observed times are kept.

Lite/HTML form POST and HTML GET also returned ten results (0.679–0.877 s).
[Browser controls](browser-variants.json) recovered ten through Lite navigation,
HTML form submission and the JavaScript page. They did not demonstrate an
additional read over the existing default, so no new POST/JS tier was shipped.
No key, paid service, proxy rotation, CAPTCHA solver or extra container is required
by the implementation.

The acquisition alternatives were informed by
[SearXNG's DDG engine documentation](https://docs.searxng.org/dev/engines/online/duckduckgo.html),
which documents form requests and browser navigation headers. It does not promise
that these mechanisms bypass every DDG block.

## Live automatic fallback, not mocked responses

The [first live proof](autonomous-proof.json) deliberately replaced the initial
curl-impersonating getter with ordinary Python HTTP. The [repeat](autonomous-proof-final.json)
and [final worker run](autonomous-proof-final-worker.json) used the reproducible
harness with the same explicit transport ablation. **This is
an experiment, not a change to the shipped first-hop configuration.**

The actual DDG 202 body/status entered the normal parser and acquisition ladder.
Without manual provider selection, the ladder called Patchright, obtained public
DDG HTTP 200 and returned ten DDG results. All results are uncached and no Yahoo,
Yandex or other supplementary provider participates.

| Question | First run, s | Repeat, s | Final worker, s | Initial DDG | Automatic browser |
|---|---:|---:|---:|---|---|
| Filmmakers' nationality | 1.453 | 1.501 | 1.473 | 202 + CAPTCHA markers | 200, 10 results |
| Python recursive pathlib discovery | 1.561 | 1.538 | 1.330 | 202 + CAPTCHA markers | 200, 10 results |

These six live recoveries prove that the autonomous fallback handles this real
request-profile refusal. They do **not** prove recovery from an IP-wide ban that
rejects every available request profile. The normally configured TLS first hop
also succeeded in the controls; we did not falsely label it as refusing. No
response was fabricated and no CAPTCHA was solved. Observed refusals had no
Retry-After header; no cooldown was cleared to force retries.

[Source follow-up checks](source-checks.json) read the recovered Python reference
and both Wikipedia biographies using normal direct extraction. The Python page
contained the recursive `Path.rglob` description; both biographies described the
subjects as American filmmakers. All three reads succeeded. Not every returned
search candidate is asserted relevant, and this is not an answer-quality benchmark.

## Confirmed fixes

- **Sparse TLS results:** the static parser still required three links/two long
  snippets, unnecessarily rejecting one/two legitimate source choices. It now
  accepts a valid source with a substantive snippet, matching the browser policy.
  Empty/challenge/weak-snippet cases still fail. No ranking or display cap changes.
- **False genuine-zero reporting:** an empty DDGS fallback could overwrite earlier
  real refusals as `no_results`. Refused acquisitions retain their failure state;
  zero-count diagnostics during known unavailability/cooldown remain unavailable.
  An honestly empty query without a refusal still reports `no_results`.
- **Retry-After applied too late:** previously the direct header affected family
  rest only after further browser/library attempts. An explicit wait on 202/429/503
  now immediately stops further DDG-family acquisition and persists the server wait.
  Browser responses also propagate the wait and cancel pending race work. Already
  received parallel results remain available while future calls respect the wait.
  Headerless refusals can still try the browser. Controlled explicit-wait tests
  reduce acquisitions from four adapter calls to one, while cached evidence remains
  available and normal single-flight recovery resumes after the wait.

A real Chromium/local HTTP regression exposed one further defect: an empty HTTP
429 made `page.goto` throw `ERR_HTTP_RESPONSE_CODE_FAILURE`, losing its status and
headers. A navigation-response observer now preserves them before the exception.
The [worker fixture](chromium-backoff.json) receives the actual 429/120-second wait,
stops with one HTTP request and retains sparse results/menu-cap regressions. The
original failed browser runs remain private. Numeric/date waits are bounded.

No ranking, source order, ten-primary/fifteen-total limits, cache lifetime, corpus
policy, model or dependency changed. There is no new production retry loop. The
existing adaptive family cooldown still handles correlated headerless refusals.

## Verification and remaining bounds

The initial isolated regressions reproduced four failures (one-/two-source parser
rejection, false-empty diagnostics, refusal erased by empty fallback). Those
regressions pass after correction. Existing provider doubles also needed transport
wrapping explicitly disabled: they have no `ddgs.http_client` module and must not
rely on test import order. Original failed logs are retained privately.

The final core suite passed 905 tests (15 skips; two network tests excluded), and
the final real Chromium worker fixture passed. Final counts and candidate hashes
are in [validation](validation.json) and
[source hashes](source-hashes.json). Native x86_64 was tested; ARM64 was not rerun
for this follow-up. The previous concise-response, MCP and browser regression
checks remain part of this candidate. Live sample size is small and uses one
outbound IP. Intermittent network failure and complete provider blocking can still
leave only supplementary results; this work does not claim otherwise.
