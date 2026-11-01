# Dethrottled 0.7.0: implementation and measured coverage

Recorded 1 November 2026, Asia/Singapore. Baseline: 0.6.0 at `05efcc6`.

Dethrottled 0.7.0 is deployed on the existing API and public MCP route. It has
measurably stronger browser and PDF-table capabilities. This run does **not**
establish that it beats most paid web engines, or that general answer accuracy
has increased by a particular percentage.

## Recorded comparison

| Check group | 0.6.0 | 0.7.0 | What passing means |
|---|---:|---:|---|
| Controlled document/parser/range tasks | 21/22 | 22/22 | Required values recovered; PDF table includes structured cells |
| Browser workflows | 1/8 | 8/8 | Real headed Chromium completes the declared behavior or required refusal |
| Live discovery | 38/40 | 40/40 | Expected primary domain appears in the first eight results |
| Live source reading | 39/40 | 39/40 | Extraction succeeds and contains the declared phrases |
| **Mechanical total** | **99/110** | **109/110** | A coverage checklist, not a semantic accuracy score |

These are 110 mechanical checks, including 40 paired discovery/source tasks,
22 controlled parser/range checks and eight browser workflows. They are not
110 independent research questions. Both builds were measured once; search
engines and upstream pages can vary between sequential observations. The two
additional domain hits therefore do not prove a causal ranking improvement.

The clearest controlled improvement is **22/30 → 30/30** across the parser and
browser checks. Discovery and extraction on the first eight live source tasks
were also checked before deployment: both builds passed all sixteen checks.

Both builds failed the strict static-only PyTorch documentation read. A separate
0.7.0 request using the normal thorough recovery workflow recovered the page.
That follow-up is recorded separately, not substituted into the original score.
The fixed suite therefore remains 109/110.

The baseline's first expanded run started before its container was ready. Those
connection resets were a harness failure, **not engine failures**; that run is
retained as `web-startup-invalid.json` and excluded. The harness now waits for
health before scoring, and the corrected baseline is the one reported above.
A browser restart occurred during the corrected baseline window; together with
shared upstream/browser state this is another reason not to attribute the two
search differences to code. The controlled browser checks use separate instances.
The broad suite ran before the final redirect-ledger and retry-compatibility fixes;
those fixes have focused tests and a final public smoke, rather than an invented
second 110-check run.

## What changed and why

**Discovery preserves independent sources.** Identical titles no longer cause
one URL to erase another site's result. Exact duplicate URLs merge discovery
provider/query provenance. Research still detects mirrors using extracted content.
This favors coverage while retaining evidence-based deduplication later.

**Optional Exa, Tavily and Parallel adapters are implemented.** Server-side keys
and an explicit `engines` selection are both required; ordinary profiles remain
keyless. Configured-provider booleans are discoverable through capabilities.
Failures preserve other providers' results, diagnostics distinguish configuration
and upstream failures, and metered cost is reported as unknown. Credentials are
never agent tool arguments. Contract tests cover payloads, provenance, missing
keys and failure isolation. **No account keys were provided, so these adapters
have not been validated against paid live accounts, quotas or billing.** Interfaces
were checked against the official [Exa](https://exa.ai/docs/reference/search),
[Tavily](https://docs.tavily.com/documentation/api-reference/endpoint/search) and
[Parallel](https://docs.parallel.ai/api-reference/search/search) documentation.

**PDF structure now has a dependable native path and optional neural recovery.**
Auto reads retain native text and add detected table cells, page boxes and
partial-output warnings. `inspect_document` exposes those cells and coordinates.
`document_mode=layout` requests the new private Docling worker; `native` skips
layout analysis. Fetch, retained-document reparsing and durable fetch jobs expose
the mode through MCP and REST. Acquisition-cache compatibility includes it.

Docling 2.145.0 and CPU PyTorch are installed in a separate container. Model weights
persist locally; the downloaded cache is approximately 506 MiB. The worker accepts
PDF bytes only, has one active conversion, bounded input/page ranges, a 180-second
child deadline, and an 8 GiB/four-CPU Compose ceiling. This follows Docling's
[document conversion interface](https://docling-project.github.io/docling/usage/advanced_options/).

The initial neural result missed the ruled table fixture. The final implementation
therefore prefers recovered native tables and rejects inference that loses tables,
numeric tokens or substantial text. It successfully converted the multicolumn
fixture through the actual production worker. This worker does native-text layout
inference; existing OCR still handles scans. Complex scanned-table structure and
chart interpretation remain limitations, and ARM64 has not been tested for this worker.

**Browser coverage and recovery are stronger.** Chunked JSON can be read without
Content-Length; declared and decoded bodies are checked against 2 MB. Locator
actions can target an allowed iframe. Agents can list/switch popup tabs.
Checkpoints preserve cookies, localStorage, sessionStorage and IndexedDB across
process restart. They retain bounded action history; live DOM and other tabs are
not restored. History contains outcomes, not typed secrets or a script to replay.
Completed operation IDs still replay their recorded result; unknown outcomes stay
blocked. An explicit compatibility check verifies pre-0.7 retry IDs remain usable
when the new optional frame selector is omitted.

**Research exposes gaps instead of implying completeness.** `coverage.facets`
records readable references, matched/missing terms, unread candidates, failed or
duplicate reads, and exact suggested follow-up calls. Redirected reads are not
miscounted as unread. Research now defaults to thorough keyless discovery.
`answer_verified` remains false: lexical overlap does not establish truth,
agreement, a supported answer or exhaustive source coverage.

**Agents are told how to use the additions.** MCP initialization instructions,
tool schemas, capabilities and source workflows describe the new controls and
continuations. The published workflow hash matches the backend's policy. No
client-specific skill is required to discover them.

## Agent, competitor and deployment evidence

Three fresh Ollama tool-loop conversations used `deepseek-v4.1-flash:cloud` with
temperature zero and the published MCP policy/schemas. The agents recovered the
requested year-specific table values, portal allocations, and—in an additional
interaction task—pressed the iframe control, switched to the popup and reported
its content. Core requested facts were recovered in all three. This is small,
synthetic qualitative evidence, not a broad autonomy success rate. The first
portal run used direct source reads after a fixture-only host-policy mismatch;
the subsequent interaction run corrected the test harness's exact-host exception.
Production target policy was not relaxed. Hidden model reasoning is not recorded.
The text-only agent harness also does not demonstrate visual verification merely
because a tool returned an image.

A small anonymous **Jina Reader comparison passed 8/8 identical source-phrase
checks**, as did Dethrottled on those sources. This is parity on a small reading
sample. It does not compare search, paid tiers, freshness guarantees, semantic
faithfulness or authenticated browser workflows. No paid-product superiority
claim is supported by this run.

Final validation: **524 tests passed, 15 skipped, two network tests deselected**;
Ruff passed. Live checks separately exercised the public MCP endpoint, real MCP
SDK 1.28.1, PDF reading, document inspection/reopening across MCP and REST, speech,
research coverage, browser checkpointing and cleanup. Direct headed search returned
ten DDG Lite results. Runtime module/file hashes match the checkout; credential
registry hashes are unchanged. Only the layout-worker URL was added to the existing
runtime environment. Existing media, renderer and SearXNG services were preserved.
Protected database/config backups and rollback images were created before deployment.

## What should happen next

1. Configure one independent paid discovery account, then run matched repeated
   trials using relevance judgments and answer/citation checks. Until credentials
   are configured, paid-provider contract tests cannot prove real coverage gains.
2. Add real complex/scanned financial and scientific documents with manually
   checked cells, reading order and source citations. Prioritize scanned tables,
   merged headers, charts and native/visual disagreements over adding format names.
3. Extend cold-agent evaluation to multi-facet research, contradictions, source
   updates, absent answers and hostile source instructions. Measure unsupported
   claims and remaining gaps, rather than only whether tools were called.
4. Repeat the live suite on different days and hosts, including realistic remote
   MCP clients. This release verifies the public protocol, not which plugin revision
   a separately operated OpenClaw gateway has loaded.

The raw evidence, frozen task expectations, earlier unsuccessful runs, agent tool
traces and operational checks are included in [the accompanying archive](evidence.zip).
Publication of this evidence does not change the measurement limitations above.
