# Phase 5: browser modes and GPU defaults

Accepted for the isolated x86_64 lab, 2026-11-09. Production remains 1.7.1.
No release, deployment or driver/system change.

## Hardware and access

Host: AMD Cezanne Radeon Vega iGPU. `/dev/dri/card0` is group `video` (44);
`/dev/dri/renderD128` is group `render` (991). The worker image runs as
`browsersearch` uid 10002.

| Lab mode | `/dev/dri` | Probe |
|---|---|---|
| no device, `auto` | absent | `llvmpipe`, pixel `[64,128,191,255]`, `hardware_verified=false` |
| `--device /dev/dri --group-add 991 --group-add 44`, `auto` | present | `ANGLE (AMD, AMD Radeon Graphics ...)`, pixel `[64,128,191,255]`, `hardware_verified=true` |

Evidence: [phase5-access.json](phase5-access.json). No driver install or host
change was needed; access is an explicit lab device/group mapping.

## Matched matrix

Three repeats of six fixture workloads per mode; 18 requests per mode. Same
fresh-page lifecycle, scope, 0.5 s settle and page budget. No new fixture
endpoint was added; the existing `/ticker` page is the heavy-JS workload and
the launch probe supplies canvas/WebGL pixel evidence.

| Mode | Effective | Renderer | Raster / Comp | Verified | Median | Screenshot | CPU | RSS |
|---|---|---|---|---|---:|---:|---:|---:|
| headed/software (`mesa`) | headed | Mesa llvmpipe | enabled / enabled | no | 647 ms | 201 ms | 1.07% | 509 MB |
| headed/hardware (`auto` + device) | headed | AMD ANGLE | enabled_force / disabled_software | yes | 655 ms | 180 ms | 0.86% | 471 MB |
| headed/hardware, no device groups | headed | Mesa llvmpipe | enabled / enabled | no | 642 ms | 212 ms | 1.07% | 505 MB |
| headless/software (`mesa`) | headless | Mesa llvmpipe | enabled / enabled | no | 655 ms | 179 ms | 0.25% | 527 MB |
| headless/hardware (`auto` + device) | headless | AMD ANGLE | enabled_force / enabled | yes | 635 ms | 205 ms | 0.83% | 489 MB |

All 90 reads retained their predefined facts. Each mode had three expected
`/missing` recovery failures (`network_policy:allowed_host`); the failure is
retained rather than counted as coverage. Recovery requests were paced one second
apart. Fifteen screenshots (three per mode) succeeded, ~139 KB each. No
restart-count change. Hardware modes increased VRAM use from ~36 MB to 53-100 MB;
software modes showed no VRAM increase. The medians are too close to claim a
headless or GPU speedup.

`Raster / Comp` is from Chromium's `SystemInfo` feature status. Hardware modes
force GPU rasterization; headed hardware reports software compositing under
Xvfb while headless hardware reports compositing enabled. That is reported as
measured, not assumed. Screenshot times do not show a consistent GPU speedup.

The extra `headed/hardware, no device groups` row is the **inaccessible** case:
the device is present but the render/video groups are not granted. `auto` falls
back to llvmpipe with `hardware_verified=false`, so a device that cannot actually
be opened is not reported as acceleration.

Evidence: [phase5-matrix.json](phase5-matrix.json),
[phase5-summary.json](phase5-summary.json).

## CPU/GPU division

Chromium owns GPU raster/WebGL for the page and screenshot; Crawl4AI extraction
remains on the CPU workers. The hardware modes retained every fact and produced
screenshots while CPU/RSS stayed bounded, so the GPU is helping the rendering
path rather than replacing or duplicating extraction. No second browser or GPU
worker was added.

## Decision

- Keep **headed** as the default (`DETHROTTLED_BROWSER_HEADLESS=0`). Headless
  works and is measured, but there is no verified content/resource reason to
  change the default.
- Keep **`DETHROTTLED_BROWSER_GRAPHICS=auto`**. With a mapped render device it
  verifies hardware via WebGL pixel readback; without one it falls back to
  llvmpipe. `mesa` is the explicit software baseline.
- Headless remains an opt-in lab/operator mode; it uses full Chromium via
  `channel=chromium` because the image does not ship `chrome-headless-shell`.
- The WebGL probe remains per launch, not per request. No second browser or GPU
  worker was added.

## Code changes

- `browser-search/service.py`: `DETHROTTLED_BROWSER_HEADLESS=1` lab flag
  (default off), used in all launch paths; health/probe reports
  `effective_headless`. Headless uses `channel="chromium"`.
- `experiments/dnb/Dockerfile`: copy the browser service into the phase-5 image.
- `experiments/dnb/dnb_service.py`: `/dnb/status` exposes `drive_sessions`, the
  real count of active drive sessions, so the identity gate can distinguish a
  render-pool read from a headed/read-plan drive.
- `experiments/dnb/phase3_check.py`: worker-contact and reuse checks accept either
  a render-pool context or a drive session; same-caller reuse requires both
  counts unchanged, cross-caller requires a change.
- `experiments/dnb/phase5_check.py`: disposable five-mode lab harness; writes
  bounded matrix and summary JSON with CPU, RSS, screenshot and feature status.
- No new HTTP endpoint, production Compose, dependency or host change.

## Gates

| Gate | Result |
|---|---|
| Phase 5 matrix | 5 modes, 18 reads + 3 screenshots each (90 reads, 15 screenshots), 0 fact failures, 3 expected `/missing` failures per mode |
| Hardware verified | true only with device + `auto`; software falls back correctly |
| Screenshots | 200 / ~139 KB in every mode, three repeats |
| Restarts | 0 in every mode |
| Phase 1/2 in phase-5 image | 29 passed |
| Phase 4 focused tests | 138 passed, 8 skipped |
| Phase 3 wire on phase-5 image | 23 passed, 0 failed |

The phase-3 wire now accepts either a render-pool context or a drive session as
evidence that the worker handled the read. Both are real worker state; the
`headed/read-plan` path creates a drive session rather than a render context.

## Reproduce

```sh
docker build -f experiments/dnb/Dockerfile \
  --build-arg BROWSER_IMAGE=dethrottled-dnb:phase3-20261109 \
  -t dethrottled-dnb:phase5-20261109 .
python experiments/dnb/phase5_check.py \
  --image dethrottled-dnb:phase5-20261109 --repeats 3 \
  --output experiments/dnb/results/2026-11-09
```

## Limits

- One host, one AMD iGPU; Intel/NVIDIA/ARM hosts remain separate cases.
- Three repeats per mode; no sustained load or hostile-source campaign.
- `/missing` recovery failure reason is retained; it is not a Phase 5 success.
- Full 1.7.1 capability parity and release remain Phase 6.
- No artificial mid-run GPU crash injection; absent and inaccessible hardware
  fallbacks are verified.
