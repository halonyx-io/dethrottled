# Dethrottled

**Keyless web search, stateful browser operation, fetch, and document
extraction for agents and local tooling.** No paid API keys, metered tiers, or
purchased provider quotas. Agents can discover pages, read them cheaply, or
operate a real browser through one local API. No language model writes answers;
results stay traceable to their sources.

- **Keyless.** No paid search API, no per-query cost, no account.
- **Local-first.** Runs as a single container. The Compose project adds a
  private browser search worker, SearXNG, and a local JavaScript renderer.
- **Agent-operable browser.** `/drive` provides persistent sessions (including
  a returned `auto-*` session when navigation omits a name), structured
  DOM snapshots, bounded interactions, execution canaries, and event telemetry
  without requiring agents to launch Chromium or interpret every screenshot.
- **Self-contained.** The API image bakes in its Python dependencies,
  Tesseract, ONNX Runtime, and the one MiniLM corpus model it uses.
- **Evidence, not prose.** `/research` returns a cited source bundle you can
  read and verify; nothing is summarised by a model.

## Quick start

```sh
cp .env.example .env
docker compose up -d --build
curl http://127.0.0.1:8787/health
curl http://127.0.0.1:8787/v2/capabilities
```

The default host bind is `127.0.0.1:8787`. The local API has **no caller
authentication**; put an authenticated gateway in front of it if you expose it
beyond a trusted host. Mutable cache and corpus state live in the
`dethrottled-data` volume.

### First requests

```sh
curl -sS http://127.0.0.1:8787/search \
  -H 'content-type: application/json' \
  -d '{"query":"Python 3.12 documentation","limit":3}'

curl -sS http://127.0.0.1:8787/fetch \
  -H 'content-type: application/json' \
  -d '{"urls":["https://example.com/"]}'

curl -sS http://127.0.0.1:8787/research \
  -H 'content-type: application/json' \
  -d '{"question":"What changed in Python 3.12?","max_sources":4}'

curl -sS http://127.0.0.1:8787/drive \
  -H 'content-type: application/json' \
  -d '{"url":"https://example.com/","screenshot":"never","steps":[{"action":"snapshot"}]}'
```

## What it does

| Verb | Endpoint | Purpose |
| --- | --- | --- |
| Search | `POST /search` | Discover URLs; no page bodies fetched |
| Fetch | `POST /fetch` (alias `/extract`) | Read named URLs and extract content |
| Links | `POST /extract-with-links` | Fetch with outbound links kept |
| Search + read | `POST /search-and-fetch` (alias `/search-and-extract`) | Rank, then read the kept results |
| Research | `POST /research` | A cited, diverse evidence bundle — no model answer |
| Browser drive | `POST /drive` | Bounded, optionally stateful browser actions with DOM and event telemetry |
| Corpus | `GET /corpus/search`, `GET /corpus/stats` | Local semantic index of everything fetched |
| Status | `GET /health`, `/ready`, `/v2/status`, `/v2/capabilities`, `/stats` | Liveness and real configuration |

`/search` finds; `/fetch` reads; `/drive` operates; `/research` assembles
evidence. A search that finds nothing returns `[]`, and a failed fetch is a row with
`quality: "failed"` — HTTP 200 alone does not prove a useful result.

**Reading:** HTML, CSV/TSV, PDF (with OCR for scans), XLS/XLSX, DOCX, PPTX,
ODT/ODS/ODP, EPUB, and RTF.

**Fetch tiers:** a local escalation ladder — direct HTTP → TLS → a
containerised JavaScript renderer (Crawl4AI) — so a page is only rendered when
the cheaper tiers cannot read it.

## Measured performance

On 4 October 2026 we ran the same 50 English queries through native x86_64
and ARM64 builds. szbox is an AMD Ryzen 7 5800U (8 cores / 16 threads,
30 GiB usable RAM); q6a is a Radxa Dragon Q6A (4 Cortex-A55 + 4 Cortex-A78
cores, 11 GiB usable RAM). Both builds used the same source commit and Python
package set. These are client-observed medians with normal services running,
not latency guarantees for the public web.

| Workload | szbox useful; median | q6a useful; median |
| --- | ---: | ---: |
| `/search`, 50 queries | 50/50; **1.43 s** | 50/50; **2.66 s** |
| `/search-and-fetch`, 50 queries | 47/50; **3.60 s** | 47/50; **5.56 s** |
| `/fetch`, the same 50 fixed URLs | 42/50; **0.51 s** | 42/50; **0.73 s** |
| `/research`, eight evidence bundles | 8/8; **7.54 s** | 7/8; **9.26 s** |

A useful fetched page had `quality: ok` and at least 600 extracted characters;
HTTP 200 alone did not pass. With eight concurrent search callers, szbox
returned 50/50 useful results at 1.48 queries/s, while q6a returned 48/50
at 0.71 queries/s. Controlled document fixtures passed 39/39 expected
outcomes on each host. The browser search worker was the main search CPU
consumer; the [full report](docs/BENCHMARKS.md) has p95 latency, individual
failures, per-component CPU/RAM samples, methods, and raw results.

The report and raw JSON are also copied into the API image at
`/app/docs/BENCHMARKS.md` and `/app/docs/benchmarks/2026-10-04/`.

## Documentation

| Guide | What it covers |
| --- | --- |
| [Features](docs/FEATURES.md) | Every current feature and the shortest way to use it |
| [HTTP API](docs/API.md) | All local endpoints, fields, response shapes, examples |
| [Browser drive](docs/DRIVE.md) | Efficient agent workflow, sessions, actions, canaries, and safety boundaries |
| [Python API](docs/PYTHON.md) | Direct imports, source-install extras, and examples |
| [Pipeline](docs/PIPELINE.md) | Search, rendering, extraction, ranking, research, corpus |
| [Configuration](docs/CONFIGURATION.md) | Compose settings and local performance choices |
| [Operations](docs/OPERATIONS.md) | Verification, backups, upgrades, network exposure |
| [PDF worker](docs/PDF_WORKER.md) | Optional HTML-to-PDF service |
| [Benchmarks](docs/BENCHMARKS.md) | Paired x86_64/ARM64 endpoint, quality, and resource measurements |

## Architecture

```
client ──▶ dethrottled API (:8787) ──▶ search engines (keyless)
                    │                  ├─ private browser-search worker
                    │                  ├─ SearXNG (news)
                    │                  └─ news RSS
                    ├─▶ fetch ladder ──▶ direct ▸ tls ▸ crawl4ai (JS render)
                    ├─▶ extraction ───▶ trafilatura ▸ resiliparse ▸ selectolax
                    ├─▶ /drive ───────▶ isolated Patchright browser sessions
                    └─▶ corpus (SQLite + ONNX MiniLM embeddings)
```

The API is a single FastAPI service. The Compose project runs it alongside the
browser-search worker, SearXNG, Crawl4AI, and an optional HTML-to-PDF worker,
all on a private bridge network. The API is published to host loopback by
default; the optional PDF worker publishes host port 8788 as currently
configured. The browser-search, SearXNG, and Crawl4AI services remain private.

## Requirements

- Docker with Compose v2 for the full stack, **or** Python 3.10+ for the API alone.
- No external API keys. The default engine set is keyless.

This repository provides the raw HTTP API. A public REST gateway or MCP bridge
can build on it, but public bearer tokens and MCP tool schemas belong to that
separate deployment; they are not implemented by this Compose project.

## Notes

- The fetch ladder does not request or honour `robots.txt`. It uses no paid API
  keys or metered search tier. Local timeouts, queues, render budgets, and
  per-domain pacing still apply — see the configuration guide.
- The Compose services set no CPU affinity, CPU quota, or overall RAM cap; they
  size themselves to the host.

## License

MIT — see [LICENSE](LICENSE).

Maintained by [Halonyx](https://github.com/halonyx-io).
