# Bot findings checked — Dethrottled 0.9.0

The supplied `DETHROTTLED-CODEX-FINDINGS-2026-11-01.md` was read from the local
OpenClaw workspace. Its claims were checked against deployed 0.8.0, SDK 1.28.1,
source code, controlled browser fixtures and fresh public requests. D6 was excluded
at the user's explicit request. No routing, proxy or exit-node changes were made.

| Claim | Finding and resulting change |
|---|---|
| D1: headed reads sample once after 700 ms | Confirmed. Same-browser polling now waits for a detected interstitial to clear within a bounded deadline. |
| D2: challenge detection misses non-Cloudflare interstitials | Confirmed, including the recorded CarGurus text. Detection covers strong vendor/short-interstitial signals, with negative controls for legitimate vendor documentation and structured documents. Broad words such as `akamai` alone are deliberately insufficient. |
| D3: headed fetch discards clearance state | Confirmed for the old ephemeral fetch path. Automatic reads now use caller/exact-host/policy-scoped browser identities and checkpoints. Cookies are not shared across clients or assumed portable to another TLS fingerprint. |
| D4: default reads skip the headed tier | Confirmed for challenges. Detected challenges now trigger one automatic headed attempt; explicit render restrictions win. Ordinary readable pages stay on direct acquisition. |
| D5: fingerprint unverified | Measured. Sannysoft webdriver/Chrome/plugin/language checks pass; WebGL is absent. CreepJS loaded but its partial captured DOM was not assigned a score. No stealth launch flags or dependency versions were changed without an access win. |
| 1.1: concurrency is about two because of renderer admission | Cause incorrect. The direct research endpoint has its own two-request semaphore. At three and six concurrent controlled requests it reproduces the 429 pattern while renderer admission remains entirely unused. |
| 1.1: all 429s indistinguishable | Overstated: shared access already returned distinct `error` values. Research lacked a typed limiter and retry hint. Responses now expose consistent limiter/reason/backoff information. The existing concurrency limits are not silently raised. |
| 1.2: unknown fields silently dropped at MCP and backend | Confirmed for generated MCP argument models; disproved for backend request bodies, which already use `extra=forbid`. All 20 MCP schemas now reject extras before invoking the backend. Client-side filtering before transmission remains outside server validation. |
| 2.1: whitespace and challenge text can become `ok` | Confirmed. Blank extracted prose is rejected, recorded short interstitials are classified, and remaining short HTML evidence is explicitly `thin`. A legitimate `no matching results` page is not automatically a bot wall. |
| 2.2: capabilities advertise the wrong spelling | Confirmed. Canonical fetch fields advertise `format`; REST aliases are listed separately. |

## Measurements and limits

The controlled fixture serves a delayed JavaScript clearance page with a known
allocation of **7341 tonnes** behind it. The baseline recovers zero of four
challenged reads; the candidate recovers four of four, without an opt-in headed
flag for the default cases. Baseline explicit headed fallback falsely labels the
65-character interstitial `ok`. Both builds read the plain control directly.
Candidate first reads require two challenge polls; a repeated caller needs zero.
A separate caller requires its own clearance. After restarting the isolated browser,
checkpoint restoration recovers the original callers with zero challenge polls.
These fixtures establish workflow behavior, not success against real Cloudflare.

A further public-client bug was found beyond the brief: the browser context treated
cross-host subframe navigation like top-level navigation. A controlled cross-host
challenge iframe failed on the old worker and succeeds on the new worker. Private
subframes remain blocked and foreign top-level navigation remains rejected in both.
The fixture-only public-address exceptions used to test this are not shipped.

The live protocol freezes four hostile URLs and one ordinary Python documentation
control before execution. The four hostile sources are CarGurus, Crunchbase,
G2/Notion reviews and Expedia. **No new successful hostile-source read was observed
on that sweep.** The normal control remains readable through direct acquisition.
CarGurus's baseline 72-character verification page was falsely marked `ok`; the
candidate does not count its observed blocked/empty result as content. The public
sweep is observational: upstream responses can change between sequential runs.
The brief's 15/24 figure cannot be reproduced as a benchmark without its exact URL,
query, expected-content and raw-response manifest, so it is not reused as evidence.

MCP SDK checks demonstrate two formerly ignored arguments now produce named tool
errors, zero invalid backend calls, a valid request reaching the backend, and
`additionalProperties=false` on all 20 registered tools. REST body strictness is
an existing feature rather than a newly claimed improvement.

The research concurrency experiment returns two successes and one busy at n=3,
and two successes/four busy at n=6. Renderer counters remain zero throughout.
Candidate busy responses identify `research` and offer a two-second polling hint.
REST forwarding also preserves backend retry/limiter headers instead of dropping
them at the public gateway. Shared access retains caller/global/rate distinctions; rate hints use a ceiling
of time to the minute boundary. A 300-second lease TTL is crash reclamation, not
an estimate of a normal request's duration.

## Design decisions

The working Patchright/headed/DDG stack is retained. Recovery uses existing drive
navigation, waits, HTML reads and checkpoints. Main-frame and popup navigation stay
within allowed hosts; permitted public subframes still pass address validation.
No CAPTCHA-solving service, proxy dependency, external model, paid provider or
routing change is added. Interactive or persistent challenges are reported honestly,
and workflow actions expose browser pixels for a capable client to inspect.

Cloudflare documents clearance as tied to its visitor/device, so automatic cookie
export to curl is not presumed to work. See [Cloudflare clearance documentation](https://developers.cloudflare.com/cloudflare-challenges/concepts/clearance/).
HTTP 429 means a rate-limit rule fired; it does not establish IP reputation as the
cause, and HTTP 401 is not evidence of an IP ban. See [Cloudflare's 429 explanation](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-429/).
Chromium's SwiftShader fallback requires an explicit opt-in to lower security
guarantees. It is not enabled merely to make a fingerprint score green. See
[Chromium's SwiftShader documentation](https://github.com/chromium/chromium/blob/main/docs/gpu/swiftshader.md).

## Evidence and reproduction

Raw JSON, frozen protocols, fixture code, model-free SDK validation and final
verification are retained under `docs/benchmarks/2026-11-01-findings/`.
The original report's hash is recorded to identify the reviewed revision.
`tests/test_autonomous_recovery.py` covers acquisition, negative detection cases,
caller state isolation, deadlines, explicit render restrictions, blank/thin results,
actual attempt reporting and workflow continuation. `evaluations/tool_validation.py`
runs inside the installed MCP SDK environment without network or credentials.
A separate OpenGL backend experiment also failed to restore WebGL and was rejected.
Full fingerprint HTML and private context state remain local; published fingerprint
results omit unique fingerprint identifiers. This release improves tested autonomous
recovery and honesty; it does not establish universal challenge defeat or superiority
over paid web engines.

Final non-network suite: **568 passed, 15 skipped, 2 deselected**. Actual browser
and installed-adapter experiments are recorded separately. Lint passes. Browser
launch settings and Patchright 1.63.0/Chromium 1243 remain unchanged; the worker
code change concerns public subframe navigation policy only.

## Deployment verification

The promoted API is 0.9.0. Installed MCP, REST and shared-access source hashes
match the checkout; image checks verified the core and browser sources before
promotion. Protected backups retain the previous images, SQLite databases and
browser state. Token registry, environment and routing were unchanged.

The first post-restart public handshake returned `caller_busy`, explicitly naming
`caller_concurrency`. Read-only inspection found five unexpired admission leases
with roughly two minutes remaining. Checks wait for normal lease expiry without
clearing shared state or changing limits. This exposes a remaining rollout
limitation: persistent/crashed request leases can temporarily delay callers after
adapter restarts. The existing five-minute expiry is crash recovery, not a promise
that a request needs five minutes. Initial failures are retained as evidence.

After expiry, public HTTPS checks pass for initialization, strict schemas and
argument rejection, matching workflow hash, fetch, block inspection, MCP-to-REST
document continuity, one-page crawl, fresh search, local speech extraction, browser
checkpoint/cleanup and research coverage. An independent SDK 1.28.1 client completes
six reading-workflow events. Public REST rejects the misspelled `category` with 422.
A fresh public CarGurus diagnostic remains failed, with a headed navigation error
and a workflow action requesting browser pixels; it does not count as a bypass.
All five workers report ready. Both MiniLM and E5 contain 10,355 passages / 3,652
pages at this verification snapshot; backfill reports complete. Counts may grow
as other callers index sources. Raw public checks and the failed first attempt
are included in the evidence directory.
