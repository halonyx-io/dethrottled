# Dethrottled benchmark: szbox and q6a

Recorded 4 October 2026. This is a paired run of the same Dethrottled source
and pinned Python dependency set on x86_64 and ARM64. These are observed
results, not service-level guarantees. Public search engines and websites can
change their responses between the two sequential runs.

## Hosts and software

| | szbox | q6a |
| --- | --- | --- |
| Architecture | x86_64 | aarch64 |
| Processor | AMD Ryzen 7 5800U; 8 cores, 16 threads; up to 4.507 GHz | Radxa Dragon Q6A; 4 Cortex-A55 cores up to 1.958 GHz, 4 Cortex-A78 cores up to 2.707 GHz |
| RAM visible to OS | 30 GiB | 11 GiB |
| Benchmark storage | Samsung MZNLN512HMJP-000L7, 476.9 GB SATA SSD | Kioxia KXG60ZNV256G, 238.5 GB NVMe |
| OS and kernel | Debian 13.7, `6.12.111+deb13-amd64` | Ubuntu 24.04.5, `6.18.2-3-qcom` |
| CPU governor | `powersave` | `schedutil` |
| Docker / Compose | 29.8.2 / v5.5.1 | 29.1.3 / v2.40.3 (temporary for benchmark) |

Both API images used the same repository commit `604d69c` and the installed
Python package lists had the same SHA-256 hash,
`28c845048c57e87f6ae824a5e7f73274fb43881f16dfcd6c4642ee631411d664`.
The browser search image package lists also matched,
`781e89d5414816d05085102d20ebf3435e35bc6a39fda3483588fe1991e46ba3`.
Both API and browser
images were built natively for their host architecture. No CPU affinity,
container CPU quota, or container RAM cap was set. Other normal services on
each host remained running.

szbox used an isolated Compose bridge stack bound to `127.0.0.1:18788`.
q6a used a temporary Docker daemon with host networking and the same API
loopback port. The q6a daemon ran with `--iptables=false`,
`--ip6tables=false`, `--ip-forward=false`, `--ip-masq=false`, and
`--bridge=none`; the firewall configuration was not changed. Network topology
therefore differs slightly between hosts. The benchmark API and worker ports
were temporary, separate from the production szbox stack.

## Method and pass criteria

The harnesses are in [`scripts/benchmark_endpoints.py`](../scripts/benchmark_endpoints.py),
[`scripts/benchmark_parallel.py`](../scripts/benchmark_parallel.py),
[`scripts/benchmark_local.py`](../scripts/benchmark_local.py),
[`scripts/benchmark_pdf.py`](../scripts/benchmark_pdf.py), and
[`scripts/benchmark_fixtures.py`](../scripts/benchmark_fixtures.py).
Raw case results and resource samples are in
[`docs/benchmarks/2026-10-04/`](benchmarks/2026-10-04/); the 50 fixed fetch
URLs are in [`fetch-manifest.json`](benchmarks/2026-10-04/fetch-manifest.json).

- **Live search:** The same 50 **English** queries, spanning news,
  government, technical documentation, reference, science, documents,
  community, and web pages. `/search` and `/search-and-fetch` used `fresh: true`
  and `limit: 3`. A useful search has a URL and a title of at least ten
  characters. We separately checked whether the result set had three results
  and at least two snippets of 25 characters or more.
- **Fetch:** One URL was frozen from each szbox search result and the exact
  50-URL manifest was replayed on both machines with `fresh: true`. Its
  SHA-256 is `053da7a3dbbfffceb3763f79a1c24b4a194f361a1ca5986b10fabf33a96657de`.
  A substantial page has `quality: ok` and at least 600 extracted characters.
  `/search-and-fetch` uses the same threshold for at least one returned page.
  All failed and thin rows are counted even when the API HTTP status is 200.
- **Research:** Eight fixed English questions, `max_sources: 4`,
  `fresh: true`. A useful bundle needs a source containing evidence.
- **Controlled documents:** The same generated fixtures and content checksum
  were used on both hosts. HTML, table HTML, CSV, text PDF, scanned PDF with
  OCR, DOCX, XLSX, PPTX, ODT, EPUB, and RTF had to contain an expected marker.
  A false PDF signature and HTTP 404 had to fail. Each was tested three times.
- **Renderer and PDF worker:** Ten fixed public URLs with `render: always`
  and `fresh: true`; the tier field had to confirm Crawl4AI was actually used.
  The optional HTML-to-PDF worker made ten files, checked for a valid PDF
  signature. The q6a renderer had a separate diagnostic repeat because its
  first forced-render run fell through to direct extraction.
- **Concurrency:** The same 50 search queries were issued with three, then
  eight concurrent callers. The local API-only run also measured health,
  fixture fetch, and corpus search throughput. Local fixture fetches are
  subject to normal per-domain pacing, so more callers need not increase
  throughput.

Latency is client-observed wall time. Median and p95 are calculated from the
cases in each JSON file; p95 is the nearest-rank value. CPU and RAM came from
Docker `stats --no-stream` samples at roughly four-second intervals. **100%
CPU means one logical core**, so 400% means about four logical cores during a
sample. Reported peaks are sampled peaks and can miss shorter spikes. RAM is
Docker's reported working-set memory, not total host RAM or virtual image
size. All resource tables include idle as well as active periods during each
run.

## Live endpoint results

| Test | szbox useful | szbox median / p95 | q6a useful | q6a median / p95 |
| --- | ---: | ---: | ---: | ---: |
| `/search`, serial, 50 queries | 50/50 | 1.43 / 2.86 s | 50/50 | 2.66 / 3.92 s |
| `/search-and-fetch`, serial, 50 queries | 47/50 | 3.60 / 11.72 s | 47/50 | 5.56 / 26.03 s |
| `/fetch`, fixed 50 URLs | 42/50 | 0.506 / 1.42 s | 42/50 | 0.734 / 1.97 s |
| `/research`, eight questions | 8/8 | 7.54 / 9.40 s | 7/8 | 9.26 / 33.59 s |
| Optional HTML-to-PDF, ten files | 10/10 | 0.355 / 0.386 s | 10/10 | 0.904 / 1.055 s |
| Forced Crawl4AI, ten URLs | 10/10, 10 renderer | 1.52 / 2.97 s | 10/10, 10 renderer on diagnostic repeat | 2.21 / 2.99 s |

All 50 serial `/search` requests on both hosts returned HTTP 200, three
results, and at least two substantial snippets. `/search-and-fetch` produced
130 substantial page rows of 149 on szbox and 129 of 149 on q6a. The fixed
`/fetch` run had the same breakdown on each host: 42 substantial, one thin,
and seven failed. Failures included access restrictions and pages whose
content did not meet the extraction threshold. The q6a `/research` miss was
the lithium battery question: HTTP 200, zero sources, zero evidence after
33.6 seconds. That remains a failure in the benchmark.

The first q6a forced-render run yielded 10/10 substantial pages in 0.921 s
median, but **all ten came from `direct/trafilatura`**. It therefore cannot
be used as a renderer speed result. A subsequent repeat of the same ten URLs
used `crawl4ai/crawl4ai-native` in all ten cases; its 2.21 s median appears
in the table. The initial tier selection is preserved in the raw data and
shows that `render: always` can fall through to a cheaper tier when the
renderer is temporarily unavailable. The cause of that first fallback was
not confirmed.

## Concurrent search

| Concurrent callers | szbox useful / rich | szbox throughput | szbox median / p95 | q6a useful / rich | q6a throughput | q6a median / p95 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 3 | 50/50 / 50/50 | 1.24 queries/s | 2.15 / 3.21 s | 50/50 / 49/50 | 0.53 queries/s | 4.65 / 7.13 s |
| 8 | 50/50 / 50/50 | 1.48 queries/s | 5.19 / 6.22 s | 48/50 / 44/50 | 0.71 queries/s | 10.56 / 14.41 s |

“Rich” means three results with at least two snippets of 25 characters or
more. More callers improved throughput modestly while increasing individual
latency. Eight callers exposed two q6a search misses. The browser search
worker, rather than the API or SearXNG, consumed most CPU during these runs.

## CPU and memory by component

The following is the 50-query serial `/search-and-fetch` run. Each cell is
**mean CPU / sampled peak CPU; mean RAM / sampled peak RAM**. CPU percentages
are percentages of one logical core; RAM is MiB. PDF worker was present and
idle in this phase.

| Component | szbox CPU; RAM | q6a CPU; RAM |
| --- | ---: | ---: |
| Dethrottled API | 122.65 / 962.59%; 420.5 / 498.1 MiB | 109.89 / 631.40%; 401.6 / 459.8 MiB |
| Browser search worker | 24.45 / 113.72%; 321.9 / 406.1 MiB | 78.72 / 419.51%; 377.8 / 578.1 MiB |
| Crawl4AI renderer | 2.83 / 31.06%; 494.6 / 576.6 MiB | 11.61 / 150.80%; 612.3 / 718.2 MiB |
| SearXNG | 0.66 / 2.23%; 122.9 / 123.2 MiB | 1.10 / 4.94%; 144.0 / 144.7 MiB |
| Optional PDF worker | 0.06 / 2.67%; 22.3 / 22.3 MiB | 0.23 / 8.14%; 22.8 / 24.1 MiB |

For serial `/search` alone, the browser worker averaged 49.98% CPU and
370.8 MiB RAM on szbox, versus 175.86% and 438.2 MiB on q6a. The API
averaged 3.26% / 53.7 MiB and 6.05% / 54.3 MiB respectively. Under eight
concurrent search callers, the browser worker reached sampled CPU peaks of
349.64% / 611.06% and RAM peaks of 827.3 / 966.7 MiB on szbox / q6a.
The API-only controlled workload reached sampled CPU peaks of 662.99% and
751.87%, demonstrating that the service did use multiple cores; no CPU
pinning was applied. Full samples for **every component in every phase** are
in the raw JSON files.

When deliberately active, Crawl4AI averaged 50.80% CPU and 557.2 MiB RAM
on szbox, versus 94.76% and 698.7 MiB on q6a's diagnostic repeat; sampled
peaks were 116.42% / 641.5 MiB and 177.68% / 754.8 MiB. The optional PDF
worker averaged 43.65% CPU / 25.0 MiB on szbox and 109.70% / 96.2 MiB on
q6a, with sampled peaks of 87.26% / 27.7 MiB and 160.94% / 166.9 MiB.
The PDF worker runs were short, yielding only two and three resource samples
respectively; these figures are indicative, not reliable peak capacity
measurements.

## Controlled fixtures and local throughput

Both hosts met all **39/39 expected document outcomes** (11 real formats
times three, plus the false PDF and 404 times three). The median text-PDF
read was 30.0 ms on szbox and 106.6 ms on q6a; scanned PDF with OCR was
326.9 ms and 609.4 ms. These are local fixtures and do not include Internet
latency. Some p95 values include the normal 1.5 s per-domain pacing.

| Local API-only test | szbox | q6a |
| --- | ---: | ---: |
| Health, 120 requests, 1 / 8 / 32 callers | 1,500 / 2,182 / 2,400 req/s | 256 / 759 / 923 req/s |
| HTML fixture fetch, 24 requests, 1 / 4 / 8 callers | 7.77 / 5.33 / 5.33 req/s | 7.09 / 4.85 / 5.48 req/s |
| Corpus search, 48 requests, 1 / 4 / 8 callers | 200 / 273 / 281 req/s | 94 / 100 / 126 req/s |

All local load requests returned their expected outcomes. These short
microbenchmarks are useful for finding gross regressions; the live endpoint
tests above are the better estimate of agent-visible search and extraction
latency.

## Interpretation

szbox was consistently faster on the live end-to-end paths and retained all
50 useful search results at eight concurrent callers. The observed speedup
does not imply that CPU alone caused every difference: public engines and
sites vary, and the hosts were not otherwise idle or identically networked.
The paired fixed URL and controlled fixture tests support the direction of
the comparison. Search quality still needs explicit checks because an HTTP
200 can contain zero evidence or a thin/blocked page. The q6a renderer
fallback and research miss are concrete examples.

Raw JSON is retained so latency distributions, individual failures, tiers,
and component resource samples can be inspected without relying on this
summary.
