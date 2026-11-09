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
| 2026-11-09 | News searches use a 30-minute cache ceiling; caller `max_age` can tighten it | [SIMILAR-PROJECTS-IDEAS.md](SIMILAR-PROJECTS-IDEAS.md) | Endpoint tests pass |
| 2026-11-09 | Cache expiry + 512 MiB ceiling + `/stats` bytes | [P0-BUGS-EFFICIENCY.md](P0-BUGS-EFFICIENCY.md) | 17 cache tests pass |
| 2026-11-09 | Idle crawl-browser close + Chrome memory pressure | [P0-BUGS-EFFICIENCY.md](P0-BUGS-EFFICIENCY.md) | idle 691 -> 486 MiB; relaunch 1.18 s |
| 2026-11-09 | PDF CID-corruption detection forces OCR | [P0-BUGS-EFFICIENCY.md](P0-BUGS-EFFICIENCY.md) | targeted PDF tests pass |
| 2026-11-09 | Long login/paywall/access-denied pages no longer read as `ok` | [P0-BUGS-EFFICIENCY.md](P0-BUGS-EFFICIENCY.md) | controlled audit; gates warn |
| 2026-11-09 | Tested Reddit `old.reddit.com` rewrite | [P0-BUGS-EFFICIENCY.md](P0-BUGS-EFFICIENCY.md) | not adopted; old.reddit failed |
| 2026-11-09 | MCP `MCP_TOOL_PROFILE=core` cuts tool surface 20 -> 6 | [P0-BUGS-EFFICIENCY.md](P0-BUGS-EFFICIENCY.md) | 7.8K -> 4.2K approx tokens |

| 2026-11-09 | Concise PDF presentation no longer claims omitted table metadata when the table list is empty | `tests/test_coverage_reading.py` | Full suite 876 passed |

## Candidate images

- Baseline worker: `dethrottled-dnb:1.8.0-candidate-20261109`
- Baseline API: `dethrottled-dnb-api:1.8.0-candidate-20261109`
- Current test-bed API: `dethrottled-dnb-api:1.8.0-dev-p0-20261109`
  (`sha256:00fdfbcf…`)
- Current test-bed worker: `dethrottled-dnb:1.8.0-dev-p0-20261109`
  (`sha256:316174ac…`)
- Current P0 worker/API also carry the cache, CID and gate fixes.
- Earlier OCR-only test image: `dethrottled-dnb-api:1.8.0-dev-ocr-20261109`
  (superseded)

The baseline images were not retagged or overwritten. Rebuild all images from the
current commit before any release decision.

## Guardrails

- Production remains on 1.7.1 and is never used as a test target.
- Every improvement keeps the reference comparison and raw evidence.
- A change that loses a fact, hides a warning or widens an allow-list is rejected.
- No version bump, publish or deployment without fresh approval.
