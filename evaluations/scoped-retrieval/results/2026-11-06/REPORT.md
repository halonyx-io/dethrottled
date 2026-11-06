# Scoped retrieval candidate — 6 November 2026

Base: published 1.6.2. These are uncommitted candidate changes, not a released or
deployed version. No discovery ranking, default menu ceilings, dependencies,
services, model weights or cache lifetimes were changed.

## Controlled results

The same dependency image and frozen 25,595-byte HTML/one-page SearXNG response
were used for baseline and candidate. Runs were sequential, seven samples per
operation, on the same x86_64 host. These fixtures do not establish live upstream
relevance, bot resistance or cross-device speed. Raw observations are retained in
[baseline.json](baseline.json) and [candidate.json](candidate.json).

| Task | Baseline | Candidate | Interpretation |
|---|---|---|---|
| Matching NASA URLs after three-slot Yahoo cap | 0 | 3 | Wrong-host rows previously consumed slots before final validation. Same response; one request, page one, each. |
| Crawl evidence reads / HTTP requests | 13 / 13 | 13 / 13 | Existing crawl is preserved. Candidate median 746 ms versus baseline 737 ms; no speed gain claimed. |
| Map thirteen URL candidates | Unsupported | 1 discovery acquisition, 0 evidence reads | Seed is read; twelve linked candidates are listed without fetching them. No retained evidence or indexing. |
| Map latency | Unsupported | Median 59.4 ms; p95 61.5 ms | Seven local samples. Map is not equivalent to reading thirteen pages. |
| Plain fetch latency | Median 54.8 ms | Median 54.7 ms | No meaningful change established by this small fixture. |
| Fetch plus two selector fields | Unsupported | Median 55.6 ms; p95 56.7 ms | Same one HTTP request. Both known fields recovered in all seven runs; plain 800-character excerpts contained neither. |
| Invalid URL / explicit public-target refusal browser calls | 1 each | 0 each | Terminal refusal is retained rather than invoking another browser read. |
| Generic connection failure recovery | 1 browser call | 1 browser call | No blanket two-second cutoff; alternate transport/resolver recovery retained. |

Selector operation median overhead versus candidate plain fetch was about 1 ms
in this fixture. Maximum Python-traced allocation peak was 1,435,607 bytes with
selectors versus 1,434,621 without. This is **not** process RSS: native DOM/parser
allocations are not fully represented, and the fixture cannot establish a universal
memory ceiling. CSS parsing is opt-in per request, bounded by existing HTML input
limits; output values have a separate 64,000-character ceiling. No background
worker/model was added. CPU samples and individual timings are in the raw files.

## Contracts and regressions

- Explicit includes/excludes are hostname/subdomain constraints, not preferences.
  They intersect existing positive site operators; exclusions win. They propagate
  through search, search-and-fetch, research, source menus and corpus additions.
  Host validation precedes acquisition/menu caps, with original provider ranks
  preserved where supplied. No extra pagination is used. A valid SERP whose rows
  all fail constraints is a constrained empty response, not a transport failure
  warranting more DDG alternatives.
- Persisted fetch jobs omit empty selector defaults from request fingerprints,
  preserving operation-id retries created before this feature. Nonempty selector
  specifications remain part of the fingerprint and survive job payloads/resume.
- CSS fields use acquired HTML independently of clipped prose, including adopted
  browser-recovery DOMs. Scalar/list values, attributes, optional/required fields,
  invalid selectors, absent HTML, bounded values, HTML clipping and provenance
  are tested. Missing fields preserve prose quality. Invalid specifications are
  request errors, not invented semantic inference.
- Map reads supplied HTML seeds, sitemap URL sets and bounded nested indexes.
  Scope, redirects, request/URL/depth limits, failures, truncation and pending
  indexes remain visible. It does not guess robots/sitemap URLs or recurse through
  every linked HTML page. Existing default crawling is unchanged.
- Explicit network-policy errors during HTTP/TLS redirects preserve their reason
  and stop the ladder; guidance offers no bypass retry. Malformed URL/public-policy
  failures also skip read-plan browser recovery. Generic DNS, connect and TLS
  failures are not reclassified as permanent from an exception class or short timer.
- Actual Chromium fixture checks cover multi-include/exclude hosts before caps,
  constrained empty success, one-page acquisition, sparse results, ten-primary and
  three-supplement caps, real HTTP 429/Retry-After, cancellation and failure-history
  redaction. Actual MCP checks cover forwarding new controls, existing auth/scopes,
  backend identity checks, native images and existing limits.

## Original failures and remaining limits

The first test invocation lacked pytest in the runtime image; host Python lacked
httpx. Disposable test-only dependencies were then mounted without modifying the
runtime image or production. A no-isolation wheel build also lacked setuptools
in its development environment; the standard isolated build installs the declared
build prerequisite instead of changing runtime dependencies. The first focused run had two failures because its
mock ignored max_chars; fixing the mock restored the real fetch contract. Its
original failures are retained in [initial-focused.txt](initial-focused.txt)
with terminal trailing whitespace trimmed.
The first browser verifier launch stalled in xvfb-run before Python started;
a bounded disposable retry used the image's direct Xvfb approach and passed.

Native ARM64 execution was attempted but SSH authentication was unavailable. No
ARM64 result is claimed for this candidate; no native dependencies were added.
Full release CI remains a later gate. No production services were changed.

There is no proof of improved general search accuracy from this constrained
fixture, no universal minimum-resource claim and no claim that all dead hosts
now finish quickly. Mapping still reuses the existing acquisition/parser ladder
for discovery reads, and selector specifications must be supplied by the caller.
Publication/deployment is separate from these implementation checks.

## Final validation

The final non-network suite passed **957 tests**, with 15 optional skips and two
network tests excluded (68.46 seconds). Chromium and actual MCP/REST transport
checks passed. Documentation checks covered 24 routes, 20 MCP tools, 27 browser
actions, 85 Markdown pages, 611 links and 56 examples, including ten validated
local request bodies. Ruff, whitespace checks and skill validation passed.

A local QA wheel was built and installed outside the checkout, borrowing the
existing runtime image dependencies. Domain normalization, selector fields, map
schema and the bundled SKILL.md worked from the installed package; the deployment
context matched the changed runtime/skill files. This wheel retains the base
1.6.2 label for local checks only and must not be published over the existing
release. Final hashes, gate results and package identity are in
[validation.json](validation.json). Native ARM64 CI remains outstanding.

## 1.7.0 release preflight

The initial validation above captures the pre-version-bump implementation. Release
preparation subsequently set version 1.7.0 and built the actual API, browser and
adapter images. It caught and fixed a packaging omission: Docker COPY and the
.dockerignore allowlist both needed SKILL.md. The wheel context verifier now guards
that requirement. The self-contained image/dependency/model check passed offline.
The complete suite against installed 1.7.0 passed 957 tests (15 optional skips,
two network exclusions; 69.92 seconds).

A fresh, isolated software-rendered default Compose stack with actual MCP/REST
adapters passed the integrated [recorded checks](integrated-1.7.0.json): nested
sitemaps returned three candidates from two discovery reads; a JavaScript-created
heading, button effect and screenshot were observed; MCP selectors, mapping and
fetch-job fields survived every hop; auth and public-target boundaries held.
The bounded live search returned three docs.python.org sources with outcome=results.
This is one live query, not a general relevance benchmark.

Original setup failures remain in private release logs: rendered Compose JSON
omitted zero ulimit values (the disposable harness now restores them), a test-only
mount initially lacked adjacent fixture scripts, and a public example-page check
assumed an h1 that the publisher had removed. Inspecting the returned source proved
HTML preservation and missing-field reporting were correct; the public assertion
now uses its existing title element. No extractor fix was needed for that case.
The controlled JavaScript fixture tests h1 without relying on publisher markup.

Native ARM64 checks are provided by the release candidate's GitHub CI. Final CI,
publication hashes and deployment verification are recorded with release artifacts;
this earlier local snapshot does not claim those later gates passed.

The first candidate CI passed native ARM64 Python 3.10–3.13 but exposed a test
prerequisite mistake on the core-only Windows/macOS installations: three TLS
regressions assumed optional curl_cffi was present. Those checks now explicitly
require that extra. The HTTP redirect-policy test is independent and still runs
without TLS; the split adds one test to full installations. This correction does
not add a runtime dependency or change missing-TLS fallback behaviour. Original
CI failures are retained in the workflow history; all release gates are rerun on
the corrected candidate before merge.
