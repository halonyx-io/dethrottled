# Local HTTP API

Base URL in the default Compose deployment: `http://127.0.0.1:8787`.
FastAPI also serves `/openapi.json` and `/docs`. These are the **raw local API**
routes, not a promise about which routes a public gateway exposes. The raw API
does not require or check a bearer token.

All POST bodies below are JSON. Unknown body fields are rejected with 422. A
fetch failure normally appears as a row with `quality: "failed"`, not an HTTP
error for the whole batch. A search that finds nothing returns `[]`.

## Route map

| Route | Purpose |
| --- | --- |
| `POST /search` | Discover and order URLs; no page bodies are fetched |
| `POST /fetch` | Read one or more URLs and extract content |
| `POST /extract` | Alias for `/fetch` |
| `POST /extract-with-links` | `/fetch` with links retained |
| `POST /search-and-fetch` | Search, rank, then read selected URLs |
| `POST /search-and-extract` | Alias for `/search-and-fetch` |
| `POST /research` | Collect a cited evidence bundle without generating an answer |
| `GET /corpus/search` | Search locally stored extracted passages |
| `GET /corpus/stats` | Count locally stored corpus material |
| `GET /health` | Process liveness |
| `GET /ready` | Search-source readiness report |
| `GET /v2/status` | Configured components, providers, and profiles |
| `GET /v2/capabilities` | Installed/configured capabilities and read formats |
| `GET /stats` | Cache, tier, budget, and domain-health counters |

## Search

```sh
curl -sS http://127.0.0.1:8787/search \
  -H 'content-type: application/json' \
  -d '{"query":"Python 3.12 documentation","limit":3}'
```

`query` is required. Result count defaults to 8; `limit` takes precedence over
the older `max_items` and `num_results` names. `categories: "news"` interleaves
web and news results. `language` is a SearXNG hint, not a strict filter.
`fresh: true` bypasses the search cache. `rank: true` widens the candidate pool
and applies local BM25 before choosing results. `corpus` requests that many
already-fetched passages for the candidate pool; `0` disables the merge.
`recency` is intended for values from 0 to 1 and influences BM25 ordering
when ranking is on; the current request model does not enforce that range.
`rerank: true` is rejected: no reranker is installed or used.

The accepted `engines` and `profile` fields currently do not select a source or
execution mode. Do not use them as tuning controls.

The response is an array of rows with `url`, `title`, `snippet`,
`publishedDate`, `engine`, `from_corpus`, and related metadata. The **first**
row carries `search_attempts`, `search_elapsed_ms`, and `ranking` telemetry.
If the array is empty, there is no first row carrying telemetry. An HTTP 200
alone does not prove that any engine supplied useful results.

## Fetch and extraction

```sh
curl -sS http://127.0.0.1:8787/fetch \
  -H 'content-type: application/json' \
  -d '{"urls":["https://example.com/"],"format":"text"}'
```

`urls` is an array. `format` is `text` (default), `links`, or `html`.
`max_chars` defaults to 8000. `render` is `auto` (escalate when needed),
`always` (try the renderer first), or `never` (skip rendering). Boolean
`true` and `false` are accepted as older aliases for `always` and `auto`.
`fresh: true` bypasses the extraction cache. Older `raw` and `links` booleans
are accepted; `format` takes precedence when set to `links` or `html`.

Successful rows have `quality: "ok"`, `content`, `content_type`, `tier`,
`cached`, and possibly `title` and `published`. The `tier` value identifies the
fetch and extraction path, such as `direct/trafilatura` or
`crawl4ai/crawl4ai-native`. Failed rows have `quality: "failed"`, empty
`content`, and `failure_reason`. Check these fields; a response status of 200
does not mean every URL was read. Fetch may return a short best-available
result when every tier yields only thin content.

The raw API can request HTTP or HTTPS URLs, including local network URLs. It
does not enforce the public-address filter used by `/research`; an external
gateway must enforce its own target policy before exposing fetch publicly.

The API reads HTML; PDF (with OCR available for scans); XLSX/XLS; CSV/TSV;
DOCX/PPTX; ODT/ODS/ODP; EPUB; and RTF when the relevant dependencies are
installed. The image includes those dependencies. Legacy `.doc` and `.ppt`
are detected but not parsed. CSV/TSV lack a dependable binary signature and
need a URL or content-type hint. YouTube video URLs use available captions;
this does not transcribe audio and a remote block or absent caption is reported
as failure. Check `/v2/capabilities` on the running installation.

## Search and fetch

```sh
curl -sS http://127.0.0.1:8787/search-and-fetch \
  -H 'content-type: application/json' \
  -d '{"query":"Python 3.12 release notes","limit":3,"rank":true}'
```

This accepts search fields plus `render`, `raw`, and `max_chars` (default 3000).
It orders results before reading them and returns an array combining search
metadata with fetch fields. It does not OCR each search hit; use `/fetch` for a
specific scanned document. Page reads use a shared worker pool and preserve
row order in the response.

## Research evidence bundle

```sh
curl -sS http://127.0.0.1:8787/research \
  -H 'content-type: application/json' \
  -d '{"question":"What changed in Python 3.12?","max_sources":4}'
```

`question` is required (3–500 characters). Optional `queries` holds up to
three search facets; the question is searched as well, for at most four total
queries. Without facets, Dethrottled adds an `official source` probe.
`max_sources` is 1–6 (default 6), `max_chars` 500–6000 (default 5000).
`fresh`, `language`, and `categories: "news"` are also accepted.

The response has `question`, per-query `queries` telemetry, `sources`,
`skipped`, and `summary`. Each accepted source gets an `id` such as `S1`, its
URL and extracted content, and up to two `evidence` windows with offsets and
matched terms. It favors diverse hosts, rejects private/local source targets,
and removes near-duplicate content. `summary.model_used` is `false`: no prose
answer or citations are invented by a model. At most two research requests run
at once; excess requests receive HTTP 429. Invalid research input receives
HTTP 422.

## Corpus and diagnostics

```sh
curl -G http://127.0.0.1:8787/corpus/search \
  --data-urlencode 'q=Python 3.12' --data-urlencode 'limit=5'
curl http://127.0.0.1:8787/corpus/stats
curl http://127.0.0.1:8787/stats
```

`/corpus/search` does not fetch the web. Its optional `floor` overrides the
default semantic relevance floor for that call. A successful response has
`ok`, `count`, and `results`; an internal corpus error is reported with
`ok: false` and `reason` in the JSON body. `/health` is liveness; use
`/ready`, `/v2/status`, `/v2/capabilities`, and real queries to judge whether
the configured pipeline is serving useful results.
