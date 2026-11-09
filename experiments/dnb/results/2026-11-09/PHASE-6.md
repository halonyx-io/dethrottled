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

## Optional-worker parity

The candidate API and reference 1.7.1 ran side by side on the production Docker
network with the existing `format-worker`, `media-worker` and `docling-worker`.
A local files container served generated PDF, DOCX, XLSX, PPTX and PNG files.

| File | Reference | Candidate | Fact |
|---|---|---|---|
| office.pdf | ok / 27 chars | ok / 27 chars | golf-904 |
| office.docx | ok / 33 chars | ok / 33 chars | delta-901 |
| office.xlsx | ok / 31 chars | ok / 31 chars | echo-902 |
| office.pptx | ok / 32 chars | ok / 32 chars | foxtrot-903 |
| office.png | ok / OCR warning | ok / OCR warning | hote-005 (both; OCR misread hotel-905) |
| table.pdf | 3,843 B | 3,622 B | candidate concise-table behavior |

Office facts, tier and quality match. The PNG OCR output is identical on both
sides but misreads the intended fact; the OCR warning is retained, so this is not
an OCR accuracy claim. Media playback and a layout-worker-specific document are
still to exercise.

Evidence: [phase6-optional-summary.json](phase6-optional-summary.json).

## Layout and mixed-batch parity

Both cores used the existing docling layout worker and served the same generated
files. `table.pdf` with `document_mode=layout` returned `parser=docling`, 158
characters and the same two inference warnings on both sides. A mixed four-file
batch (PDF, DOCX, XLSX, PPTX) returned the same quality, tier and character
counts on both sides.

Evidence: [phase6-layout-mixed.json](phase6-layout-mixed.json).

## ARM64

Built the reference browser and candidate on `q6a` (`aarch64`, Docker 29.9.3):

- reference `dethrottled-dnb-browser:reference`
  `sha256:b9e0fe2a…`
- candidate `dethrottled-dnb:1.8.0-candidate-arm64`
  `sha256:9fb7c41b…`

The candidate starts and serves `/health` with software `llvmpipe`
(`hardware_verified=false`, WebGL pixel correct) and a real `/crawl` retained
`cobalt-731`. The focused phase-1/2 tests pass **29/29** on ARM64.

Evidence: [phase6-arm64-summary.json](phase6-arm64-summary.json),
[phase6-arm64-health.json](phase6-arm64-health.json),
[phase6-arm64-tests.log](phase6-arm64-tests.log).

## HTML ceiling

A 13.7 MB HTML file exceeded the existing 8 MiB capture limit. Both reference
and candidate returned HTTP 200 with the same `html_capture_limit` warning,
300 content characters, and did not include the fact placed after the ceiling.
The warning is retained rather than presenting a truncated page as complete. This
confirms the candidate preserves the existing acquisition limit; it does not
silently widen it.

Evidence: [phase6-html-ceiling.json](phase6-html-ceiling.json).

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
