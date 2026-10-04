# Dethrottled: replacement documentation draft

These documents describe the implementation in this repository as checked on
2026-10-04. They are kept separate from the older root-level documents until
the replacement set is reviewed. The API's live `/openapi.json` is the schema
reference when code and prose disagree.

## Start here

| Document | Purpose |
| --- | --- |
| [API.md](API.md) | Local HTTP endpoints, request fields, response shapes, examples |
| [PIPELINE.md](PIPELINE.md) | Search, fetch, extraction, ranking, research, and corpus behavior |
| [CONFIGURATION.md](CONFIGURATION.md) | Compose and source installs; settings and tuning choices |
| [OPERATIONS.md](OPERATIONS.md) | Build, verify, monitor, back up, upgrade, and expose safely |

Dethrottled is a keyless web search and reading service. The default Compose
project consists of the API, a private headed Chromium search worker, SearXNG
for configured news engines, and Crawl4AI for JavaScript rendering. An optional
PDF worker is a separate service. Search queries go to public search engines;
fetches go to the URLs requested. The API does not call a language model.

The API image contains one model: `all-MiniLM-L6-v2` in ONNX form, with its
tokenizer. It is used for the local corpus only. There is no reranker, decision
model, llama.cpp server, Engram, or Hypnos dependency. Mutable cache and corpus
data live in the `dethrottled-data` Docker volume.

## Quick start

```sh
cp .env.example .env
docker compose up -d --build
curl http://127.0.0.1:8787/health
curl http://127.0.0.1:8787/v2/capabilities
```

The default host bind is `127.0.0.1:8787`. The HTTP API has **no built-in
authentication**. If you make it reachable beyond a trusted host, put an
authenticated gateway in front of it and constrain what that gateway exposes.
The raw API and its helpers should not be treated as a public service.

This Compose project exposes HTTP, not MCP. A hosted REST gateway and MCP bridge
may use Dethrottled as their backend, but their bearer tokens, public route
allowlist, and MCP tool names are external deployment details. They are not
implemented or configured by this repository. Consult that deployment's
configuration for its exact public contract.

## Older documents retained for review

The existing `README.md`, `USAGE.md`, `ARCHITECTURE.md`, `SECURITY.md`,
`TLDREADME.md`, `CONTRIBUTING.md`, and `docker/pdf-worker/README.md` have not
been replaced or removed. This directory is the proposed replacement set for
product and operator documentation. `CONTRIBUTING.md` and the PDF worker's
specialized README may still be useful after review.
