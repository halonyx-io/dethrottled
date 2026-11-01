# Configuration and local tuning

## Compose versus a source install

For the portable stack, copy `.env.example` to `.env` and run Docker Compose.
The `.env` file is ignored by git. Compose uses it for **interpolation**: a
variable written there reaches a container only where `docker-compose.yml` or
an enabled overlay maps it into `environment:`. The image's built-in defaults
apply otherwise. Check the effective setup with `docker compose config`.

For a source install, `pip install '.[all]'` installs the Python features but
does not start SearXNG, the browser-search worker, or Crawl4AI. Run
`./scripts/fetch-models.sh` for MiniLM; add `--multilingual` for E5 and set the
revision/environment variables printed by the script. Set any
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
| `DETHROTTLED_EXTRACT_CACHE_CHARS` | `1000000` | Characters kept in extraction cache |
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
| `DETHROTTLED_CRAWL4AI_BUDGET` | `-1` | No hourly local quota; `0` disables, positive caps/window |
| `DETHROTTLED_RENDER_CONCURRENCY` | `2` | Active local renders per API process |
| `DETHROTTLED_RENDER_MAX_WAITING` | `32` | Total queued renders |
| `DETHROTTLED_RENDER_PER_CLIENT` | `8` | Waiting renders per evidence namespace |
| `DETHROTTLED_RENDER_QUEUE_SECONDS` | `60` | Maximum admission wait |
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

## October 31 controls

`DETHROTTLED_CHEAP_DISCOVERY=1` enables the bounded static DDG Lite probe
before the existing browser race (Compose default; standalone code default 0).
Set 0 if challenges make its extra latency undesirable. No new service or
model is needed. The browser worker owns pacing for both paths.

Public-adapter settings and shared token/admission storage are documented in
[PUBLIC-ACCESS.md](PUBLIC-ACCESS.md). These do not add authentication to the
raw internal API.

The 0.4 image adds antiword/catppt and Malay, simplified-Chinese and traditional-
Chinese Tesseract data. Select OCR language explicitly when known. No new model
service is needed. Document and job SQLite stores live under the data directory;
back them up along with cache/corpus if retaining agent work matters. See API.md
for TTLs, capacity eviction, job recovery and PDF/embedded-image caps.

`DETHROTTLED_DOC_MAX_ROWS` defaults to 2000 per table window; larger exports
can be read with successive row ranges. `DETHROTTLED_DOC_MAX_CELL` now defaults
to 32767, with an explicit per-request max_cell_chars override and truncation
metadata. Empty/covered OpenDocument cells retain their column positions;
repeated cells/rows are expanded within the extraction budget.

## Optional layout and discovery services (0.7)

`DETHROTTLED_LAYOUT_WORKER_URL` enables the private Docling PDF worker. Build
and start the `layout` profile with `docker-compose.agents.yml`; model weights
persist in `layout-models`. Native table detection works without this worker.

`DETHROTTLED_EXA_API_KEY`, `DETHROTTLED_TAVILY_API_KEY` and
`DETHROTTLED_PARALLEL_API_KEY` configure optional external discovery providers.
Keys stay server-side; callers must explicitly select providers through `engines`.
Default profiles remain keyless. See [setup and resource limits](DEPENDABLE-WORKFLOWS.md).

## Measured worker additions (0.8)

The API image now includes pinned multilingual E5-small weights alongside MiniLM.
Compose enables `DETHROTTLED_MULTILINGUAL_CORPUS=1`; library users opt in with that
variable. Set it to `0` for the original index alone. E5 uses a separate versioned
index, query/passage prefixes and `DETHROTTLED_E5_FLOOR=0.77`; the English floor
continues to apply only to MiniLM. The E5 floor is calibrated on a small fixture,
not a universal relevance guarantee. `DETHROTTLED_EMBED_THREADS` defaults to 4.
A supervised child backfills missing URLs from retained passages without
refetching source URLs;
`/v2/status.multilingual_backfill` reports completion or a typed failure. Shutdown kills/reaps the child; restart resumes committed progress. Old vectors
remain usable when disabling E5. Allow extra disk and RAM for weights and vectors.

For MSG/XLSB, enable `--profile formats` with `docker-compose.agents.yml` and set
`DETHROTTLED_FORMAT_WORKER_URL=http://format-worker:19892`. This private Tika 3.3.3
worker receives bytes, never caller URLs. It has a 50 MiB input limit, 60-second
wall deadline, 1 GiB Java heap, 2 GiB container limit and single active conversion.
Only the two measured formats are routed to it. An arbitrary-format capability
is not advertised. Attachment completeness and physical spreadsheet cells remain
unverified; preserve the extraction warnings.

Speech, layout and format workers expose `/health`, `/ready`, `/metrics` internally.
Readiness checks cached model assets; the first speech/layout conversion may need
to download weights. `/v2/status.workers` probes the configured workers with a
10-second cache. Cancellation/disconnect/deadline kills the child process group
before releasing admission. This reloads speech weights per job and can increase
latency. Layout automatically tries OCR on scanned PDF tables; explicit OCR and
native-mode choices are respected. Read `MEASURED-IMPROVEMENTS.md` for evidence.

## Automatic challenge recovery (0.9)

When a read observes a supported challenge signal, it tries the configured headed
browser after the cheaper tiers. No solver service, model API or new key is used.
`render=never` and the fast profile still prohibit browser escalation.
`headed_fallback=true` additionally requests this tier for other acquisition failures.
A detected challenge is permitted one headed attempt after the ordinary soft page
budget; `DETHROTTLED_CHALLENGE_WAIT_SECONDS` defaults to 15 for its polling deadline.
Individual navigation/HTTP requests retain their own timeouts. A challenge that
persists is reported unresolved; it is never counted as article content.

Sessions use `auto-reader-<hash>` identities scoped to the evidence namespace,
exact host and public-target policy. Existing session limits, expiry and eviction
apply. Successful reads checkpoint browser state, and resumed reads can restore
it. Cookies remain inside that browser identity; they are not exported to curl or
shared across callers. Public subframes may load for challenge execution; top-level
and popup scope and private-network restrictions remain in force.

`quality=thin` preserves a short HTML result and its warnings without claiming
normal coverage. Short successfully parsed structured documents remain valid.
`acquisition_attempts` lists actual tiers, reasons and outcomes, including residual
challenges. A skipped tier is not reported as attempted. The workflow recommends
native browser pixels for an unresolved challenge and avoids blindly repeating the
already-attempted acquisition ladder.

MCP tool argument schemas now reject unknown fields. Use `categories`, not
`category`, and `format=html`/`format=links`; `raw`/`links` remain REST aliases.
The backend body models already reject unknown fields. A client that silently
removes fields before sending them cannot be diagnosed by server-side validation;
refresh/read its actual tool schema after upgrading.

Public admission and research/gateway 429 responses identify the limiter. Rate
window retry hints round up to the next boundary; busy hints are polling advice,
not a claim that an active operation or crashed lease expires at that instant.
