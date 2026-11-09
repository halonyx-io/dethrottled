# Candidate test-bed changes

Running log of changes made to the held 1.8.0 candidate after the Phase 6 freeze.
The frozen baseline remains `735d420` / `phase5-candidate-20261109`; these are
test-bed improvements, not a released version.

| Date | Change | Evidence | Status |
|---|---|---|---|
| 2026-11-09 | Regenerated stale HTTP/MCP references and fixed five broken Phase 6 prep links | [S0-S1-PROVENANCE-CONTRACTS.md](S0-S1-PROVENANCE-CONTRACTS.md) | Docs checks pass |
| 2026-11-09 | Bounded 2x OCR upscale for small standalone images; PDF pages keep their OCR-DPI raster | [S3-OCR-RESOLUTION.md](S3-OCR-RESOLUTION.md) | 7 focused tests pass; full suite 876 passed |
| 2026-11-09 | Transparent PNGs are composited on a contrasting background before OCR | [S3-OCR-RESOLUTION.md](S3-OCR-RESOLUTION.md) | 7 focused tests pass; dark text recovered |
| 2026-11-09 | Separate headed non-GL crawl browser; drive keeps verified Mesa/WebGL | [S2-RENDERER-CPU.md](S2-RENDERER-CPU.md) | 0.706 -> 0.370 CPU-s/request; Crunchbase and drive pass |
| 2026-11-09 | Concise PDF presentation no longer claims omitted table metadata when the table list is empty | `tests/test_coverage_reading.py` | Full suite 876 passed |

## Candidate images

- Baseline worker: `dethrottled-dnb:1.8.0-candidate-20261109`
- Baseline API: `dethrottled-dnb-api:1.8.0-candidate-20261109`
- Current test-bed API: `dethrottled-dnb-api:1.8.0-dev-20261109`
  (`sha256:4bdeb3e31224…`)
- Current test-bed worker: `dethrottled-dnb:1.8.0-dev-crawlsplit3-20261109`
  (`sha256:e82fa102…`)
- Earlier OCR-only test image: `dethrottled-dnb-api:1.8.0-dev-ocr-20261109`
  (superseded)

The baseline images were not retagged or overwritten. Rebuild all images from the
current commit before any release decision.

## Guardrails

- Production remains on 1.7.1 and is never used as a test target.
- Every improvement keeps the reference comparison and raw evidence.
- A change that loses a fact, hides a warning or widens an allow-list is rejected.
- No version bump, publish or deployment without fresh approval.
