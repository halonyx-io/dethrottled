# Evidence and known limits

Use this page to assess what has actually been measured. Current guides describe
present behavior; the reports below retain their recorded versions, protocols
and failures. Neither a health check nor a passing fixture establishes universal
web access, answer correctness or superiority over paid services.

Current source-menu policy follows the [expanded ranking evaluation](../evaluations/search-policy/results/2026-11-03/REPORT.md):
ten DDG choices, Yahoo/Yandex supplements of at most three each and fifteen unique
choices total. Research has a separate 24-candidate/20-source ceiling. Earlier
larger-pool measurements remain historical evidence.

## Recorded evaluations

| Scope | Report and raw data | Interpretation |
|---|---|---|
| Public Corpus v2 and retrieval support | [Controlled comparison](../evaluations/corpus-v2/results/2026-11-05/REPORT.md), [reproduction](../evaluations/corpus-v2/README.md) | Deep facts, multilingual/model ablation, standard versus broad retrieval and native package/lifecycle gates; preserves false positives and misses |
| Complete installation and two-device performance | [1.4.0 validation](../evaluations/install-showcase/results/2026-11-04/REPORT.md), [reproduction](../evaluations/install-showcase/README.md) | PyPI-managed workers, native software rendering, retained controlled facts and live outcomes; original failures preserved |
| Expanded ranking and default policy | [400-query experiment](../evaluations/search-policy/results/2026-11-03/REPORT.md) | 299 usable train/100 fresh test, two model judges; modest XGBoost improvement, no demonstrated fresh-read gain; compact supplements retained, learned ranking not deployed |
| Agent source choices | [120-question study](../evaluations/agent-search/results/2026-11-03/REPORT.md) | Frozen 80/40 split, source/RRF menu replay, blinded model judgements, 283 fetched URLs, live pacing/bursts and preserved refusals; supports source order on this host, not general paid-provider superiority |
| Automatic discovery breadth | [Whole-path correction](../evaluations/search-breadth/results/2026-11-02/REPORT.md) | Records the failed public check and the staged MCP → API → TLS/browser recovery before promotion |
| Browser discovery depth | [Broad-search follow-up](../evaluations/broad-search/results/2026-11-02/REPORT.md) | Requested count reaches the worker; bounded same-origin pagination and pooled results; native and live observations |
| Dependency audit and coverage ceilings | [1.1.0 assessment](../evaluations/audit/results/2026-11-02/REPORT.md) | Full dependency locks, vulnerability observations, higher request capacities, compact MCP values and backend identity checks |
| MCP maintenance | [1.0.1 transport checks](../evaluations/mcp-maintenance/2026-11-02/REPORT.md) | SDK upgrade, release identity, strict arguments and access contracts; no source-coverage claim |
| 1.0 release gates | [Evaluation](../evaluations/release/results/2026-11-02/REPORT.md), [method](../evaluations/release/README.md) | Default-stack, fidelity, browser and remote-agent evidence; native CI results and release verification are recorded in the report |
| Native browser navigation recovery | [0.10.1 comparison](../evaluations/drive-recovery/results/2026-11-02/REPORT.md), [method](../evaluations/drive-recovery/README.md) | Reddit listing/thread recovered with native controls; no additional Crunchbase/G2 reads; single-host observations |
| Autonomous read loop and GPU | [0.10.0 comparison](../evaluations/read-loop/results/2026-11-02/REPORT.md), [method](../evaluations/read-loop/README.md) | Five controlled recoveries 0/5 to 5/5; scoped drive handoff; AMD and software pixel checks; no new hostile-source win; Booking assertion coverage lower |
| Mixed content and task evidence | [0.9.2 comparison](../evaluations/content-validity/results/2026-11-01/REPORT.md), [method](../evaluations/content-validity/README.md) | 6/8 labelled long-banner cases surfaced versus 0/8; all 18 fixture facts retained; 32 live observations, no new hostile-source win |
| Current recovery and software graphics | [0.9.0 to 0.9.1](RECOVERY-GAPS.md), [raw bundle](benchmarks/2026-11-01-recovery-next/README.md) | Headed contention 1/6 to 6/6; two JS fixtures 0/2 to 2/2 under defaults; real WebGL pixel test; four hostile sources still unreadable |
| Bot findings and challenge wiring | [0.9 review](REVIEWED-BOT-FINDINGS.md), [raw bundle](benchmarks/2026-11-01-findings/README.md) | Controlled clearance 0/4 to 4/4; strict MCP inputs; no new hostile-source success |
| Workers, corpus and formats | [0.8 measured changes](MEASURED-IMPROVEMENTS.md), [raw bundle](benchmarks/2026-11-01-measured/README.md) | Controlled admission, MSG/XLSB, scanned tables, worker supervision and dual corpus; bounded fixture quality |
| Source/format/browser coverage | [0.6 to 0.7](../evaluations/dependable/results/2026-11-01/REPORT.md), [method](../evaluations/dependable/README.md) | 99/110 to 109/110 mechanical checks; not 110 independent research questions |
| Agent behavior | [Cold-agent method](../evaluations/agent-workflow/README.md), [confirmation](../evaluations/agent-workflow/results/2026-11-01/RESULTS.md), [six-upgrade results](../evaluations/agent-workflow/results/2026-11-01-six-upgrades/RESULTS.md) | Model-, task- and client-specific; includes pilot tuning and failures |
| Installed worker audit | [Audit](../evaluations/worker-audit/2026-11-01/REPORT.md) | Snapshot before later changes; upgrade proposals are not current deployed facts |
| Host performance | [4 October comparison](BENCHMARKS-2026-10-04.md), [raw JSON directory](benchmarks/2026-10-04/) | Historical x86_64/ARM64 comparison, not current latency or coverage guarantees |

The 0.9.1 regression snapshot reports 578 passed, 15 skipped and two network tests
deselected. Public MCP/REST and actual SDK checks are recorded separately. Search
samples returned 10/9/10 results on both tested workers; that is not exhaustive
ranking equivalence. Live tests are observational and subject to upstream changes.

## Limits that remain

- CarGurus, Crunchbase/OpenAI, G2/Notion and Expedia did not become readable in
  the recorded recovery sweep. Persistent Chromium/Chrome profiles did not
  change that outcome. WebGL availability is not an anti-bot bypass score.
- Automatic recovery waits and executes browser JavaScript; it is not a general
  interactive CAPTCHA solver. Browser navigation/response failures remain real.
- OCR, layout and ASR can be wrong. Source pixels, ranges and warnings matter;
  reading a short table is not proof of reconstructing an entire workbook.
- Site traversal sees bounded observed links, not every page. Retention and
  input/page/row/cell limits constrain evidence coverage.
- Public admission leases can temporarily survive adapter crashes/restarts.
  Request retry hints do not imply immediate slot reclamation.
- No general paid-provider quality comparison or defensible aggregate CreepJS
  score has been established by these runs. Default workflows remain keyless.

For a new claim, freeze exact URLs/tasks and expected facts before running, record
version/configuration, distinguish cache hits and acquisition, retain negative
results, and check semantic support separately from term matches. Keep credentials,
login state and full identifying fingerprint data outside publication.

[Documentation home](README.md) · [Agent guide](AGENT-UPGRADES.md) · [API](API.md) · [Evidence](EVIDENCE.md)


## Retrieval reliability candidate

The [2026-11-05 investigation](../evaluations/retrieval-reliability/REPORT.md)
compares discovery readiness/degradation, long-HTML extraction and correlated-DDG
refusals. It retains before/after fixtures and native x86_64/ARM64 measurements;
the dated captures precede the authorized 1.5.2 rollout. They are not new ranking
or universal performance claims.

## Domain-filter evaluation

[HaGeZi filtering controls and resource measurements](../evaluations/adblock/README.md)
retain original failed approaches, local network/evidence controls, native
architecture checks and a small live comparison. They do not claim universal
challenge recovery or zero false positives.

## 1.6.1 retrieval and client-contract evidence

The [1.6.1 candidate investigation](../evaluations/retrieval-review/results/2026-11-06/REPORT.md)
retains the RFC 9110 three-fact comparison, PDF/OCR continuation regressions,
corpus diagnostic cases and performance limitations. The dated reports preserve their original local candidate observations. Final
CI/package/deployment checks are attached to the
[1.6.1 release](https://github.com/halonyx-io/dethrottled/releases/tag/v1.6.1).

The [post-1.6.0 follow-up](../evaluations/post160-review/results/2026-11-06/REPORT.md)
adds unchanged-refresh CPU measurements, real socket transfers during rule
changes, MCP admission framing and crawl/job contract checks. It includes the
cumulative change summary and the gates outstanding at the time of that experiment.
