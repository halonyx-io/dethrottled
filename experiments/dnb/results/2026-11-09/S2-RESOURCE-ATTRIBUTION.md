# S2 resource attribution

2026-11-09. Candidate held. This records why the 1.8.0 render figure differs
from 1.7.1 and whether the reader or the renderer owns the gap.

## Direct extraction

40 sequential local fetches (HTML, PDF, DOCX, XLSX, PPTX), `render=never`,
`cache_mode=bypass`, cgroup `cpu.stat` deltas:

| Side | CPU-seconds | CPU/request | Median | p95 | Failures |
|---|---:|---:|---:|---:|---:|
| reference 1.7.1 | 31.199 | 0.780 | 1.568 s | 1.732 s | 0 |
| candidate 1.8.0 | 32.135 | 0.803 | 1.580 s | 1.768 s | 0 |

The reader is within 3% of the reference. There is no candidate core extraction
regression to fix here.

## Extraction worker

Ten in-process `html_extract` calls on the same fixture article:

- 0.187 CPU-seconds total, 0.0187 CPU-seconds per call.
- 3,475 markdown characters, all ten successful.

The extraction worker is not the source of the render gap either.

## Renderer

The Phase 6 resource smoke measured 10 renders at ~6.8-7.2 candidate
CPU-seconds versus ~2.4-2.8 reference CPU-seconds. The two sides are not the
same renderer: the reference path was the Crawl4AI service, while the candidate
is the consolidated Patchright/Chromium browser plus its extraction pool. A
single candidate headless/Mesa observation was 9.44 CPU-seconds for 10 renders,
so the result is dominated by browser mode and graphics backend, not by the
reader.

That does not prove the candidate is optimal. It means the next renderer
comparison must hold browser mode and graphics constant, and should measure
Chromium and Python worker CPU separately. Until then the gap is a documented
rendering-mode trade, not a reader regression.

Evidence: [s2-direct-cpu.json](s2-direct-cpu.json),
[s2-extract-bench.json](s2-extract-bench.json).
