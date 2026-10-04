# Configuration and local tuning

## Compose versus a source install

For the portable stack, copy `.env.example` to `.env` and run Docker Compose.
The `.env` file is ignored by git. Compose uses it for **interpolation**: a
variable written there reaches a container only where `docker-compose.yml` or
an enabled overlay maps it into `environment:`. The image's built-in defaults
apply otherwise. Check the effective setup with `docker compose config`.

For a source install, `pip install '.[all]'` installs the Python features but
does not start SearXNG, the browser-search worker, or Crawl4AI. Run
`./scripts/fetch-models.sh` for the one corpus model. Set any
`DETHROTTLED_*` variables in that process's environment, then start
`dethrottled`. A plain source install can still search through its direct
keyless engines and news feeds; capabilities differ from full Compose.

## Settings wired into the provided Compose files

| `.env` name | Default | Effect |
| --- | --- | --- |
| `DETHROTTLED_BIND` | `127.0.0.1` | Host address publishing API port 8787 |
| `DETHROTTLED_PORT` | `8787` | Host port; container still listens on 8787 |
| `DETHROTTLED_ENABLE_JINA` | `0` | Enable external reader tier if set to `1` |
| `DETHROTTLED_USER_AGENT` | `dethrottled/0.2.0 (automated fetcher)` | Article-fetch User-Agent override |
| `DETHROTTLED_EXTRACT_CACHE_CHARS` | `20000` | Characters kept in extraction cache |
| `CRAWL4AI_TOKEN` | `dethrottled-compose-local` | Private API-to-renderer credential |
| `CRAWL4AI_ALLOW_INTERNAL_URLS` | `false` | Let the renderer visit private/LAN addresses when intentionally needed |
| `COMPOSE_FILE` | Base Compose file | Add the optional PDF worker overlay |

The Compose file sets its internal service URLs, the Crawl4AI API dialect,
and SearXNG's two news engines. The API's data directory is `/data` and its
model directory is baked into the image at `/opt/dethrottled/models`. Do not
point `DETHROTTLED_MODEL_DIR` at `/data/models` unless you actually put weights
there; a volume mount would otherwise hide the image's working model.

The optional PDF worker is enabled with:

```env
COMPOSE_FILE=docker-compose.yml:docker-compose.pdf-worker.yml
```

It publishes `8788` on the host as currently written in its overlay. It is a
different service from the Dethrottled API. Check and change that bind for
your environment before enabling it.

## Useful application controls

These are read by the Python process. For Compose deployments, add the chosen
value to a container `environment:` mapping or to a local Compose overlay;
placing an unreferenced name in `.env` alone will not pass it through.

| Variable | Default | When to change it |
| --- | --- | --- |
| `DETHROTTLED_THIN_CHARS` | `600` | Raise to reject more short HTML, lower for terse sites |
| `DETHROTTLED_PAGE_BUDGET` | `60` seconds | Named fetch total-ladder budget |
| `DETHROTTLED_PAGE_BUDGET_BULK` | `25` seconds | Per-result budget in bulk paths |
| `DETHROTTLED_TLS_TIMEOUT` | `8` seconds | Time allowed for the TLS-fingerprint tier |
| `DETHROTTLED_CRAWL4AI_TIMEOUT` | `25` seconds | API wait for renderer |
| `DETHROTTLED_CRAWL4AI_RENDER_MS` | `20000` ms | Requested browser render time; keep below renderer timeout |
| `DETHROTTLED_CRAWL4AI_BUDGET` | `40` per window | Rolling local-render attempt budget |
| `DETHROTTLED_TIER_BUDGET_WINDOW` | `3600` seconds | Window shared by tier budgets |
| `DETHROTTLED_ENGINE_REST_SECONDS` | `1800` seconds | How long failing search engines rest |
| `DETHROTTLED_ENABLE_TLS` | `1` | Disable TLS tier only for diagnosis |
| `DETHROTTLED_ENABLE_TRANSCRIPTS` | `1` | Disable YouTube caption lookup |
| `DETHROTTLED_MAX_HTML_BYTES` | `10000000` | HTML download ceiling |
| `DETHROTTLED_PDF_MAX_BYTES` | `25 MiB` | PDF download ceiling |
| `DETHROTTLED_DOC_MAX_BYTES` | `50 MiB` | Other document download ceiling |
| `DETHROTTLED_OCR_PAGE_CAP` | `8` | Maximum pages OCR examines |
| `DETHROTTLED_OCR_PAGE_TIMEOUT` | `30` seconds | OCR time per page |
| `DETHROTTLED_CORPUS_FLOOR` | `0.22` | Semantic match floor; measure before changing |
| `DETHROTTLED_CORPUS_MAX_PASSAGES` | `50000` | Corpus passage retention cap |
| `DETHROTTLED_CORPUS_RETENTION_DAYS` | `180` | Corpus age retention |
| `DETHROTTLED_EMBED_THREADS` | `0` | ONNX Runtime chooses host threads; set only to cap it |

This is a practical tuning list, not every internal setting. Search and fetch
source files hold the full set and defaults. `/stats` reports tier usage and
budgets; `/v2/capabilities` reports which optional features are active.

## How to tune without hiding failures

1. Run representative queries with `fresh: true` to avoid measuring a cache
   hit. Record elapsed time, result URLs, `search_attempts`, and fetch
   `quality`/`tier`, not just HTTP status.
2. Change one setting at a time. `render: "never"` is useful for latency
   sensitive reads; `render: "always"` is useful when static HTML hides the
   desired article behind JavaScript.
3. For a thin result, inspect the source and `failure_reason` before lowering
   `DETHROTTLED_THIN_CHARS`; a lower threshold can accept paywall teasers.
4. For corpus changes, compare known-answer queries before changing the floor
   or retention. The bundled MiniLM model is used only for corpus retrieval;
   it does not rerank fresh web results by default.
5. Raise renderer concurrency only with memory and quality measurements. The
   browser-search worker currently has one browser, three active query races,
   and at most three tabs per race. Crawl4AI has its own browser-pool settings
   in `docker/crawl4ai/config.yml`.

Compose sets **no CPU affinity, CPU quota, or overall RAM limit** on its
services. Chromium `shm_size: 1gb` is shared-memory allocation, not an overall
RAM cap. There are still application-level queues, page budgets, timeouts,
per-domain pacing, and the renderer's own pool safeguards. These keep a broken
page or blocked engine from consuming every worker; they are not metered API
limits. The fetch ladder does not consult `robots.txt`.
