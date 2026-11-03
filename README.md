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
  [Navigation recovery](https://github.com/halonyx-io/dethrottled/blob/main/docs/DRIVE.md#navigation-recovery-and-access-evidence) also
  applies when the reading ladder reaches the browser.
- Assemble research evidence with source references and explicit coverage gaps.

Recovery escalates from direct HTTP through TLS, rendering and the headed
browser when appropriate. Challenges and script-only shells can trigger browser
recovery automatically. A failed or partial read remains visible in the result;
HTTP 200 and extracted text alone do not establish answer accuracy.

## Run locally

```sh
docker compose up -d --build
curl -fsS http://127.0.0.1:8787/health
curl -fsS http://127.0.0.1:8787/v2/capabilities
```

Base Compose runs the API, headed browser worker, SearXNG, Crawl4AI and MSG/XLSB reader. The API
binds to `127.0.0.1:8787` and has no caller authentication. Use the optional
[public adapters](https://github.com/halonyx-io/dethrottled/blob/main/docs/PUBLIC-ACCESS.md) and an authenticated TLS deployment for
remote clients. Speech and PDF layout have optional local
workers; see [configuration](https://github.com/halonyx-io/dethrottled/blob/main/docs/CONFIGURATION.md).

```sh
curl -sS http://127.0.0.1:8787/fetch \
  -H 'Content-Type: application/json' \
  -d '{"urls":["https://docs.python.org/3/library/sqlite3.html"],"focus":"in-memory database"}'
```

Ordinary reads run an [observed-gap recovery loop](https://github.com/halonyx-io/dethrottled/blob/main/docs/READ-PLANNER.md): acquire,
inspect, select a justified publisher or browser strategy, then reassess. The loop
can discover primary representations, scroll lazy content, open standard details
and read observed primary JSON responses. It preserves partial evidence and records
why recovery stopped. Optional GPU setup is described in the same guide.

An agent should inspect `quality`, `warnings`, `read_plan`, `source_partial`, `truncated`,
`document_id` and `workflow.next_actions`. The [agent guide](https://github.com/halonyx-io/dethrottled/blob/main/docs/AGENT-UPGRADES.md)
explains the workflow and what an MCP client must forward to its model.
[Coverage limits](https://github.com/halonyx-io/dethrottled/blob/main/docs/LIMITS.md)
keep discovery compact: ten DDG choices, at most three per supplementary engine,
up to six supplements and fifteen unique choices total. Yahoo and Yandex supplement
DDG by default, preserving its order. Research reads ten sources by default, allows
twenty on request and admits at most twenty-four unique candidates across facets.
Million-character document reads remain available.

## Documentation

Start at the [documentation home](https://github.com/halonyx-io/dethrottled/blob/main/docs/README.md). The
[1.0 release gates](https://github.com/halonyx-io/dethrottled/blob/main/docs/ONE-ZERO.md) describe measured capabilities and limits.

| Page | Use it for |
|---|---|
| [Agent integration](https://github.com/halonyx-io/dethrottled/blob/main/docs/AGENT-UPGRADES.md) | Autonomous workflow, tool selection and client contracts |
| [Reading and evidence](https://github.com/halonyx-io/dethrottled/blob/main/docs/DEPENDABLE-WORKFLOWS.md) | Formats, OCR, tables, media, citations and resumable jobs |
| [HTTP API](https://github.com/halonyx-io/dethrottled/blob/main/docs/API.md) | Routes, examples, response semantics and generated request reference |
| [Browser operation](https://github.com/halonyx-io/dethrottled/blob/main/docs/DRIVE.md) | Actions, sessions, scope, checkpoints, screenshots and downloads |
| [Configuration](https://github.com/halonyx-io/dethrottled/blob/main/docs/CONFIGURATION.md) | Base stack, optional workers, models and workload controls |
| [Operations](https://github.com/halonyx-io/dethrottled/blob/main/docs/OPERATIONS.md) | Build, verification, backups, updates and remote deployment |
| [Architecture](https://github.com/halonyx-io/dethrottled/blob/main/docs/PIPELINE.md) | Search/read/research paths, corpus models and service boundaries |
| [Evidence and limits](https://github.com/halonyx-io/dethrottled/blob/main/docs/EVIDENCE.md) | Dated measurements, raw results and unresolved failures |

## Deployment and limits

Default Compose also starts the MSG/XLSB reader. Speech/layout are selected with
`--profile full` (or individually with `media`/`layout`) and connect automatically.
No `.env` file, worker URL or GPU is required for the default stack.

The API image includes document libraries, Tesseract and MiniLM/E5 corpus
models. Mutable evidence, jobs, cache and corpus live in a named data volume;
browser checkpoints use a separate volume. Source installs require Python 3.10+
and explicitly installed optional dependencies and services.

Dethrottled does not guarantee access to every website or file. OCR and speech
can be wrong, scans and charts may require visual inspection, and interactive
challenges may remain unresolved. The 1.0 evaluation recovered predefined Reddit thread facts and exercised native
controls in three fresh sessions each on software and GPU rendering. Crunchbase
and G2 remained blocked; CarGurus yielded no usable text. See the [recorded evidence](https://github.com/halonyx-io/dethrottled/blob/main/docs/EVIDENCE.md)
for methods and limits. Neural live-web reranking remains disabled.

The fetch ladder does not consult `robots.txt`. The raw API can access trusted
LAN targets; public adapters enforce a narrower policy, which is not a substitute
for deployment-level network isolation.

This checkout is **1.2.0**. Check `/health` and `/v2/capabilities`
on the installation you use; a repository branch or remote plugin may differ
from the deployed service. Historical reports describe their recorded versions.

## License

[MIT](https://github.com/halonyx-io/dethrottled/blob/main/LICENSE). Maintained by [Halonyx](https://github.com/halonyx-io).
