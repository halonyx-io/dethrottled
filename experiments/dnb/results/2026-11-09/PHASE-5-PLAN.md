# Phase 5 plan: browser modes and GPU defaults

Checkpoint 1, 2026-11-09. **Executed**; the final record is `PHASE-5.md`.
This plan is retained as the approved scope. Phases 1-4 remain accepted;
production remains 1.7.1.

## Hardware and container access (measured)

Host: AMD Cezanne Radeon Vega iGPU. `/dev/dri/card0` is group `video` (44);
`/dev/dri/renderD128` is group `render` (991). The lab worker runs as
`browsersearch` uid/gid 10002 and currently has no `/dev/dri`.

| Lab container | `/dev/dri` | `graphics` health |
|---|---|---|
| no device mapping, `DETHROTTLED_BROWSER_GRAPHICS=auto` | absent | `webgl=true`, renderer `ANGLE (Mesa, llvmpipe ...)`, pixel `[64,128,191,255]`, `hardware_verified=false` |
| `--device /dev/dri --group-add 991 --group-add 44`, `auto` | card0 + renderD128 | `webgl=true`, renderer `ANGLE (AMD, AMD Radeon Graphics ...)`, pixel `[64,128,191,255]`, `hardware_verified=true` |

Both probes launched the real worker and read the existing
`browser-search/service.py` probe. Evidence: [phase5-access.json](phase5-access.json).
Hardware access does not require a driver install or host change; it requires an
explicit device/group mapping in the lab.

## Proposed matched matrix

| Mode | Launch | Graphics | Device |
|---|---|---|---|
| headed/software | `HEADLESS=0` | `default` | none |
| headed/hardware | `HEADLESS=0` | `auto` | `/dev/dri` + groups 991,44 |
| headless/software | `HEADLESS=1` | `default` | none |
| headless/hardware | `HEADLESS=1` | `auto` | `/dev/dri` + groups 991,44 |

`mesa` is available as an intermediate if `default` does not give a stable
software baseline. Every mode uses the same fresh-page lifecycle, scope,
0.5 s settle, page budget, `max_chars`, fixture, and run order (alternating).

## Proposed workloads

- `/article` and `/tiny`: static text facts.
- `/ticker` and `/long`: heavy JS/timer and long readable content.
- New `/webgl` fixture: canvas WebGL clear/readPixels plus a visible fact; proves
  page-level acceleration, not just launch.
- Drive screenshot: one screenshot through `/drive`.
- Recovery: `/redirect`, `/missing`, `/blocked-resource` with predefined facts and
  retained failures.

Five alternating repeats per mode; no parallel modes. Measure retained facts,
failures, latency, cgroup CPU, RSS, GPU busy/VRAM/GTT where readable, probe
`webgl`/renderer/pixel/`hardware_verified`, and crash/restart count.

## Proposed file/container changes

- `browser-search/service.py`: add an env-gated lab launch mode
  `DETHROTTLED_BROWSER_HEADLESS=1` (default `0`). Use it in all three launch paths
  and record `effective_headless` in the probe. Default behavior is unchanged.
- `experiments/dnb/fixture.py`: add `/webgl` with canvas WebGL and a `#ready` fact.
- `experiments/dnb/phase5_check.py`: disposable lab harness that starts one
  worker mode at a time and writes the matrix evidence.
- `experiments/dnb/phase5_lab.sh` if a shell wrapper is clearer than inline
  commands.
- Results: `PHASE-5.md`, `phase5-matrix.json`, `phase5-resources.json`,
  `phase5-webgl.json`, `phase5-failures.json`, `phase5-tests.log`,
  `phase5-provenance.json`.
- README phase table/current-work and documentation inventory.

No production Compose, Dockerfile dependency, driver or system package change.
The reference image must still be built from frozen 1.7.1 browser sources.

## Expected gates

1. All four modes complete the same workload with retained facts and failures.
2. Hardware modes show `hardware_verified=true` and a non-software renderer with
   correct pixel readback; software modes show `hardware_verified=false` and a
   working `llvmpipe`/software path.
3. No crashes or uncontrolled restarts; resource samples are bounded and retained.
4. Default choice is supported by the measured matrix; no unmeasured speedup claim.
5. Focused Phase 1-4 regressions pass; phase3_wire if the lab is available.

Approval needed for the `browser-search/service.py` headless lab flag and the
fixture/harness file list before editing source.
