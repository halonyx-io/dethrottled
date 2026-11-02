# Audit assessment — 2 November 2026

This assessment checks `DETHROTTLED-AUDIT-2026-11-02.md` against deployed 1.0.1,
package metadata, upstream releases and controlled tests. The source document is
identified by [hash](audit-source.json); its recommendations are assessed rather
than treated as deployment instructions. Changes prepare 1.1.0.

## Findings and disposition

| Finding | Assessment and action |
|---|---|
| Bridge dependencies drift | Confirmed. Install the full 32-package `requirements/adapters.lock`, not only the four direct requirements. Container and host environments use the same lock. Pip is bootstrap tooling, not an application transitive. Offline checks validate every installed pin and `pip check`. |
| Python base image moves | Confirmed. All six Dockerfiles pin multi-architecture index `sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30`, including native AMD64/ARM64 manifests. Apt downloads and external browser/model assets are separate inputs; this is not a byte-identical build claim. |
| Core versions are behind | Confirmed against [package metadata](dependency-versions.json). Refresh 27 existing pins, including certifi, curl_cffi, FastAPI/Starlette, Pillow, PyMuPDF, Resiliparse/FastWARC and ONNX. The resolved runtime has 76 packages, including five new PyMuPDF 2 dependencies. |
| Known dependency advisories | The baseline scan flags Brotli, certifi, filelock and Pillow. The candidate core and adapter scans return no known advisories at the observation time. This is a package-database check, not an exploitability assessment or proof that no vulnerability exists. |
| Dateutil 4 provenance | PyPI provenance names `dateutil/dateutil`, `publish.yml`, environment `release`; the upstream repository publishes matching 4.0.0 release notes. The cadence alone does not establish compromise. Retain 2.9.0.post0 here: no advisory was found, and the new Python 3.11 floor/stricter date parsing needs its own compatibility decision. |
| Hugging Face Hub 2 | Retain 1.33.0. Hub 2.4 adds a different HTTP client dependency (`httpx2`); no current vulnerability or required Dethrottled feature justifies including that migration in this pass. |
| Remove OpenTelemetry API | Rejected. Installed distribution metadata declares it a required FastAPI dependency. Keep it and its pin; `pip check` now makes missing required dependencies visible. No tracing/telemetry exporter is enabled by this change. |
| Bridge/backend mismatch | Add startup probing, ten-second cached health diagnostics and transition warnings. Expose backend `match`, `mismatch` or `unavailable`; do not prohibit rolling upgrades. Version equality is not proof of matching source or correct answers. |
| MCP result framing | Preserve the existing per-entry JSON values and native blocks. Compact JSON text without changing parsed values, order or structured content. Document parsing each entry, never concatenating entries into one JSON value. Do not introduce a breaking array envelope or new search output schema. |
| PDF print-worker pin | Keep 0.9.4: its offline utility is independent of Crawl4AI server 0.9.5. |
| GPU overlay is inactive | The `.env` list alone is incomplete evidence: the production helper selects the GPU override dynamically. Hardware rendering was verified during the 1.0 deployments. Keep the helper and portable software default. |
| MCP protocol is fixed | The audit's 2025-06-18 observation is one negotiated client session, not a universal protocol version. Retain SDK 1.30.0; no SDK 2 migration is required. |

## Larger useful ceilings

The [limits guide](../../../../docs/LIMITS.md) gives defaults and ceilings. Search
can return 50 results; research permits 30 sources and ten additional facets, with
120,000 characters per source. Its defaults rise from six sources/5,000 characters
to ten/12,000. Fetch, retained reads and explicit browser text/HTML actions permit
one million characters. Automatic headed recovery retains its staged HTML capture
and can read up to one million visible-text characters when that capture is partial.
Concurrency, queue admission, input-file limits and timeouts remain bounded.
These are request capacities, not promises that every upstream provides enough
material or that every source becomes readable.

Controlled core requests retain the 50th search result and 30 research sources
across all eleven facets, both across publishers and from one publisher. An
additional hard two-per-publisher selection cap is replaced by a diversity
preference: consider diverse publishers first, then fill remaining capacity
with additional primary documents. URL/content deduplication remains. The [regression log](regression-final.log) reports
**652 passed, 15 skipped and two network tests deselected**. FastAPI's existing
startup/shutdown-event deprecations remain warnings, not silent failures.

The offline adapter harness uses a real MCP client/server and deterministic local
HTTP backend. It checks the expanded limits on MCP and REST, strict arguments,
authentication/revocation and private-target rejection. Its backend begins on a
different version, then changes without a bridge restart; health observes both
states and startup logs the mismatch. It preserves all result rows and structured
payloads while reducing equivalent JSON whitespace. This is a fixture measurement,
not a claim that all responses shrink by the audit's 17.6% example.

Production inspection also found explicit `MCP_MAX_RESULTS=10` and
`MCP_MAX_CHARS=50000` settings. These must be raised during promotion; new code
defaults alone would leave remote agents capped. The new transport tests cover
all 50 result entries rather than concatenating or discarding them.

## TLS observations

[Baseline](tls-baseline.json) and [candidate](tls-candidate.json) use the same host,
Chrome impersonation, fixed sources, predefined facts and an 18-second timeout.
Both retain the same Python documentation facts and content hash. Neither recovers
the Reddit thread facts through TLS alone; Crunchbase and G2 remain blocked.
The missing Reddit blocker label in one candidate observation is not usable content.
Individual timings are retained, but the sample does not establish a speedup.
The upgrade is retained for maintenance/security fixes, not an anti-bot win.

## Reproduction and remaining gates

Run the normal Dockerfiles, offline core/adapter verifiers, full regression suite
and fresh Compose contracts. The local fresh stack passes **21/21 contracts plus 1/1 restart restoration**,
with no GPU, .env or prior volumes. Its [long-browser case](contracts.json) retains
a fact after 158,911 visible-text characters; the old ceiling was 120,000.
The [adapter contracts](adapter-contracts-final.json) retain native image blocks
and show 952 compact bytes versus 1,056 equivalently pretty bytes for eight
fixture rows (9.85% smaller for that fixture). Native AMD64/ARM64 CI
and authenticated public endpoint checks gate promotion. Published evidence
identifies those runs separately so a local pass is not presented as native or
production certification.

[Core baseline advisories](vulnerabilities-core-baseline.json) · [Core candidate scan](vulnerabilities-core-candidate.json) · [Adapter baseline](vulnerabilities-adapters-baseline.json) · [Adapter candidate](vulnerabilities-adapters-candidate.json)

Upstream references: [curl_cffi 0.17](https://github.com/lexiforest/curl_cffi/releases/tag/v0.17.0), [PyMuPDF 2](https://pymupdf.io/blog/pymupdf-2-0), [dateutil releases](https://github.com/dateutil/dateutil/releases), [dateutil PyPI provenance](https://pypi.org/integrity/python-dateutil/4.0.0/python_dateutil-4.0.0-py3-none-any.whl/provenance).
