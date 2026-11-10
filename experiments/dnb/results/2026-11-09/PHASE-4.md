# Phase 4: inherited defects and presentation compatibility

Accepted for the isolated x86_64 prototype, 2026-11-09. Production remains
1.7.1. No release, deployment, version bump or Phase 5+ work.

## Report 1 — search-and-fetch PDF bloat: CONFIRMED

`compact_row` removed PDF `text_layer_blocks` but left `native_pdf_tables` and
`layout_tables` intact. A concise response could therefore carry the entire
structured table payload regardless of `max_chars`.

| Reproduction | Before | After |
|---|---:|---:|
| REST `/search-and-fetch`, `concise`, `max_chars=300`, synthetic large PDF row | **1,178,896 B** | **15,640 B** |
| Same, `detailed` | 1,423,701 B | 1,423,701 B (unchanged) |
| Real PDF: 20 pages, 20 detected tables, 99,791 table chars | 104,127 B concise | 4,396 B concise |
| MCP `search_and_fetch`, large synthetic PDF row, `concise`, `max_chars=300` | **100,754 B** | **4,419 B** |
| MCP same call, `detailed` | — | 241,495 B (unchanged) |
| MCP `fetch`, real IRS PDF over the public network, `concise`, `max_chars=300` | **32,640 B** | **4,466 B** |

The real PDF was generated with pymupdf and extracted through
`formats.read_blob(..., "pdf")`; the concise path removed 99,791 bytes of
duplicated table metadata and retained `native_pdf_table_count=20`, the page
methods, warnings, `document_id`, `document_chars`, `truncated` and the table
scan metadata.

Evidence: [phase4-sf-summary.json](phase4-sf-summary.json),
[phase4-sf-concise-after.json](phase4-sf-concise-after.json),
[phase4-real-pdf-metrics.json](phase4-real-pdf-metrics.json),
[phase4-mcp-sizes.json](phase4-mcp-sizes.json).

The MCP measurement used the real `adapters/mcp_server.py` streamable-HTTP
transport and the real `search_and_fetch` tool, with the same synthetic large
PDF row. The concise tool result fell from 100,754 to 4,419 bytes; detailed
stayed at 241,495 bytes.

The real-network MCP check used the same MCP bridge and `fetch` tool against
`https://www.irs.gov/pub/irs-pdf/f1040.pdf` (a public 220 KB form PDF with three
native tables). The concise result was 4,466 bytes, detailed 32,640 bytes,
`content_chars=300`; detailed retained 3 tables and concise retained
`native_pdf_table_count=3`. Evidence:
[phase4-mcp-real.json](phase4-mcp-real.json).

### Fix

`src/dethrottled/content.py::compact_row` now, for concise output only:
- replaces `native_pdf_tables` with `native_pdf_table_count`;
- replaces `layout_tables` with `layout_table_count`;
- records `presentation.omitted_table_metadata` and
  `detail_available_with={"response_format":"detailed"}`;
- keeps `native_table_scan`, `layout_tables_total`, pages, warnings and retained
  evidence fields;
- is idempotent and does not mutate the input. Detailed output is unchanged.

REST and MCP both use this presentation function; MCP passes `response_format`
through to the same endpoint, so no separate MCP code path was added.

Tests: `tests/test_coverage_reading.py::test_concise_pdf_omits_structured_table_metadata`
and `...::test_concise_mixed_batch_compacts_pdf_tables_and_keeps_plain_rows`.

## Report 2 — cache accounting: public path unconfirmed; raw footgun fixed

- Raw `Cache.get()` without a validator returned a valid-JSON wrong-shape entry
  and counted it as a hit (hits 1, misses 0).
- `CacheView.get()` already rejected the same `extract` entry as a **miss**
  before any caller saw it (hits 0, misses 1).
- Both public paths, `/fetch` and `/search-and-fetch`, pass `CacheView`, so the
  reported public-API accounting bug does not reproduce.
- The raw `Cache` behavior was a latent footgun for a direct internal caller
  that bypassed `CacheView`. The extract read now passes a shared shape validator
  (`valid_extract`) for both `Cache` and `CacheView`, so a wrong-shape row is a
  miss before it is counted or returned. Valid empty results and expiry are
  unchanged.

Evidence: [phase4-cache.json](phase4-cache.json),
[phase4-cache-tests.log](phase4-cache-tests.log).

Tests: `tests/test_cache.py::test_cacheview_rejects_wrong_shape_extract_before_counting_a_hit`
and `tests/test_autonomous_recovery.py::test_wrong_shape_cached_extract_is_refetched`.

## Report 3 — DOM adoption: CONFIRMED end-to-end and fixed

The unit/endpoint tiny-page selector test already covered direct HTML, but the
consolidated DNB renderer returned markdown-only when it also had a usable
source DOM. A real `/fetch` with `selectors={"p":{"selector":"p"}}`,
`render=always` against example.com returned:

| Tier | `structured.p` | Status |
|---|---|---|
| `crawl4ai/crawl4ai-native` before | `None` | `html_unavailable` |
| `crawl4ai/crawl4ai-native` after | the page paragraph | `satisfied` |

Cause: `_crawl4ai_payload()` preferred long markdown and discarded the worker's
full `html` field, even when the caller asked for selectors/raw output. Fix:
carry `keep_html` in the read options, prefer the full page HTML for those
callers, and retain it alongside markdown when requested. Markdown-only
consumers still receive text only.

A deterministic local fixture check now also passes: `/fetch` on the repo
`/tiny` page with `selectors={"h1":{"selector":"h1"}}`, `render=always`, returned
tier `crawl4ai/short` and `structured.h1="Tiny fact quartz-452"` with
`reason="satisfied"`; the tiny-page HTML is retained for selector callers even
when it is below the prose threshold.

Evidence: [phase4-dom-before.json](phase4-dom-before.json),
[phase4-dom-after.json](phase4-dom-after.json),
[phase4-dom-local-after.json](phase4-dom-local-after.json),
[phase4-dom-parity.log](phase4-dom-parity.log). The existing tiny-page test
remains, and the end-to-end selector case is recorded for the Phase 6
reference-vs-DNB parity checklist.

## Gates

| Gate | Result |
|---|---|
| Focused content/cache/fetch/contract tests | **138 passed, 8 skipped** |
| Phase 3 unit tests (delegation, owner store, operation store) | **25 passed** |
| Phase 1/2 focused tests in the worker image | **29 passed** |
| Host navigation/network/extraction units | **17 passed, 1 environment-only failure** (needs crawl4ai; passes in the image) |
| Phase 3 wire gate | **23 passed, 0 failed** |
| Phase 3 network gate | loopback 200, LAN 403 |

Evidence: [phase4-phase3-tests.log](phase4-phase3-tests.log),
[phase4-phase12-tests.log](phase4-phase12-tests.log),
[phase4-host-regressions.log](phase4-host-regressions.log),
[phase4-phase3-wire.json](phase4-phase3-wire.json),
[phase4-phase3-network.json](phase4-phase3-network.json).

## Reproduce

```sh
# Synthetic REST reproduction
PYTHONPATH=src python - <<'PY'
# build the 200-page row with 20 native_pdf_tables, then:
# TestClient(server.app).post("/search-and-fetch",
#   json={"query":"large pdf","response_format":"concise","max_chars":300})
PY

# Real PDF (inside an image with pymupdf; repo mounted read-only)
# generate 20 ruled table pages, call formats.read_blob(..., "pdf"),
# then compact_row(row) and compare JSON sizes.

# MCP: run adapters.mcp_server.py against a core whose _ranked/_extract_row
# return the real PDF row, then call the search_and_fetch tool with
# response_format=concise and detailed, max_chars=300. Sizes:
# experiments/dnb/results/2026-11-09/phase4-mcp-sizes.json

PYTHONPATH=src python -m pytest \
  tests/test_cache.py tests/test_coverage_reading.py \
  tests/test_fetch_edge_cases.py tests/test_content_validity.py \
  tests/test_contract.py -q
```

## What this does not prove

- No live-hostile-source or sustained load run; those remain Phase 6.
- The real-PDF reproduction is a generated table document, not a corpus of
  arbitrary publisher PDFs. Layout-worker output is covered by the same removal
  path but was not separately exercised here.
- Full 1.7.1 capability parity, browser/GPU modes and ARM64 remain Phase 5/6.
