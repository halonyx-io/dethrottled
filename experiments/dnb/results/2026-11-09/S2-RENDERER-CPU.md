# S2 renderer CPU improvement

2026-11-09. Candidate held. This is a test-bed change, not a release.

## Baseline

Ten renders of `https://example.com` through each full stack, `render=always`,
`cache_mode=bypass`, cgroup CPU deltas:

| Side | Core CPU | Renderer CPU | Total CPU | CPU/request | Median |
|---|---:|---:|---:|---:|---:|
| reference 1.7.1 (Crawl4AI) | 0.112 s | 1.964 s | 2.159 s | 0.216 | 0.652 s |
| candidate baseline (DNB) | 0.087 s | 6.815 s | 7.063 s | 0.706 | 0.631 s |

The core reader is not the cause: direct extraction is within 3%, and the
in-process extractor is about 0.019 CPU-seconds per call. The DNB renderer was
running one headed Chromium with Mesa/llvmpipe for **both** bulk crawl and drive.
Its GPU process spent most of the CPU.

## What was tried

| Candidate renderer | CPU/request | Observed |
|---|---:|---|
| headed, Mesa/llvmpipe (baseline) | 0.706 | Crunchbase readable |
| headless, SwiftShader | 0.338 | Crunchbase failed in one observation |
| headed, default graphics (no GL) | 0.373 | Crunchbase readable |
| headed SwiftShader | 1.733 | Rejected, worse |
| separate crawl browser, headed default graphics | **0.370** | Crunchbase readable |

The separate-browser design keeps the verified Mesa/WebGL browser for `/drive`
and challenge recovery, and gives bulk `/crawl` its own headed Chromium with
default graphics. This preserves page behaviour while removing llvmpipe from the
bulk path.

## Implemented

- `browser-search/service.py` can launch `app.state.crawl_browser` when
  `DETHROTTLED_CRAWL_SEPARATE=1`.
- The crawl browser is headed by default
  (`DETHROTTLED_CRAWL_HEADLESS=0`) with no GL arguments
  (`DETHROTTLED_CRAWL_GRAPHICS=default`).
- `dnb_service.py` uses the crawl browser for `/crawl`; the existing headed
  browser remains the drive browser and still reports verified Mesa/WebGL.
- The browser watcher now checks both browsers; a crash still exits the worker
  for Compose supervision.
- `experiments/dnb/start.sh` enables the split by default.

## Result

Ten renders after the change:

| Measure | Baseline | Split |
|---|---:|---:|
| CPU-seconds per 10 renders | 7.063 | 3.700 |
| CPU/request | 0.706 | 0.370 |
| Core CPU/10 | 0.087 | 0.090 |
| Renderer CPU/10 | 6.815 | 3.599 |
| Median latency | 0.631 s | 0.619 s |
| Successful renders | 10/10 | 10/10 |

That is a **48% reduction** in render CPU at the same latency. Reference remains
lower at 0.216 CPU-seconds/request; this change closes about half the gap without
changing the successful Crunchbase result.

Functional checks after the change:

- Crunchbase fresh read: `quality=ok`, `crawl4ai/crawl4ai-native`.
- Drive: title and `h1` read from the fixture; headed browser still works.
- Concurrent two fetches plus a drive: all successful.
- Focused worker tests: 29 passed.

## Trade

The second browser costs memory: `p6-browser` was about **1.0 GiB** versus
~0.52 GiB for the single-browser baseline/reference. The lab ceiling is 4 GiB.
The crawl browser has no GL/WebGL; the drive browser retains verified WebGL. A
headless crawl variant was cheaper still but lost a Crunchbase read in one
observation, so it remains opt-in and is not the default.

Candidate worker image for this check:
`dethrottled-dnb:1.8.0-dev-crawlsplit3-20261109`
(`sha256:e82fa102…`). Frozen images remain unchanged.

Evidence: [s2-renderer-cpu.json](s2-renderer-cpu.json),
[s2-renderer-concurrency.json](s2-renderer-concurrency.json),
[s2-renderer-functional.json](s2-renderer-functional.json).
