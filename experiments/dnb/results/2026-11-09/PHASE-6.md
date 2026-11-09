# Phase 6 progress

2026-11-09. Phase 6 is in progress; production remains 1.7.1 and the local
Compose container was not modified.

## Frozen candidate

- Source commit `735d420`, tag `phase5-candidate-20261109`.
- Candidate worker image `dethrottled-dnb:1.8.0-candidate-20261109`
  (`sha256:c6633da3…`).
- Candidate API image `dethrottled-dnb-api:1.8.0-candidate-20261109`
  (`sha256:bb859007…`), built from `experiments/dnb/Dockerfile.api` over
  `dethrottled:1.7.1` with the frozen `src/`.
- Reference browser image `dethrottled-dnb-browser:reference`
  (`sha256:c1726a32…`).

## Completed smoke checks

### Browser parity (prep)
`compare.py`/`verify.py` against reference and candidate: both passed 27 facts,
all 27 drive actions, exact download, network fact, concurrency and checkpoint
restore. The 9 raw `compare` failures are 3 reference `/tiny` thin-content flags
and 6 expected `/missing` 404s.

### Candidate API smoke
The candidate API image started, `/health` returned 200, and a local PDF
`/fetch` succeeded through `direct/direct-native` with quality `ok` and 213
content characters.

### PDF concise parity
Same PDF, same `max_chars=300`:

| Side | Response bytes | Native tables | Table count |
|---|---:|---:|---:|
| reference 1.7.1 | 3,847 | 1 | absent |
| candidate 1.8.0 | 3,373 | 0 | 1 |

The content and tier match; the candidate's smaller response is the intentional
Phase 4 concise-table behavior. This is a deliberate presentation difference, not
a capability loss.

Evidence: [phase6-pdf-summary.json](phase6-pdf-summary.json),
[phase6-pdf-reference.json](phase6-pdf-reference.json),
[phase6-pdf-candidate.json](phase6-pdf-candidate.json).

## Remaining Phase 6 work

1. PDF/OCR/Office/media/layout coverage and mixed batches, including the 8 MiB
   HTML ceiling reconciliation.
2. Optional-worker integration through the candidate API image.
3. Paced live/hostile-source parity with predefined facts.
4. ARM64 build/parity/resource run on `q6a`.
5. PyPI/GitHub installation route outside the source checkout.
6. Mixed-load, long-running memory and crash containment.
7. Rollback/volume preservation and release artifact verification.
8. Version/package 1.8.0 and release only after approval.

## Resource note

The prep resource smoke showed the candidate at ~6.8–7.2 CPU-seconds per 10
renders versus ~2.4–2.8 for the reference, with similar latency. This is
consistent with the consolidated extraction workers; old pilot CPU figures do not
apply.
