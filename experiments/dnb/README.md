# DNB browser consolidation prototype

An isolated experiment against Dethrottled **1.7.1**, commit
`9ad5fa36a6290c442fcfcc9aebeb8bdcf6a4aa80`. Production code, deployments,
package versions and releases are unchanged. Rust is outside this experiment.

DNB imports the existing browser-search service, retaining its Patchright search,
27 drive actions, scoped sessions, checkpoints, downloads, graphics selection,
recovery recipes and browser watchdog. It adds a bounded `/crawl` adapter which
captures pages in isolated contexts in the same warm headed browser, then runs
Crawl4AI 0.9.5's default scraper and Markdown generator in two bounded Python
worker processes inside the same container.
There is one Chromium installation and one browser process tree; neither
`AsyncWebCrawler` nor a second Playwright browser is started.

This retains upstream extraction code and its Apache-2.0 attribution in the
installed distribution. Patchright and other dependencies retain their installed
licenses. It is browser consolidation, not a new browser engine or a claim of
universal anti-bot access. See the [initial measured pilot](results/2026-11-06/REPORT.md) and the
[caller-isolated reuse follow-up](results/2026-11-07/REPORT.md). The current
default and security decisions are in [the scope review](results/2026-11-07/SECURITY-SCOPE.md).

## Current progress — 2026-11-08

**Phase 1 is complete for the local x86_64 DNB worker.** Its 33 focused tests and
real HTTP cancellation/crash gates passed. See the [acceptance record](results/2026-11-08/PHASE-1.md),
[wire results](results/2026-11-08/phase1-wire.json) and
[source/image provenance](results/2026-11-08/phase1-provenance.json).

**Phase 2 is complete for the isolated x86_64 worker.** Sixty focused tests and
an offline real-Chromium gate passed, including the actual `/crawl` and `/drive`
handlers under the image's normal non-root user. Public CDN JavaScript/CSS,
frames, popups and service-worker fetches remained usable. Forbidden navigation,
a synthetic adblock target and a private redirect received **zero TCP connections**.
See the [phase-2 acceptance record](results/2026-11-08/PHASE-2.md),
[results](results/2026-11-08/phase2-wire.json) and
[provenance](results/2026-11-08/phase2-provenance.json). The earlier real HTTP
cancellation/crash gate also passed again on this image; see
[the lifecycle replay](results/2026-11-08/phase2-lifecycle-regression.json).

**Phase 3 is accepted for the isolated x86_64 worker.** Twenty-three wire checks and
twenty-five focused regressions passed, plus the rerun phase-1/phase-2 units. The
repo adapters forward the verified caller credential to the core; the core
re-verifies it and accepts it only from configured adapter peers. Drive sessions
and checkpoints are bound to the first verified owner, and completed drive
operations are durably replayable across a restart while `running`/`unknown`
outcomes remain non-replayable. Rotation, replay, spoofed headers and log
redaction were exercised through real REST/MCP paths. See the
[phase-3 acceptance record](results/2026-11-08/PHASE-3.md),
[wire results](results/2026-11-08/phase3-wire.json) and
[provenance](results/2026-11-08/phase3-provenance.json).

**Phase 4 is accepted for the isolated lab.** The search-and-fetch PDF bloat was
confirmed and fixed: concise output now removes duplicated `native_pdf_tables`
and `layout_tables` while detailed output is unchanged. A real 20-page table PDF
dropped from 104,127 to 4,396 bytes in concise mode. The cache-accounting report
was unconfirmed through the public `CacheView` path; the raw-`Cache` footgun is
now closed by a shared extract-shape validator, with a refetch regression. The
DOM report was confirmed end-to-end: the DNB renderer dropped source HTML for
selector callers, and now retains it; a real `/fetch` selector changed from
`html_unavailable` to satisfied. See the
[phase-4 acceptance record](results/2026-11-09/PHASE-4.md).

**Phase 5 is accepted for the isolated lab.** A matched headed/headless x
software/verified-hardware matrix ran on the AMD Vega iGPU. `auto` with
`/dev/dri` and the render/video groups verified hardware via WebGL pixel
readback; without the device, and with the device present but its groups not
granted, it fell back to llvmpipe with `hardware_verified=false`. Five modes,
three repeats of six loads (90 reads) and three screenshots per mode retained all
predefined facts, with no restarts; CPU, RSS, screenshot latency, and Chromium
raster/compositing feature status were recorded. Headed remains the default;
`auto` remains the graphics default and `mesa` is the explicit software baseline. See the
[phase-5 acceptance record](results/2026-11-09/PHASE-5.md).

**Phase 6 prep is complete.** Candidate source is frozen at `735d420` and tagged
`phase5-candidate-20261109`; image
`dethrottled-dnb:1.8.0-candidate-20261109` is built from the frozen reference.
A disposable parity smoke passed both reference and candidate for 27 facts, all
27 drive actions, downloads, network evidence, concurrency and checkpoint
restore. Resource smoke shows the candidate at higher CPU than 1.7.1, as
expected from consolidation. ARM64 `q6a` is reachable but still needs its own
build/parity run. See [the prep record](results/2026-11-09/PHASE-6-PREP.md). Phase 6 execution has
started: the candidate API image is built and its first PDF parity smoke passes
with the expected concise-table presentation difference; layout, mixed-batch and
ARM64 runtime checks also pass, as do media/live/hostile parity, packaging and
install routes, mixed-load/crash containment and rollback preservation. Only the
approved 1.8.0 version bump and release remain; the approval checklist is in
[the release gate](results/2026-11-09/PHASE-6-RELEASE-GATE.md) and the full record
in [the Phase 6 progress record](results/2026-11-09/PHASE-6.md).

| Phase | Status | Remaining work |
|---|---|---|
| 1. Bounded execution, cancellation, retries | Accepted in the isolated x86_64 worker | Keep this gate passing through later changes; native/release validation is still required |
| 2. Navigation and assets | Accepted in the isolated x86_64 worker | Keep the scoped-navigation/CDN gate passing; broader compatibility and native gates remain in phase 6 |
| 3. Verified identity/integration | Accepted in the isolated x86_64 worker | Keep the REST/MCP/worker gate passing; full compatibility remains phase 6 |
| 4. Inherited defects | Accepted in the isolated lab: PDF bloat and DOM adoption fixed; cache validator hardened | Keep the concise-size, DOM and cache regressions; full parity remains phase 6 |
| 5. Browser modes/GPU | Accepted in the isolated lab: matched headed/headless x software/verified hardware matrix | Keep the probe and fallback regressions; native/release validation remains phase 6 |
| 6. Candidate and release | Technical checks complete: parity, media/live/hostile, ARM64, packaging/install, load/crash/rollback | 1.8.0 version bump, final artifact rebuild and release approval |

Production stays on 1.7.1. This branch remains unpublished development work;
1.8.0 is not declared ready. The 1.8.2 DPR document is saved planning only.
The new extractor processes change the resource footprint: old pilot CPU/RAM
figures must not be presented as measurements of this candidate.

## Run the disposable lab

Requires Docker Engine, Compose and Python 3 on an x86_64 test host. Native ARM64
validation is still pending. Reserve loopback ports **19981–19983**. Run from the
prototype checkout root, not from a production checkout:

```sh
# Build the reference from the frozen source in a SEPARATE checkout, or tag an
# already verified immutable reference image as dethrottled-dnb-browser:reference.
# Never tag an unverified current worker as the reference.
docker build -f browser-search/Dockerfile -t dethrottled-dnb-browser:reference .
docker build -f experiments/dnb/Dockerfile -t dethrottled-dnb:prototype .
docker compose -f experiments/dnb/compose.yml up -d --wait
python3 experiments/dnb/compare.py /tmp/dnb-comparison
python3 experiments/dnb/verify.py /tmp/dnb-comparison
python3 experiments/dnb/measure.py /tmp/dnb-resources.json
# Optional small, paced live pilot; never run concurrently with resource tests.
python3 experiments/dnb/compare.py /tmp/dnb-live --live
docker compose -f experiments/dnb/compose.yml down --volumes --remove-orphans
```

The current offline phase-2 gate is self-contained and publishes no ports:

```sh
# Uses a built image, an isolated internal network and synthetic block rules.
# Requires this test subnet (11.253.72.0/24) to be free of Docker/VPN conflicts.
DNB_IMAGE=dethrottled-dnb:phase2-accepted-20261108 \
  experiments/dnb/phase2_lab.sh /tmp/dnb-phase2
```

It keeps results/failure logs and removes its own container/network on exit. Its
fixture certificate is trusted only by that disposable test browser. It neither
downloads a list nor contacts upstream sites. The earlier Compose comparison and
`verify.py` remain parity harnesses to rerun in phase 6; their historical results
do not certify the current candidate.

The phase-1 wire harness is `phase1_check.py`: it requires PyJWT[crypto]/httpx,
a privately generated signing key, an isolated worker on loopback port 19985,
and the same fixture published on 19987. It restarts that lab worker deliberately;
see its docstring and the acceptance record before use. Never point it at production.
Historical `pool_bench.py`/`security_check.py` header fixtures predate signed
delegation and need the phase-3 protocol migration before reuse on this candidate.

Use the frozen 1.7.1 browser sources for the first build; this prototype checkout
has not modified them. Record image IDs, `docker inspect` output and
`/app/dnb-dependencies.txt` after building. The prototype pins direct dependencies;
its recorded transitive inventory describes the tested image, not a cross-platform
release lock. Do not claim reproducibility from the image tag alone.

The lab enables trusted internal fixture URLs and disables filtering for the
like-for-like acquisition comparison. These are experiment settings, not proposed
production defaults. The candidate otherwise rejects non-public destinations;
existing browser policy gates redirects and subresources. No production cookies,
models, volumes or account state are mounted. The lab's token is disposable and
confined to its loopback/private network. Never publish these worker ports.

`verify.py` checks fact retention, all actions, exact download bytes, network
facts, screenshots and concurrent render/drive operation. It restarts both browser
workers to verify actual checkpoint restoration. Explicit `close_session` deletes
checkpoints and is deliberately not used as evidence of restoration.

## Contract and deliberate limits

- Existing search and drive actions are retained. Drive now has bounded
  request/disconnect handling and journal preflight; its original mutation journal
  remains authoritative. `/dnb/status` exposes queue, active work and extractor
  counters alongside prototype identity.
- `/crawl` implements the actual single-URL subset used by Dethrottled 1.7.1,
  not Crawl4AI's entire API. Unknown options fail validation. There is no arbitrary
  JavaScript execution, LLM extraction, deep-crawl, scheduled job or screenshot API
  added to `/crawl`; `/drive` retains its existing screenshot/actions contract.
- Supported configs: `BrowserConfig.headless` (requested mode recorded, **effective
  mode is headed**), and `CrawlerRunConfig` bypass, no worker robots check,
  100–30,000 ms navigation budget, 0–5 s settling and optional `css:` wait.
  API-owned site policies remain outside the worker as in the existing adapter.
- Two active reads, four waiters, five-second queue wait and two warm extraction
  processes. Per extractor: 12-second job deadline, 2-GiB virtual-address-space cap,
  eight-second additional soft CPU allowance, 60-second hard lifetime CPU cap and
  recycling after 45 CPU-seconds. Workers/process groups are stopped and reaped
  before capacity returns. HTTP inputs are bounded to one MiB; acquired HTML still
  has the prototype's eight-MiB compatibility limit.
- Real HTTP disconnects cancel read/drive work. Three-second bounded cleanup
  fails closed by restarting an unresponsive worker. Container restart supervision
  is required; that restart may interrupt other requests. The test lab has a
  4-GiB/4-CPU/1,024-PID ceiling, not a universal machine requirement. The complete
  retry, replay and unknown-mutation rules are in the phase-1 acceptance record.
- Anonymous or insufficiently scoped reads receive fresh contexts. The trust work
  uses signed `X-DNB-Delegation` claims and `DNB_TRUST_PUBLIC_KEY`; configured
  verifiers are checked before readiness. Workers receive public-key access only.
  Legacy bearer-authorized owner headers are rejected. Phase 3 adds a trusted
  adapter peer gate for the forwarded caller credential, owner-bound drive
  sessions/checkpoints and a durable completed-operation journal. Keep private
  worker ports off public networks. Do not infer production readiness from this
  lab contract.
- Reuse keys separate owner, explicit session, security-scope label, exact origin,
  public/internal and host policy, supported browser configuration and page mode.
  At most four contexts remain, with a 60-second idle TTL, ten-second reaper
  and recycling after 200 reads. At memory pressure (85% cgroup memory usage,
  or less than 15% host memory available when unlimited), idle entries are evicted
  and new admissions pause while pressure persists. Busy contexts are not evicted.
  The least recently used idle entry is destroyed when capacity is needed; busy
  entries are never evicted or concurrently used. Busy same-session requests
  return HTTP 409; a full active pool returns 503. Failed operations discard the
  context. A restart destroys all retained render state.
- Signed `page_mode="fresh"` is the authorized reuse default: retain the owner's
  cookies/local storage/IndexedDB, replace pages and reset tab session storage.
  `persistent` is an explicit option that reuses its tab on each navigation; session
  storage and same-owner state remain. Both modes park on `about:blank` after
  capture so the source DOM and its timers do not remain live between reads.
  The entire worker remains experimental. Contexts are
  never reassigned or sanitized for another owner. Rendering and `/drive`
  maintain separate pools, and extra renderer popups are closed on release.
- Render and drive context traffic uses the existing HTTP/CONNECT gate with a
  pinned connector: resolve once per connection, reject non-public/mixed answers
  in public scope, and dial the validated numeric IP. HaGeZi remains independent;
  disabling it does not disable network admission. TLS stays native, without MITM.
- Document navigation and assets have separate authority. `allowed_hosts` scopes
  documents, including frames, popups and every redirect. Ordinary public assets
  may use other public hosts through the IP/filter gate. Internal scopes require
  the operator's existing opt-in; their assets default to document hosts. Only a
  trusted signed `asset_hosts` claim can add asset destinations. An explicit empty
  asset list restricts assets to document hosts, including in public scope. It is
  an internal delegation claim, not a new public REST/MCP switch. Active drive
  sessions reject policy changes with 409; read reuse keys include asset policy.
  Internal requests without a navigation host infer the initial URL's host; blank
  unscoped internal operations fail closed. No permission is learned from a page.
- A single browser CDP policy client intercepts requests before new pages resume;
  the overlapping prototype Playwright route handlers are replaced. Redirects
  are checked even on reused connections, without disabling service workers.
  Its random loopback debugging endpoint is private to the worker and denied by
  the browser's connector even for internal scopes. Unexpected policy transport
  loss closes the browser. No worker/debug port should be publicly exposed.
  Automatic gateway integration and authenticated checkpoint/owner binding are
  accepted for the isolated worker in phase 3; wider browser compatibility and
  performance require phases 5–6.
- Render results retain raw/cleaned HTML, Markdown, links, metadata, target status,
  access assessment, recovery and blocking diagnostics. Blank Markdown, observed
  challenges/login walls and HTTP errors are reported as failures. This does not
  certify answer accuracy, document completeness or long-term source availability.
- The public API still decides which extraction to adopt. In 1.7.1 its Crawl4AI
  adapter adopts sufficiently long Markdown before HTML; consolidation does not
  silently change that evidence/DOM contract.

## Later release planning

The [DPR 1.8.2 implementation proposal](../../docs/plans/1.8.2-DPR.md) is retained
unchanged from the supplied brief. It proposes programmatic single-item and durable
bulk acquisition after DNB and stabilization. Saving this proposal does not approve
its implementation, fix release dates or change the current 1.8.0 scope.

## Pending 1.8.0 plan

Phase status and evidence are tracked above. A local phase acceptance is not
release acceptance; the remaining phases and their exit gates still apply.
Keep 1.7.1 frozen as the reference and leave production unchanged during this
work. Rust, paid dependencies and speculative ranking changes remain excluded.
Preserve search policy, cache/corpus lifetimes, evidence and API compatibility.

Complete the reliability and trust phases before tuning performance. Use small
controlled tests first, retain failures and compare identical workloads. Repeat
only checks invalidated by a subsequent change. A phase closes with retained
results or an explicit unresolved blocker, not an assumption of success.

### Phase 1 — Bounded execution, cancellation and retries

**Status:** accepted for the local worker on 2026-11-08; see the acceptance record
above. The requirements below remain regression gates, not unfinished tasks.

**Outcome:** a stalled or abandoned request cannot permanently consume capacity
or trigger an uncontrolled retry pile-up.

- Replace unkillable threaded extraction with bounded, separately terminable work.
  Evaluate a small worker-process arrangement inside the existing container;
  additional containers are not the default solution. Enforce wall-clock and
  memory/CPU limits, terminate and reap timed-out jobs, and replace failed workers.
- Bound browser acquisition too. One pathological page must not permanently occupy
  the shared browser. An HTML-size limit alone does not bound processing cost.
- Handle actual HTTP disconnects as well as task cancellation. Release a slot only
  after its underlying work stops; relabelling it or releasing a semaphore while
  its thread continues does not restore safe capacity accounting.
- Reuse existing operation/admission machinery where appropriate. Define
  `retryable`, bounded retry delay/Retry-After, scoped operation IDs, handling of
  retries while work remains in flight, and safe semantics for mutating drive steps.

**Exit gate:** controlled stalled jobs, disconnects, cancellation, retry bursts,
worker failure and malicious HTML recover within the stated bounds; an unrelated
healthy caller can subsequently complete. Do not call finite slot occupancy a
deadlock or claim complete resource isolation from a bounded input alone.

### Phase 2 — Navigation scope and usable subresources

**Status:** accepted for the local worker on 2026-11-08; see the acceptance record
above. The requirements below remain regression gates.

**Outcome:** ordinary pages can load their assets without opening a route outside
the caller's permitted security boundary.

- Separate document-navigation scope from asset-egress policy. Ordinary public
  reads should not require callers to enumerate every CDN host. Public asset
  access still requires DNS pinning, HaGeZi filtering, redirect checks and
  credentials/origin isolation; it must never permit access to private networks.
- Use an explicitly trusted egress policy for authenticated internal scopes.
  Public-by-default assets may leak internal data and are not a universal policy.
  Never learn permissions from an unconstrained first fetch: observed hosts are
  diagnostics, not authority.
- Enforce restrictions before network access, including redirects over reused
  connections, frames, popups and service-worker requests. Browser route callbacks
  alone were insufficient in the controlled probe.
- Preserve 1.7.1's API meanings or document an intentional compatibility change.
  Resolve the prototype's stricter all-subresource allowlist without silently
  widening internal scope or breaking legitimate asset-backed content.

**Exit gate:** representative CDN-backed pages retain their useful facts, while
forbidden destinations receive no connection. DNS rebinding, redirects and
filtering regressions pass with both new and reused contexts.

### Phase 3 — Verified identity and automatic gateway integration

**Status:** accepted for the isolated x86_64 worker on 2026-11-08; the public
adapter path was simplified and re-accepted on 2026-11-09. The public adapters
authenticate the bearer and forward the same verified credential; the core
re-verifies it and accepts it only from `DETHROTTLED_ADAPTER_CIDRS`. There is no
adapter signing key. "Gateway-only private signing" below means the core API,
which is the gateway to the private worker; it remains the sole minter of the
worker delegation. See the phase-3 acceptance record.

**Outcome:** agents reach safe reuse automatically without choosing trusted owner
headers, and one leaked admission credential cannot select every cookie jar.

- Derive owner, session and security policy from the existing gateway's verified
  claims. Keep reuse partitioned by caller, explicit session, security scope,
  effective browser configuration and applicable network/origin policy. Anonymous
  or insufficiently scoped requests remain isolated.
- Replace bearer-authorized arbitrary owner selection with short-lived,
  integrity-protected delegation bound to audience, operation/request, owner,
  session, scope and effective policy/configuration. Separate admission credentials
  from signing authority.
- Prefer gateway-only private signing and worker public verification if supported
  cheaply by existing dependencies. In this implementation the core API is the
  gateway to the private worker; public adapters do not sign. Choose one standard
  mechanism, not a custom crypto protocol or more operator profiles. HMAC with
  the bearer secret is not a fix; even a separate HMAC secret remains forgeable
  if exposed. Signatures do not protect cookie jars from a fully compromised
  gateway or worker process.
- Carry the verified identity through REST, MCP and autonomous escalation. Retain
  existing bounded reuse, expiry, request limits, memory-pressure eviction and
  exclusive context use; do not share state across security scopes.

**Exit gate:** real API/MCP requests exercise cold and reused paths automatically.
Tampering, expiry, wrong audience/scope, spoofed headers, replay/idempotency,
rotation and concurrent cross-caller storage tests pass. Logs expose no secrets.

### Phase 4 — Inherited defects and presentation compatibility

**Status:** accepted for the isolated lab on 2026-11-09; see the phase-4
acceptance record. The report matrix was reproduced: PDF bloat was confirmed and
fixed in REST and MCP, cache accounting was unconfirmed through the public path
but the raw-`Cache` footgun was closed, and DOM adoption was confirmed end-to-end
and fixed for selector callers. Full parity remains phase 6.

**Outcome:** response size and cache metrics are trustworthy before release
benchmarking. Treat these reports as unconfirmed until reproduced; the 2026-11-09
outcome is recorded above and in the acceptance record.

- **Search-and-fetch bloat:** inspect `server.py::search_and_fetch()`,
  `SearchFetchBody` and MCP presentation. Check whether large PDF metadata bypasses
  concise output despite small `max_chars`. If confirmed, add consistent
  concise/detailed REST/MCP support while preserving existing defaults,
  compatibility, retained evidence and provenance. Test large PDFs and mixed
  source batches.
- **Cache accounting:** inspect `Cache.get()` and `CacheView.get()` for malformed
  decoded entries counted as hits before rejection. If confirmed, correct
  minimally without changing expiry or valid empty-result handling.
- **DOM adoption:** retain the tiny-page selector/HTML regression in end-to-end
  parity checks. Consolidation alone does not prove that adoption preserves DOM.

**Exit gate:** each report has a confirmed/unconfirmed finding, focused regression
coverage where justified, and retained before/after evidence. Avoid unrelated fixes.

### Phase 5 — Browser modes and GPU defaults

**Status:** accepted for the isolated lab on 2026-11-09; see the phase-5
acceptance record. The matched matrix used the AMD Vega iGPU with and without
`/dev/dri`; `auto` verified hardware via WebGL pixel readback and fell back to
llvmpipe without the device. Headed remains the default, `auto` remains the
graphics default, and `mesa` is the explicit software baseline.

**Outcome:** choose execution defaults from useful-content and resource evidence,
with a reliable software path on machines without usable GPU access.

- Compare headed and headless Patchright using identical lifecycle, scope, workload
  and settle settings. Both reference and prototype already keep Chromium warm;
  context/page lifecycle is not cold Chromium startup. Keep fresh pages as the
  scoped-read default unless additional evidence supports a change.
- Cross browser mode with software rendering and verified hardware acceleration
  where available. Start with static text, heavy JS, canvas/WebGL, screenshots and
  a few paced recovery targets. Measure retained facts, failures, latency, CPU,
  GPU use, RAM/shared GPU memory and stability; expand only if warranted.
- Reuse the existing graphics `auto` startup probe: render-device candidate,
  Chromium launch, renderer identity and actual WebGL pixel readback, with software
  fallback. Check actual raster/compositing feature status and GPU crashes too.
  Device presence or a renderer name alone does not prove acceleration. Probe per
  browser launch, not on every request.
- Let managed installation discover accessible devices and actual group IDs before
  generating optional mappings. Containers cannot grant themselves host access.
  Do not automatically install drivers/system packages. Treat Intel/AMD devices,
  NVIDIA runtime needs and ARM drivers as separate supported-host cases.
- Let Chromium coordinate CPU/GPU work. Do not duplicate reads or introduce a GPU
  worker merely to claim parallelism. A second browser mode must share the existing
  Chromium installation, start only when needed and have a bounded lifetime; count
  its RAM cost. Keep headed recovery where it adds verified reads.

**Exit gate:** measured normal/recovery defaults preserve source coverage and
fall back cleanly when hardware is absent, inaccessible or fails. Do not include
unmeasured headless/GPU speedups in release claims.

### Phase 6 — Frozen candidate, parity, packaging and release

**Outcome:** a reproducible 1.8.0 candidate preserves the capabilities people use,
and every release claim traces to evidence.

- Freeze one runtime/workload candidate. Compare against frozen 1.7.1 through the
  actual REST/MCP paths: discovery, automatic escalation, all drive actions,
  sessions/checkpoints, downloads, selectors, research and retained evidence.
- Cover PDF/OCR/Office/media/layout integration and optional workers. Reconcile the
  prototype's eight-MiB HTML ceiling with existing acquisition limits. Keep source
  warnings, partial/truncated state, provenance and continuation instructions.
- Run representative paced live/hostile-source comparisons with predefined facts.
  Preserve blocked/thin/suspect outcomes; transport success and character counts
  are not proof of usable evidence or anti-bot recovery.
- Validate mixed-load behavior, long-running memory use, shared-browser crash
  containment, restart and recovery. Admission slots do not reserve Chromium CPU;
  browser consolidation also combines failure boundaries. Retain a separate
  browser strategy if it adds verified coverage.
- Pass native x86_64/ARM64 build/runtime and reproducible dependency/image gates.
  Exercise fresh PyPI managed-stack and GitHub installation routes outside the
  source checkout, including software fallback and optional profiles. Record
  unique disk usage separately from logical image sizes and measure whole-stack
  resource needs without attributing optional-worker costs to DNB.
- Reconcile Compose, bundled deployment/build context, CLI/worker management,
  versions, licenses and all relevant human/agent/API/MCP docs. Preserve dated
  reports and sanitize retained evidence. Repeat earlier gates when fixes change
  their assumptions; do not erase the original failures.

**Exit gate:** parity and installation evidence support replacement, limitations
are explicit, docs/checks pass, and rollback preserves existing data. Publication,
GitHub/PyPI release and production deployment require separate approval. After
approval, verify delivered artifacts, actual running source and API/MCP identity.

The acceptance standard is bounded recovery, usable sources, verified isolation
and preserved evidence. A smaller image is a benefit, not a substitute for those
gates. Current work moves to phase 6 while release gates remain; publication and
deployment still require separate approval.
