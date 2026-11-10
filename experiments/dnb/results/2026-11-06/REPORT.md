# DNB consolidation pilot — 2026-11-06

**Decision:** continue this architecture as an experiment; do not replace 1.7.1
production yet. One headed Patchright browser can support the tested search,
interaction and Crawl4AI extraction paths with much lower image size and working
memory. CPU per isolated render is higher. Full capability parity is not proven.

## Frozen reference and implementation

Reference: Dethrottled 1.7.1, source
`9ad5fa36a6290c442fcfcc9aebeb8bdcf6a4aa80`. Reference image IDs and candidate image
identity are in [summary.json](summary.json). Existing browser service/recovery
files match the reference byte for byte. Production was not modified.

The candidate imports the existing Patchright 1.63.0 browser service. A new
single-URL `/crawl` adapter uses isolated contexts in that browser and upstream
Crawl4AI 0.9.5 default scraping/Markdown code. No second Chromium, Redis server,
Crawl4AI HTTP server or model is started. The Python Playwright package remains a
transitive dependency; this is not a claim to have removed all Playwright code.
Installed Crawl4AI carries its Apache-2.0 license. The dependency inventory is
retained [alongside the results](dependency-inventory.txt).

The official renderer image contains two Chromium/headless-shell revisions under
its app user's cache and another root browser cache. The candidate has one
393-MiB browser installation. This explains much of the image reduction; rewriting
browser control in Rust was not needed to obtain it.

## Measurements

Host: x86_64 mini PC, AMD Ryzen 7 5800U, 16 logical CPUs, approximately 30.8 GiB
available container memory ceiling. Software rendering, no GPU devices passed.
Background production workloads remained running. A load-average snapshot near
the tests was 1.62 / 1.75 / 1.46; this is not a dedicated idle-host benchmark.

Resource workload: three rounds per variant, ten sequential fixture renders per
round, alternating article/long HTML, with 0.5-second settle on every request.
Order was reference/candidate, candidate/reference, reference/candidate. All
60 resource-workload requests succeeded. Cgroup CPU counters include the reference
browser + renderer containers together, versus the candidate's single container.
Docker working-set samples were taken during each phase; 12 samples per variant.
Fixture server and API are excluded equally. Raw samples are in
[resource-samples.json](resource-samples.json).

| Metric | Frozen two-worker reference | DNB candidate |
|---|---:|---:|
| Logical uncompressed image size | 1.39 + 7.62 GiB | 2.24 GiB |
| Median observed working set | 832.3 MiB | 409.2 MiB |
| Highest sampled working set | 843.0 MiB | 449.6 MiB |
| Median request latency, 30 requests each | 661.4 ms | 657.6 ms |
| Median CPU-seconds per ten renders | 2.65 | 6.79 |

The observed median working set is about 51% lower. Image totals share some layers
and **are not unique disk savings**. The latency difference is too small to call
an improvement. CPU is about **2.56 times** the reference on this warm workload.
CPU-seconds measure consumed processor time, not wall time or CPU percentage.
The main API and optional document/media/model workers were not reduced.

An initial resource run overlapped live requests; it is retained privately and
excluded above. The reported run did not overlap other lab acquisition tests.
There were still uncontrolled host workloads, so interpret absolute timings with
that limitation. Sampled memory is not a continuously observed peak or a minimum
hardware requirement.

## Controlled capability checks

Five fixture paths, three repetitions, both variants: article with delayed
JavaScript, tiny page, long HTML, redirect and HTTP 404. Known markers covered
initial, delayed and final content. Both variants retained **27/27 fact checks**
in returned Markdown. Markdown hashes matched in **all 15 paired captures**.

Reference Crawl4AI marked the tiny page as an anti-bot failure despite preserving
its fact; DNB returned it without that false classification. Both reported the
404 as failed. Fact retention is reported separately from the success flag and
is not proof of general extraction completeness. These are controlled HTML
fixtures, not a new PDF/OCR benchmark.

Both workers completed **all 27 existing `/drive` actions**, with assertions for
confirmation text, iframe content, screenshot presence, exact downloaded bytes
and the captured JSON network fact. Both passed simultaneous two-render/one-drive
fixture requests. Checkpoints restored after an actual worker restart. An initial
harness used `close_session`, which deletes checkpoints; that did not prove
restoration and was replaced by the restart assertion.

A fresh, isolated **unchanged 1.7.1 API image** was pointed at DNB for both worker
URLs. `/fetch` with `render=always`, a CSS wait and cache bypass reached
`crawl4ai/crawl4ai-native` and retained all three article markers. API `/drive`
read the delayed JavaScript fact. Public/MCP infrastructure was not changed.

Tests: **17 prototype regressions passed**, plus **72 existing drive/recovery/
adblock regressions passed**. Public-target rejection before context creation,
bounded config validation, navigation-failure cleanup and admission release are
covered. The real browser filter test used an explicitly synthetic 10,000-rule
snapshot: blocked top-level URL, blocked redirect, blocked script subresource
with legitimate article retained, and drive access with the same blocker active.
This validates wiring, not the real list's coverage or its production memory cost.

## Live pilot and negative results

Six URLs were acquired once per variant with pacing: Example, Reddit Python,
Wikipedia HTTP, MDN JavaScript, Booking and Crunchbase. One DDG discovery query
per browser returned five choices including the official Python documentation.
This small pilot is not sufficient to rank search quality or anti-bot performance.

The first candidate bypassed the existing guarded navigation helper: Reddit
returned a 516-character challenge. The reference also returned no substantive
Reddit posts in that attempt (72 characters of Markdown). The candidate also
called blank Booking Markdown successful. Both defects were fixed before the
reported final fixture/resource measurements: reuse existing guarded navigation
and classify blank extraction as failure.

After the fix, Reddit's recovery recipe settled successfully and the candidate
returned **17,738 characters** of subreddit content with post/comment links in
**about 4.4 seconds**, including its configured settle. The exact retained timing
is in `live_retests` in summary.json. This is a single successful observation,
not a repeated like-for-like victory over the reference. Booking remained empty
and now reported `empty_extracted_content`. No new Cloudflare/PerimeterX bypass
claim follows from the readable Crunchbase landing page or this pilot.

## CPU investigation and next step

A separate inside-container browser diagnostic held navigation, capture and
0.5-second settle constant, varying only fresh contexts versus reuse within one
fixture owner's context. Two ten-read rounds per mode:

| Context policy | Median CPU-seconds / ten | Approximate elapsed time / ten |
|---|---:|---:|
| Fresh isolated context per read | 6.67 | 6.42 s |
| Same owner's context reused | 1.89 | 5.39 s |

This strongly implicates context lifecycle in the extra CPU cost. This diagnostic
started its own temporary browser and is not part of the runtime memory table.
Its numbers establish an opportunity, not a shipped optimization. The reference
Crawl4AI pool reuses contexts; the current candidate isolates every render.
**Do not recover the CPU saving through global cookie/context sharing.** The next
implementation to evaluate is bounded reuse within a verified caller/session,
with isolated anonymous requests, eviction, cleanup and cross-caller regressions.

## Remaining replacement gates

- Native ARM64 build and runtime; tested transitive lock for supported platforms.
- Repeated live coverage with predefined task facts, not text length alone.
- Full API/MCP/evidence and non-browser document regression gates.
- Realistic mixed discovery/render/drive load and browser-crash failure containment.
- Cancellation, hostile HTML and extraction resource limits. The prototype's
  eight-MiB render HTML ceiling is an explicit compatibility limit; it must be
  reconciled with current acquisition limits before replacing the renderer.
- Real-list filtering/resource tests, browser identity comparison and worker policy
  propagation. The shared browser broadens a crash's impact across all three uses.
- Careful comparison of final post-wait access state; no claim of verified answer
  completeness from the worker's access assessment.

The prototype is viable and measurably smaller. It is not yet an approved,
across-the-board faster replacement. Keep 1.7.1 as the working reference while
closing these gates. See the [lab guide](../../README.md) and
[source hashes](source-sha256.json) to reproduce the experiment.
