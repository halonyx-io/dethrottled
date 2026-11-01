# Dethrottled

Dethrottled gives agents one interface for web discovery, source reading and
browser interaction. It returns traceable evidence and concrete continuation
steps, rather than writing an answer on the agent's behalf.

The default search and reading stack is self-hosted and keyless. There are no
purchased search quotas or required model APIs. Public websites can still block
requests, and local queues, timeouts and storage limits apply. Optional metered
discovery providers are available only when an operator configures keys and a
caller explicitly selects them.

## What agents can do

- Discover sources through web, news and academic search, or a bounded site crawl.
- Read pages, documents, tables, archives, captions and direct media files.
- Continue retained documents by question, text offset, PDF page or table row.
- Inspect source structure and retained source pixels where available.
- Operate a headed browser: navigate, use controls, inspect frames and popups,
  read application responses, collect downloads and restore checkpoints.
- Assemble research evidence with source references and explicit coverage gaps.

Recovery escalates from direct HTTP through TLS, rendering and the headed
browser when appropriate. Challenges and script-only shells can trigger browser
recovery automatically. A failed or partial read remains visible in the result;
HTTP 200 and extracted text alone do not establish answer accuracy.

## Run locally

```sh
cp .env.example .env
docker compose up -d --build
curl -fsS http://127.0.0.1:8787/health
curl -fsS http://127.0.0.1:8787/v2/capabilities
```

Base Compose runs the API, headed browser worker, SearXNG and Crawl4AI. The API
binds to `127.0.0.1:8787` and has no caller authentication. Use the optional
[public adapters](docs/PUBLIC-ACCESS.md) and an authenticated TLS deployment for
remote clients. Speech, PDF layout and MSG/XLSB parsing have optional local
workers; see [configuration](docs/CONFIGURATION.md).

```sh
curl -sS http://127.0.0.1:8787/fetch \
  -H 'Content-Type: application/json' \
  -d '{"urls":["https://docs.python.org/3/library/sqlite3.html"],"focus":"in-memory database"}'
```

An agent should inspect `quality`, `warnings`, `source_partial`, `truncated`,
`document_id` and `workflow.next_actions`. The [agent guide](docs/AGENT-UPGRADES.md)
explains the workflow and what an MCP client must forward to its model.

## Documentation

Start at the [documentation home](docs/README.md).

| Page | Use it for |
|---|---|
| [Agent integration](docs/AGENT-UPGRADES.md) | Autonomous workflow, tool selection and client contracts |
| [Reading and evidence](docs/DEPENDABLE-WORKFLOWS.md) | Formats, OCR, tables, media, citations and resumable jobs |
| [HTTP API](docs/API.md) | Routes, examples, response semantics and generated request reference |
| [Browser operation](docs/DRIVE.md) | Actions, sessions, scope, checkpoints, screenshots and downloads |
| [Configuration](docs/CONFIGURATION.md) | Base stack, optional workers, models and workload controls |
| [Operations](docs/OPERATIONS.md) | Build, verification, backups, updates and remote deployment |
| [Architecture](docs/PIPELINE.md) | Search/read/research paths, corpus models and service boundaries |
| [Evidence and limits](docs/EVIDENCE.md) | Dated measurements, raw results and unresolved failures |

## Deployment and limits

The API image includes document libraries, Tesseract and MiniLM/E5 corpus
models. Mutable evidence, jobs, cache and corpus live in a named data volume;
browser checkpoints use a separate volume. Source installs require Python 3.10+
and explicitly installed optional dependencies and services.

Dethrottled does not guarantee access to every website or file. OCR and speech
can be wrong, scans and charts may require visual inspection, and interactive
challenges may remain unresolved. The latest recovery evaluation fixed software
WebGL and demonstrated better controlled JavaScript recovery; its four hostile
live sources remained unreadable. See the [recorded evidence](docs/EVIDENCE.md)
for methods and limits. Neural live-web reranking remains disabled.

The fetch ladder does not consult `robots.txt`. The raw API can access trusted
LAN targets; public adapters enforce a narrower policy, which is not a substitute
for deployment-level network isolation.

This branch documents package **0.9.1**. Check `/health` and `/v2/capabilities`
on the installation you use; a repository branch or remote plugin may differ
from the deployed service. Historical reports describe their recorded versions.

## License

[MIT](LICENSE). Maintained by [Halonyx](https://github.com/halonyx-io).
