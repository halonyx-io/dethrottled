# Evidence and known limits

Use this page to assess what has actually been measured. Current guides describe
present behavior; the reports below retain their recorded versions, protocols
and failures. Neither a health check nor a passing fixture establishes universal
web access, answer correctness or superiority over paid services.

## Recorded evaluations

| Scope | Report and raw data | Interpretation |
|---|---|---|
| Unpublished 1.0 candidate | [Candidate gates](../evaluations/release/results/2026-11-02/REPORT.md), [method](../evaluations/release/README.md) | Local default-stack, fidelity, browser and remote-agent evidence; native candidate ARM64 CI/promotion remain pending |
| Native browser navigation recovery | [0.10.1 comparison](../evaluations/drive-recovery/results/2026-11-02/REPORT.md), [method](../evaluations/drive-recovery/README.md) | Reddit listing/thread recovered with native controls; no additional Crunchbase/G2 reads; single-host observations |
| Autonomous read loop and GPU | [0.10.0 comparison](../evaluations/read-loop/results/2026-11-02/REPORT.md), [method](../evaluations/read-loop/README.md) | Five controlled recoveries 0/5 to 5/5; scoped drive handoff; AMD and software pixel checks; no new hostile-source win; Booking assertion coverage lower |
| Mixed content and task evidence | [0.9.2 comparison](../evaluations/content-validity/results/2026-11-01/REPORT.md), [method](../evaluations/content-validity/README.md) | 6/8 labelled long-banner cases surfaced versus 0/8; all 18 fixture facts retained; 32 live observations, no new hostile-source win |
| Current recovery and software graphics | [0.9.0 to 0.9.1](RECOVERY-GAPS.md), [raw bundle](benchmarks/2026-11-01-recovery-next/README.md) | Headed contention 1/6 to 6/6; two JS fixtures 0/2 to 2/2 under defaults; real WebGL pixel test; four hostile sources still unreadable |
| Bot findings and challenge wiring | [0.9 review](REVIEWED-BOT-FINDINGS.md), [raw bundle](benchmarks/2026-11-01-findings/README.md) | Controlled clearance 0/4 to 4/4; strict MCP inputs; no new hostile-source success |
| Workers, corpus and formats | [0.8 measured changes](MEASURED-IMPROVEMENTS.md), [raw bundle](benchmarks/2026-11-01-measured/README.md) | Controlled admission, MSG/XLSB, scanned tables, worker supervision and dual corpus; bounded fixture quality |
| Source/format/browser coverage | [0.6 to 0.7](../evaluations/dependable/results/2026-11-01/REPORT.md), [method](../evaluations/dependable/README.md) | 99/110 to 109/110 mechanical checks; not 110 independent research questions |
| Agent behavior | [Cold-agent method](../evaluations/agent-workflow/README.md), [confirmation](../evaluations/agent-workflow/results/2026-11-01/RESULTS.md), [six-upgrade results](../evaluations/agent-workflow/results/2026-11-01-six-upgrades/RESULTS.md) | Model-, task- and client-specific; includes pilot tuning and failures |
| Installed worker audit | [Audit](../evaluations/worker-audit/2026-11-01/REPORT.md) | Snapshot before later changes; upgrade proposals are not current deployed facts |
| Host performance | [4 October comparison](BENCHMARKS.md), [raw JSON directory](benchmarks/2026-10-04/) | Historical x86_64/ARM64 comparison, not current latency or coverage guarantees |

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
