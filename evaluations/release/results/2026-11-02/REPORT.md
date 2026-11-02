# 1.0 candidate evaluation — 2 November 2026

The local measurements below used **1.0.0rc1**, compared with the 0.10.1
baseline. The candidate was subsequently pushed for native CI and prepared as
1.0.0 with version, packaging and documentation changes. Publishing a release
does not update the public deployment. Release verification is recorded below.

## Outcomes and limits

| Gate | Observed result | What remains |
|---|---|---|
| Autonomous acquisition | 20/20 fresh default-stack contracts and 1/1 restart contract pass | Broader sources and real agent populations are not covered by synthetic fixtures |
| Browser/blocker recovery | Three fresh Reddit thread sessions per CPU/GPU configuration returned the predefined fact and exercised native controls; listing reads also passed | Crunchbase/G2 remained 403; CarGurus yielded no usable text; no general hostile-source breakthrough is claimed |
| Content fidelity | 22/22 parser tasks pass; known pollution detections improve 6/8 → 8/8, false flags remain 0/10 and facts 18/18 | This is a known regression set, not an independent accuracy sample |
| Portable defaults | Normal Dockerfiles build; fresh volumes and an empty environment file pass without GPU or host model mounts | Native AMD64/ARM64 execution subsequently passes in CI; Windows/macOS Docker Desktop behavior remains untested |
| Optional resources | Started profile workers are discovered automatically; speech and PDF layout conversions return supported evidence | Initial model downloads and resource requirements still apply |
| Agent contract | Actual authenticated REST/MCP checks pass; corrected fresh-agent task completes through published tools | One model conversation is not a general agent reliability estimate |
| Runtime/docs | 648 unit/contract tests pass; offline verifier validates 71 package versions, reader dependencies and actual MiniLM/E5 inference | Native CI results are recorded below; final release metadata is checked separately |

The [source hashes](source-sha256.json) identify the implementation inputs tested.
Full controlled results and summarized live observations accompany this report.
No bearer values, browser storage or full third-party page bodies are included.

## Hands-off defaults

Base Compose now includes the MSG/XLSB worker. It also defines speech/layout
profiles directly, so `docker compose --profile full up -d --build` is sufficient
for both. The API discovers fixed service names through Compose DNS; a separately
configured worker URL and API restart are unnecessary. Missing names are cached
for ten seconds. Custom URLs take precedence, and `off` disables an individual
reader. Source installations do not probe for services unless explicitly enabled.

The [paired format probe](formats-candidate.json) retains the expected text from
both Apache POI files; [0.10.1 without endpoint configuration](formats-baseline.json)
cannot use that worker. The same actual files pass through HTTP in the default
stack's contracts. Source URLs, byte hashes, expected text, license and notice
are retained with the fixtures. This establishes additional default coverage for
two formats, not full email attachment or spreadsheet-cell completeness.

The format service used about 34–37 MiB while idle on this host; its conversion
cap is 2 GiB. Speech and layout stay optional because model downloads and memory
requirements are materially larger. An unready model worker now identifies
`initialization=first_use_download`; using it triggers the download without a key.
The [speech observation](speech-profile.json) retains the known audio phrase and
speech uncertainty warnings. Initial cold acquisition/transcription took about
25.7 seconds; a later cached-model observation took 6.8 seconds. These are single
runs in different cache/load conditions, not a speedup estimate.

## Autonomous and native browser operation

The [normal-image contracts](normal-contracts.json) start the actual default stack
with no `.env`, inherited deployment settings, GPU devices or old data volumes.
They acquire predefined facts through a publisher representation, scroll-loaded
page, expandable details, primary application JSON and visitor state. They also
check a same-browser handoff, later physical table rows, retained-source reparsing,
frame actions, popup reading, parsed downloads and checkpoints.

Negative cases preserve the absence of evidence: an unrelated JSON document is
not substituted, explicit render/manual policies remain effective, and a new
caller does not inherit the prior visitor's cookie. After the worker restarts,
the [restore contract](normal-restore.json) verifies cookies, localStorage,
sessionStorage and IndexedDB. Project names and volumes are unique to each run;
cleanup removes only the disposable project.

Checkpoint capture previously failed if navigation detached an inspected frame.
It now captures each frame's origin/storage together and retries only read-only
snapshot work, at most three times. It does not repeat the action that triggered
navigation or accept arbitrary capture errors as transient. Unit checks also
verify that permission errors are not retried.

## Live coverage and latency

[Live protocol](live-protocol.json) and [observations](live.json) keep the fixed
sources, individual timings, negative outcomes and body hashes. Software and GPU
used the same browser implementation and navigation recovery, with fresh sessions.
For the Reddit thread, three runs per configuration retained the ParticleDB and
`WHERE 4 = 5` assertions and opened the native comment-sort menu. Operation retries
were replayed without another click. Median navigation/read times in this small
sample were 1,933.61 ms on software and 1,755.11 ms with GPU; median menu clicks
were 219.52 and 225.74 ms respectively. This does not establish a meaningful GPU
performance or blocker-recovery advantage.

A separate [normal Dockerfile software-browser smoke](normal-browser-live.json)
also retained the thread fact and opened the menu, after the OS/browser image was
rebuilt rather than layered over the production image. Its navigation/read took
2,205.19 ms. Actual software WebGL was reported; no physical GPU was mapped.

Crunchbase and G2 returned 403 on both configurations. CarGurus produced no usable
text and an unknown access assessment. Bloomberg's homepage returned text with
the predefined navigation terms on both; these broad homepage assertions do not
verify article access, paywall removal or an additional win against a fixed
blocked baseline. No such claim is made. Complete-source and answer verification
remain false even when text is observed.

## Renderer update

Crawl4AI **0.9.5** replaces 0.9.4 in the candidate, pinned to a multi-architecture
image digest. Its upstream index advertises AMD64 and ARM64; that is manifest
evidence, not ARM execution evidence. The upstream config is refreshed with the
same three capacity tunings and its browser-context recycling default retained.
The independent offline HTML-to-PDF utility remains on its tested 0.9.4 image; it
does not run the renderer HTTP server.

The [paired renderer protocol/results](renderer-comparison.json) use controlled
sources. A quoted CSS selector returned one whitespace character under 0.9.4;
0.9.5 retained the expected allocation fact in 1,471 characters. Basic JavaScript
and quoted-selector waits retained the same fact on both versions. An untrusted
JavaScript wait was accepted by the old server and rejected with 400 by 0.9.5.
This agrees with the upstream [security and compatibility release notes](https://github.com/unclecode/crawl4ai/blob/main/CHANGELOG.md).

Both servers still wrap a target 404 in a transport-200 response with `success=true`.
Dethrottled's [actual client checks](renderer-client.json) reject that target as
`crawl4ai_target_http_404` on both. Reading quality is assessed independently from
upstream transport status. All six client checks pass. The final fresh default
Compose suite uses 0.9.5 and also passes.

## Fidelity and model-result adoption

The [pollution comparison](pollution.json) improves the two known missed retry
banners while retaining exact spans/provenance and useful material. The patterns
remain bounded and quote/code/structured-aware. No text is removed merely for
containing an error phrase. The fixture labels informed the change, so the 8/8
result must be described as regression coverage.

A forced layout conversion initially returned useful model text but was rejected.
The length guard compared against native text plus an appended duplicate native
table, inflating the baseline. It now compares length against original native
text. Number retention and detected-table count checks remain. The [final layout
observation](layout-profile.json) adopts Docling, retains the expected value and
source hash, and exposes inferred table provenance. Tests still reject a candidate
that loses the key number. Native parsing remains available when conversion fails.
The initial model/rejection record is retained as [cold-original evidence](layout-cold-original.json).

## Remote agents and the cold test

The first fresh-agent task exposed an actual schema mismatch: instructions
advertised `scroll`, `read_state` and `expand_details`, but MCP's action enum did
not accept them. The candidate exposes all three, and a parity test compares the
published enum with the browser's implemented actions. The initial task also
incorrectly described the SQL predicate as a joke. Its [failed pilot summary](cold-agent-pilot.json)
is preserved; the corrected task asks about the anomaly list. These are different
tasks/configurations, not a controlled model before/after success-rate comparison.

The [final conversation](cold-agent-final.json) started without hidden endpoint
hints, using only MCP initialization instructions and tool schemas. It returned
the predicate and sort choices, and its trace contains successful native clicks,
scrolls and details actions. It used ten tool calls in about 62.4 seconds, with
no MCP tool-validation errors. The test used an already configured Ollama cloud
model subscription; Dethrottled itself still requires no model service or key.
Only reviewed summaries and result hashes are included here; full local transcripts
are retained outside the repository without provider reasoning or credentials.

The [actual SDK/REST probe](remote.json) confirms 20 tools, matching instruction
hashes, native clicking and operation replay, shared caller-scoped browser state,
retained-document reads, other-caller rejection and private-target rejection. It
uses disposable local adapters and credentials; it does not claim that the public
production endpoint runs this candidate or that a remote plugin has reloaded code.

## Failed pilots and reproducibility

Failures are retained rather than counted as wins. Besides the schema/task and
layout findings above, the initial new harness used incorrect capability paths,
read-document paths and download response assumptions. A restart-time profile
probe ran before the API was ready and reset its connection. A renderer-client
probe set a credential after import and got 401; its missing-page assertion was
corrected to require the exact target-404 reason. Remote probes initially reused
an old operation ID, and then assumed a caller with its own warmed session had
no session. Fresh test handles and operation IDs remove those assumptions.
These test defects do not establish product regressions or extra source recovery.

The normal Docker build uses [tested package pins](../../../../requirements/docker-py312.txt),
with application installation after dependency/model layers. The [offline check](offline-runtime.log)
validates all 71 pins, native readers, OCR tools and actual MiniLM/E5 embeddings
with networking disabled. This freezes runtime package versions, not every OS
package or image byte. [ARM wheel preflight](arm-wheel-manifest.json) found all nine
selected native-package wheels; it does not replace native execution.

[Regression log](regression-final.log): **648 passed, 15 skipped, two network tests
deselected**. Lint and documentation contracts pass.

## Native CI and release verification

[Candidate CI](https://github.com/halonyx-io/dethrottled/actions/runs/41413525014)
passes all 14 checks at commit `44e4d1ac64c98d833d1fe8922f333d1ce304a741`.
Both native AMD64 and ARM64 build the normal API/browser images, run the offline
runtime and packaged-document checks, start headed Chromium, and pass **20/20
fresh-stack contracts plus 1/1 restart restoration**. The stack uses fresh volumes,
an empty environment file and software rendering. [Summary](ci-candidate.json),
[AMD64 contracts](ci-amd64/contracts.json), [AMD64 restore](ci-amd64/restore.json),
[ARM64 contracts](ci-arm64/contracts.json) and [ARM64 restore](ci-arm64/restore.json)
are preserved. This is actual native execution, beyond the earlier wheel preflight.

Release preparation changes the version to **1.0.0**, updates the current guides,
adds canonical PyPI project links and a release tag/package-version check. The
wheel and source archive both build, pass `twine check`, and install/import in
separate clean environments outside the source tree. The installed base wheel
starts its HTTP server and reports 1.0.0 from health and capabilities. These checks
do not assert that a Python install includes Docker workers or system OCR tools.
The exact release commit must also pass all CI checks before tagging.

The public deployment remains independently versioned; no production runtime
upgrade is part of these publication checks. Public adapter code and remote
plugin captures must be verified separately when that installation is upgraded.
