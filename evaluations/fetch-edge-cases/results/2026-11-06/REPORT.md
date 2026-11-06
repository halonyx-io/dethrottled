# Fetch edge-case investigation — 6 November 2026

Baseline: published 1.7.0 runtime. Candidate: source changes based on Git
`a774f15`, tested inside the existing x86_64 runtime image with the source mounted.
No image build, version bump, publication or production deployment was performed.

## Reachability: confirmed delay, incorrect IPv6-only diagnosis

The reported URL is `https://www.gnu.org/philosophy/free-sw.html`.
The host resolves to IPv4 `209.51.188.116` and IPv6
`2001:470:142:5::116` here. `getent hosts` displaying IPv6 alone did not prove
absence of IPv4. DNS lookup took 0.67 seconds in this observation. Separate
curl checks found a two-second IPv4 connect timeout and an immediate IPv6
connection failure.

One direct/TLS run per version, no cache and rendering disabled:

| Measurement | Baseline | Candidate |
|---|---:|---:|
| Direct tier | 20,011.88 ms | 2,005.45 ms |
| TLS tier | 8,075.43 ms | 2,076.79 ms |
| Total | 28.151 s | 4.162 s |
| Successful source reads | 0 | 0 |

Raw receipts: [baseline](gnu-before.json), [candidate](gnu-after.json).
This is an observed latency reduction, not recovery or a sustained benchmark.
The candidate gives direct/TLS a separate two-second connection allowance;
direct reads retain their requested read allowance. curl_cffi's streaming
low-speed allowance remains eight seconds by default. Operators can override
`DETHROTTLED_CONNECT_TIMEOUT`.

DNS is not bounded by Requests' connect timeout; multiple addresses can multiply
that timeout. Renderer and browser deadlines are unchanged. This does **not**
prove a two-second end-to-end failure, nor does it remove worker escalation.
A generic `ConnectionError` may wrap a reset, handshake problem or exhausted
address attempts; it is not sufficient evidence that every worker/network path
will fail. The existing transient-connection recovery regression remains.

## Large REST responses: warning, no silent contract change

REST keeps its detailed default. Detailed fetch, job, retained-read and research
source presentation now warns when known text representations total at least
131,072 characters, recommending concise mode and a smaller excerpt. This is a
lower bound, not a claim to measure every serialized byte. No response fields
or retained evidence are removed by the warning.

A cached live RFC 9110 PDF read provided one fixed row: 194 pages, 466,034
canonical characters, `source_partial=false`. Replaying that identical row:

| Presentation | JSON bytes | Median / p95 presentation time |
|---|---:|---:|
| Detailed with warning | 939,642 | 113.04 / 126.65 microseconds |
| Concise | 45,686 | 47.07 / 51.47 microseconds |

The payload difference is 95.14%; content and document hash were identical.
Timing uses 300 helper calls per mode and excludes acquisition/serialization.
This is one document, not a universal saving. The original live detailed
response was 939,511 bytes. [Metrics and captured-response hash](payload-summary.json).
The captured full response is kept locally rather than adding a duplicate PDF
extraction to the repository. The compaction itself already existed; the new
behaviour is the warning.

## Selectors: confirmed small-DOM bug, current example.com claim not reproduced

Two current live calls, text and HTML, both returned the `<title>` value
`Example Domain`; neither source contained an `<h1>`. Both correctly reported
`fields_absent` for the requested heading. The reported h1 assertion cannot be
used as a current regression fixture.

Controlled minimal documents did expose the underlying issue: prose extractors
reject very small HTML, and text-mode acquisition discarded the DOM even when
selectors requested it. The candidate keeps that DOM eligible, without upgrading
the short prose quality. Fixtures cover a small heading, head-only title and
empty anchor with an attribute, in text and HTML formats. Clipped tiny HTML also
retains `source_html_partial`; previously a thin-result reason could hide the
capture's truncation reason. Ordinary reads and challenge detection retain
their existing policy.

## Verification

The initial focused baseline run had eight failures and three passes, confirming
missing tiny-DOM handling, unsplit timeouts and absence of the new warning.
Native x86_64 tests cover actual slow loopback response bodies in both Requests
and curl_cffi: body delivery exceeds the connect allowance and still succeeds.
No new dependencies, services, models or network probes on the normal fetch path.
ARM64 has not been rerun for this candidate.

Final non-network x86_64 suite: **974 passed, 15 skipped, two network tests
deselected**, 68.84 seconds. Deprecation warnings and curl_cffi's existing
chunk-size warning were reported. Focused relevant regressions also passed.
The first wider-suite command used an incorrect test filename and collected no
tests; it was corrected before the successful focused/full runs. No failed
assertion from the corrected candidate run remains.

## Follow-up: adjacent defects and scheduling efficiency

Three further changes were confirmed against the same baseline:

- The synchronous batch reader submitted four URLs, then waited for that whole
  chunk before submitting another. A slow first URL held up later reads despite
  free executor slots. The candidate refills completed slots, preserving input
  row order, at most four in flight per request and the shared eight-thread pool.
- Link-format reads resolved relative anchors against the requested URL, even
  after a redirect changed the page's origin or directory. They now use the
  final acquired URL. The requested URL and final URL provenance remain distinct.
- CacheView trusted decoded JSON shapes. Null, arrays or scalars in an extraction
  slot, invalid metadata containers, and malformed search rows could cause
  exceptions. These entries now miss and use normal acquisition. Valid empty
  search lists remain valid hits. Corrupt JSON is counted as a cache miss rather
  than a successful hit. Freshness and expiry policies are unchanged.

The new regression file initially produced **16 failures and three passes**.
After the changes, a focused combined run passed **125 tests**, including the
earlier edge-case fixes, cache policies and retained-document tests.

### Controlled batch measurement

Twelve URLs per batch; twelve paired runs per workload, alternating scheduler
order. Normal fixture reads wait 30 ms; designated slow reads wait 180 ms.

| Fixture | Prior median | Candidate median | Change |
|---|---:|---:|---:|
| One slow source (index 0) | 241.868 ms | 180.515 ms | 25.4% faster |
| Two slow sources (indices 0 and 4) | 391.584 ms | 210.956 ms | 46.1% faster |
| Uniform source times | 92.312 ms | 92.217 ms | Effectively unchanged |

Peak active reads remained four for every workload and scheduler. Every output
row, source order, fact, document handle, quality label and warning matched by
SHA-256, including the thin fixture. [All samples](batch-results.json) and
[reproduction](../../README.md) are retained. These are controlled scheduler
measurements; no claim of the same percentage improvement across the live web.

No source pool, search ordering, extraction algorithm, read budget or recovery
tier was removed. A proposed duplicate-retention cleanup was left alone because
it would need to preserve recovery metadata and evidence variants; it was not
an equally small, proven improvement.

Final follow-up verification: **993 passed, 15 skipped, two network tests
deselected**, 71.24 seconds on native x86_64. Repository lint, documentation
coverage, examples/links and generated-contract checks also pass. The first
benchmark container invocation lacked Git; it produced no measurements. The
working reproduction passes an explicitly exported baseline source file instead.
[Verification record](verification.json) identifies tested source hashes.
