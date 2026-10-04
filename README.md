# Dethrottled

Keyless web search, fetching, document reading, and local evidence gathering.
Run the API alone or use the Compose project for browser-backed search and
JavaScript rendering. Search queries go to public search engines; fetches go
to requested URLs. No language model writes answers.

## Run the full stack

```sh
cp .env.example .env
docker compose up -d --build
curl http://127.0.0.1:8787/health
curl http://127.0.0.1:8787/v2/capabilities
```

The default host bind is `127.0.0.1:8787`. The local API has **no caller
authentication**; use an authenticated gateway if you expose it beyond a
trusted host. The API image includes all Python dependencies, Tesseract, ONNX
Runtime, and its one MiniLM corpus model. The Compose project also starts a
private headed Chromium search worker, SearXNG, and Crawl4AI. An HTML-to-PDF
worker is optional. Mutable cache and corpus state live in the
`dethrottled-data` volume.

## First requests

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
```

`/search` discovers URLs, `/fetch` reads content, and `/research` returns a
traceable **evidence bundle**, not a generated answer. `/search-and-fetch`
combines discovery and reading. The raw API also serves a local corpus,
diagnostics, and a live `/openapi.json` schema. Check returned result rows:
HTTP 200 by itself does not prove a search found useful results or a fetch
read a page.

## Documentation

| Guide | What it covers |
| --- | --- |
| [Features](docs/FEATURES.md) | Every current feature and the shortest way to use it |
| [HTTP API](docs/API.md) | All local endpoints, fields, response shapes, examples |
| [Python API](docs/PYTHON.md) | Direct imports, source-install extras, and examples |
| [Pipeline](docs/PIPELINE.md) | Search, rendering, extraction, ranking, research, corpus |
| [Configuration](docs/CONFIGURATION.md) | Compose settings and local performance choices |
| [Operations](docs/OPERATIONS.md) | Verification, backups, upgrades, network exposure |
| [PDF worker](docs/PDF_WORKER.md) | Optional HTML-to-PDF service |

This repository provides the raw HTTP API. A public REST gateway or MCP bridge
can use it, but public bearer tokens and MCP tool schemas belong to that
separate deployment; they are not implemented by this Compose project.

The fetch ladder does not request or honor `robots.txt`. It uses no paid API
keys or metered search tier. There are still local timeouts, queues, render
budgets, and per-domain pacing; see the configuration guide. The Compose
services have no CPU affinity, CPU quota, or overall RAM cap.

MIT licensed. Maintained by [@zataraine](https://github.com/zataraine).
