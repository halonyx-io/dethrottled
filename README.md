<p align="center">
  <img src="https://raw.githubusercontent.com/halonyx-io/dethrottled/main/docs/assets/hero.svg" alt="dethrottled: self-hosted web access for AI agents. Search, read, drive a browser and keep the evidence, with no API keys." width="100%">
</p>

<p align="center">
  <a href="https://pypi.org/project/dethrottled/"><img src="https://img.shields.io/pypi/v/dethrottled?color=22d3ee&amp;label=PyPI" alt="PyPI version"></a>
  <a href="https://github.com/halonyx-io/dethrottled/actions/workflows/ci.yml"><img src="https://github.com/halonyx-io/dethrottled/actions/workflows/ci.yml/badge.svg" alt="CI status"></a>
  <img src="https://img.shields.io/badge/API%20keys-none-22d3ee" alt="No API keys required">
  <img src="https://img.shields.io/badge/runs%20on-AMD64%20%7C%20ARM64-334155" alt="Runs on AMD64 and ARM64">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-334155" alt="MIT license"></a>
</p>

# dethrottled

**Self-hosted web access for AI agents. No API keys, no quotas, no per-call bill.**

Your agent needs the web. dethrottled searches it, reads what it finds (pages,
PDFs, spreadsheets, slide decks, scanned images, audio and video), drives a
real browser when a site insists on one, and keeps the evidence so the next
question starts where the last one stopped. It runs in Docker on your own
hardware.

It is also honest about what it got. Every result carries its quality, its
warnings, how complete it is and where it came from, plus the concrete next step
when something is missing. Your agent can tell a full article from a cookie wall.

## Why dethrottled

- **Keyless by default.** Search, rendering, OCR, speech, embeddings and
  reranking all run locally. Paid providers exist only as explicit opt-ins.
- **Reads the pages simple scrapers can't.** Each read starts with a plain request
  and climbs to TLS impersonation, a JavaScript renderer and finally a real
  browser, only as far as the page needs.
- **Results you can trust to be honest.** `quality`, `warnings`, partial and
  truncated flags, attempt history and source hashes travel with the text. A
  failed or thin read is reported as one, never dressed up as a success.
- **Built for agents.** An MCP server and REST gateway with per-client tokens and
  scopes, an installable agent skill, and responses sized for context windows:
  focused excerpts, token estimates and continuation handles.
- **It remembers.** Long documents are retained for follow-up reads, and public
  evidence goes into a local searchable corpus for 90 days.

## Quick start

You need Docker Engine with Compose.

```sh
git clone https://github.com/halonyx-io/dethrottled.git
cd dethrottled
docker compose up -d --build --wait
curl -fsS http://127.0.0.1:8787/health
```

The first build downloads browser, OCR and model assets, so it takes a while.
After that, search:

```sh
curl -sS http://127.0.0.1:8787/v2/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"sqlite write-ahead logging","limit":5}'
```

and read a page, keeping only the passages about one topic:

```sh
curl -sS http://127.0.0.1:8787/fetch \
  -H 'Content-Type: application/json' \
  -d '{"urls":["https://sqlite.org/wal.html"],"focus":"checkpoint","max_chars":600}'
```

Prefer not to clone? With Python 3.10+ and Docker:

```sh
python3 -m venv .venv && . .venv/bin/activate
python -m pip install dethrottled
dethrottled stack up
dethrottled stack status
```

> [!IMPORTANT]
> The raw API on `127.0.0.1:8787` has no authentication and is meant for the
> same machine. To serve other devices or a hosted agent, put the
> [authenticated REST and MCP adapters](docs/PUBLIC-ACCESS.md) in front of it.

## What it does

### Search

One query fans out to DuckDuckGo plus supplementary engines through a bundled
SearXNG, and comes back as a compact menu of at most fifteen unique sources.
Profiles cover `web`, `news`, `academic` (Crossref, OpenAlex, arXiv) and a
`thorough` mode. The same page reached under different addresses is merged into
one result that keeps everyone's dates and provenance. A local Ettin reranker
refines the order, and you can restrict, exclude or prefer domains.

### Read almost anything

<p align="center">
  <img src="https://raw.githubusercontent.com/halonyx-io/dethrottled/main/docs/assets/escalation.svg" alt="A read climbs from plain HTTP to TLS impersonation, a JavaScript renderer and a real browser, assessing the result after every step and returning evidence with its quality, warnings and next steps." width="100%">
</p>

After every attempt the result is assessed. Is there readable text? Is this an
app shell waiting for JavaScript, a challenge page, an error banner or a teaser?
The read only climbs when it has to. When a page needs more than rendering, a
read planner tries the fix it observed: scrolling a feed, expanding collapsed
sections, waiting out a loading state, or following the publisher's own
alternative format.

The same `fetch` call reads:

| Source | What you get |
|---|---|
| Web pages | Main text with title, publisher-declared dates and identifiers (DOI, ISBN, package versions) |
| PDF | Text layer, detected tables, page ranges and Tesseract OCR for scans; optional Docling layout analysis |
| Office and OpenDocument | DOCX, PPTX, XLSX, XLS, ODT, ODS, ODP, EPUB, RTF, legacy DOC/PPT, MSG and XLSB |
| Data and text | CSV and TSV row windows, JSON, XML, Markdown, plain text |
| Archives and email | ZIP, TAR and GZIP members; EML messages and attachments |
| Media | Captions and subtitles, image OCR, and speech-to-text for audio and video with the optional speech worker |

### Drive a real browser

When reading isn't enough, `/drive` hands your agent a real Chromium session:
snapshot the page's controls, click, fill and submit forms, switch tabs and
frames, capture network responses, download files and take screenshots. Sessions
persist across calls, survive worker restarts through checkpoints, and stay
inside the hosts you allow.

```sh
curl -sS http://127.0.0.1:8787/drive \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/","session":"demo","allowed_hosts":["example.com"],"steps":[{"action":"snapshot","limit":10}]}'
```

### Research in one call

`/research` takes a question, searches several angles, reads the most promising
sources in parallel and returns an evidence bundle: source excerpts matched to
your question, with the gaps it could not cover. Mirrors and duplicate copies are
collapsed so the bundle contains distinct sources. No model writes an answer;
your agent does that with the evidence in hand.

```sh
curl -sS http://127.0.0.1:8787/research \
  -H 'Content-Type: application/json' \
  -d '{"question":"How does Python sqlite3 create an in-memory database?","max_sources":4}'
```

### Keep and reuse evidence

- **Retained documents.** Every read gets a `document_id`. Page through a long
  PDF, jump to a table's rows or, where supported, view the source page as an
  image, all without fetching it again.
- **A shared corpus.** Public reads are indexed in the background, lexically and
  with local MiniLM/E5 embeddings, and kept for 90 days. `corpus_search` finds
  passages across everything read before, in any language the models cover.

### And more

- **Bulk jobs.** [DPR](docs/DPR.md) takes up to 500 URLs per job from a CSV or
  text file, survives restarts and exports JSONL, CSV or extracted files.
- **Site mapping and crawling.** Read a sitemap or follow links within one
  site, with explicit page and path bounds.
- **Field extraction.** Named CSS selectors pull exact values out of a page
  without a model.
- **Ad and tracker blocking.** [HaGeZi Multi PRO](docs/ADBLOCK.md) filtering is
  on by default across every fetcher and browser.
- **Guided Setup.** [Guided Setup](docs/GUIDED-SETUP.md) recommends settings for your machine and
  workload, and saves a plan you can review before applying it.

## What a result looks like

A real `fetch` response, trimmed:

```json
{
  "url": "https://sqlite.org/wal.html",
  "quality": "ok",
  "tier": "direct/trafilatura",
  "content_status": "complete",
  "page_type": "article",
  "published": "2026-08-25",
  "date_source": "page",
  "content": "In its default configuration, SQLite will checkpoint the WAL file at the conclusion of any transaction when the WAL file is more than 1000 pages long...",
  "content_chars": 30118,
  "truncated": true,
  "document_id": "doc_8a903f5c0b48492fb6fcf21d236245fc",
  "warnings": [],
  "tokens_estimated": 150
}
```

`truncated` is true because `focus` returned only the matching passages; the full
30,118-character text is retained under `document_id`. When a read is incomplete,
`workflow.next_actions` names the exact tool call to make next.

## Connect your agent

| You use | Connect with |
|---|---|
| An MCP client (Claude, Codex, Cursor and others) | The [MCP adapter](docs/PUBLIC-ACCESS.md): Streamable HTTP at `/mcp` with a bearer token |
| Your own code | The [HTTP API](docs/API.md), or the [Python package](docs/PYTHON.md) |
| A coding agent that reads skills | The [agent skill](SKILL-dethrottled.md) and the [client playbook](docs/AGENT-PLAYBOOK.md) |
| A shell script | The `dethrottled` CLI and [DPR](docs/DPR.md) for batches |

## Honest limits

- Some sites block automated access whatever the client. Those reads fail, and
  say so.
- Search quality depends on upstream engines, which rate-limit and change.
- "Readable" is not "correct". OCR and speech can misread, and a page can be
  wrong. dethrottled reports evidence; it does not verify claims.
- The fetch ladder does not consult `robots.txt`. You are responsible for how you
  use it. Use the [authenticated adapters](docs/PUBLIC-ACCESS.md) and network
  isolation when anyone else can reach it.

## Documentation

| Start here | For |
|---|---|
| [Quick start](docs/QUICKSTART.md) | Install, first requests, everyday use |
| [Client playbook](docs/AGENT-PLAYBOOK.md) | How agents should call each tool and read each field |
| [HTTP API](docs/API.md) | Routes, examples and the [request reference](docs/HTTP-REFERENCE.md) |
| [Browser operation](docs/DRIVE.md) | Actions, sessions, scope, checkpoints and downloads |
| [Reading and evidence](docs/DEPENDABLE-WORKFLOWS.md) | Formats, OCR, layout, spreadsheets and continuation |
| [Configuration](docs/CONFIGURATION.md) | Workers, profiles, models and tuning |
| [Requirements](docs/REQUIREMENTS.md) | Hardware, memory and disk |
| [Operations](docs/OPERATIONS.md) | Upgrades, backups and releases |
| [All documentation](docs/README.md) | Everything else |

## Contributing

Read [AGENTS.md](AGENTS.md) before changing code. It sets out the rules
contributors (human or AI) follow here, and the checks a change must pass.

This checkout is **1.8.4**. A running service reports its own version at `/health`.

[MIT license](LICENSE) · Maintained by [Halonyx](https://github.com/halonyx-io)
