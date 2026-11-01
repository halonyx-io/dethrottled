# Recovery gaps: 0.9.0 to 0.9.1

> Historical evaluation: the measurements and deployment statements below describe
> the recorded release, not current installation instructions. Use the
> [current guides](README.md) and [evidence index](EVIDENCE.md) for context.

This follows the [D1–D5 review](REVIEWED-BOT-FINDINGS.md). D6 is excluded. The
release closes measured browser/reader gaps; it does not establish a higher
commercial anti-bot bypass rate.

## Shipped decisions

| Gap | Change | Evidence |
|---|---|---|
| D1: waiting for DOMContentLoaded can consume the read deadline before usable text is read | Internal headed reads navigate to `commit`, then inspect the DOM; blank documents still loading are polled. Explicit drive retains its normal DOMContentLoaded default. Network/navigation errors still fail. | JavaScript-produced report followed by a 20-second blocking script: old explicit headed read fails after 12.3 seconds, new read recovers the fact in 1.1 seconds. |
| D2: browser-side response headers ignored, and two live wall texts missed | Carry only `cf-mitigated` from initial navigation into detection; recognize observed session-verification text and the paired Expedia human/bot message. | Header/loading unit checks plus recorded live messages and negative quoted-article controls. Persistent walls still fail. |
| D3: speculative transfer of browser clearance into TLS | Retain caller/exact-host browser checkpoints; do not add cookie export or full profile directories without evidence of an access benefit. | Existing four challenged reads and plain control still recover; same caller reuses clearance, another caller earns its own. |
| D4: busy headed reads discarded after 100 ms; script-only failures still need an expert flag | Keep one active read but add bounded round-robin admission. A nearly empty HTML shell containing script/iframe markup can automatically reach headed acquisition. | Six simultaneous reads: 1/6 facts before, 6/6 after. Two script-only fixtures fail under old defaults and recover under new defaults, without `headed_fallback`. |
| D5: WebGL unavailable | Install EGL/GLES runtime libraries and enable a selectable Mesa/ANGLE GL profile in Compose. No GPU passthrough or fingerprint injection. | WebGL 1/2 available; real red-pixel readback unlocks fixture text. Sannysoft reports actual Mesa/llvmpipe; selected existing checks remain passing. |

Snapshots captured while the document is still loading, or cut by the HTML
capture limit, are explicitly partial. Warnings, source-partial metadata and a
workflow action let an agent inspect visible text after normal document loading
when more evidence is needed. Capturing an early useful fact does not establish
that the entire source was read. Queue time, loading/challenge polls, ready state
and initial navigation are reported separately.

Default automatic browser recovery remains conditional: recognized challenges or
script-only shells, or an explicit headed request. Readable ordinary prose still
returns from direct acquisition. Explicit render restrictions win. The existing
Crawl4AI tier remains ahead of headed acquisition.

## Experiments rejected or still unresolved

The host has an AMD render device, but passing it into a test container did not
produce hardware WebGL. EGL plus ANGLE GL and the blocklist override produced
llvmpipe software WebGL both with and without that device. Device passthrough is
therefore not shipped. This exposes the actual software renderer; it does not
pretend to be an AMD GPU. The profile overrides Chromium's compatibility
blocklist, so operators can select `default` if graphics causes trouble. No unsafe
SwiftShader opt-in is used. CPU rendering can cost more on graphics-heavy pages.

Persistent Chromium 153.0.8010.12 and persistent Google Chrome 156.0.8078.79 were
also tested in isolated containers, with Mesa and no viewport override. Both
failed to recover the four hostile sources; both read the Python control.
Full-profile and Chrome replacement work is rejected for this release because
neither demonstrated additional access. Chrome is not added to production.
CreepJS still has no defensible aggregate score from these runs.

The same four hostile sources—CarGurus, Crunchbase/OpenAI, G2/Notion and Expedia—
still yield **zero successful reads** with both the old and candidate headed
workers. CarGurus still fails navigation; switching to commitment does not cure
that navigation/response error. Crunchbase retains a challenge, G2 can return an empty
403, and Expedia returns a human/bot wall. No HTTP code alone establishes an IP
reputation cause. There is no automatic arbitrary CAPTCHA interaction in this
release. The prior admission-lease delay after adapter restarts also remains
unfixed; deployment need not restart unchanged adapters.

## Tests and limits

The controlled JavaScript fixture generates its report in JavaScript, so direct
and TLS extraction cannot read the answer. The WebGL fixture reveals its report
only after an actual red-pixel readback. End-to-end probes use the core acquisition
ladder with Crawl4AI unconfigured to isolate headed behavior, first explicitly and
then under default options. They are not claims that every production URL needs
this tier or that the old full stack would always fail those pages.

Initial reader-only probes used a static report followed by a slow script;
`fixture_initial.py` preserves that version. End-to-end and default-workflow
probes use `fixture.py`, where JavaScript generates the report. Both versions are
included so the narrower preliminary measurements are not confused with the
stronger final ones. A first baseline run happened before browser readiness and
is invalid; it is not used in before/after counts. The initial API harness also
expected a bare `headed` tier, whereas the API correctly returns composite
`tier/extractor` names; the corrected assertion checks the acquisition prefix. A profile harness initially
could not write its result file; the corrected run is recorded separately.

Three live search queries return 10/9/10 results on both workers. These samples
show no observed search regression, not exhaustive equivalence. Live hostile
observations are subject to upstream variation. Pixel rendering and fixtures are
controlled tests, not a substitute for verified facts on real protected sites.

The final suite and public deployment checks are retained in
[the evidence directory](benchmarks/2026-11-01-recovery-next/). SDK argument
strictness, document continuity, format/speech/layout workers and the dual corpus
from the preceding releases remain part of the system; this release does not
claim to reimplement them.

## Best next steps

1. Obtain exact task URLs, expected facts and raw failures from remote agents.
   Expand the frozen benchmark; do not optimize to green fingerprint pages.
2. Trace the remaining navigation failure at the actual response/transport
   boundary. Any workaround must prove a committed usable source and must not
   reinterpret a browser error page or stale DOM as success.
3. If interactive challenges dominate that benchmark, evaluate an agent-driven
   visual interaction loop using the existing screenshot/iframe/action endpoints
   and a local vision model. No such model or general solver is installed here;
   success and resource requirements need an experiment first.
4. Fix adapter admission lease reclamation with process-lifecycle tests separately.
   Raising concurrency limits does not address stale ownership.

Patchright's [recommended browser setup](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python)
was evaluated, not taken as proof of access. Playwright documents the distinction
between [commit and DOMContentLoaded](https://playwright.dev/python/docs/api/class-page#page-goto).
Chromium defines the [GPU blocklist override](https://chromium.googlesource.com/chromium/src/+/main/gpu/config/gpu_switches.cc)
and separately describes the [unsafe SwiftShader opt-in](https://github.com/chromium/chromium/blob/main/docs/gpu/swiftshader.md).

## Final verification

0.9.1 is deployed. The suite reports **578 passed, 15 skipped, 2 network tests
deselected**, with four existing FastAPI lifespan deprecation warnings. Lint
passes. The isolated API recovers both JavaScript-only fixtures without a headed
flag; its early snapshot is explicitly partial and provides a browser follow-up.
Public HTTPS MCP/REST initialization, schema checks, workflow hash, document
continuity, fresh search, speech, crawl, checkpoint/cleanup and research pass.
An independent MCP SDK client completes its six-event read workflow. A public
MCP browser call verifies the working Mesa renderer, and all five workers report
ready. Browser and core source hashes match the reviewed checkout before
promotion. Unchanged public adapters were not restarted; protected rollback
backups were retained. Registry, environment file and routing were unchanged.
