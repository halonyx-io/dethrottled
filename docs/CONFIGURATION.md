# Configuration

<picture>
  <img src="assets/profiles.svg" alt="Default stack and optional profiles">
</picture>

Base Compose runs five services: API, browser-search, SearXNG, Crawl4AI and the
MSG/XLSB format reader. Optional profiles add local speech and PDF layout.
Authenticated remote adapters are a separate overlay. The API image already contains native readers, Tesseract and
corpus weights; a source install requires explicit dependencies and setup.

## PyPI-managed installation

After `pip install dethrottled`, use `dethrottled stack up` to start the complete
default stack without a Git clone. Docker Engine and Compose are prerequisites.
See [Python installation and worker management](PYTHON.md) for profiles, state
locations and lifecycle commands.

## GitHub base installation

```sh
docker compose up -d --build
```

No `.env` file is required. Copy `.env.example` only to override defaults.
`.env` is Compose interpolation, not an automatic container environment export.
Only names mapped by the selected Compose files reach their services. Other
application settings need an `environment` entry in a local override. Inspect
`docker compose config` locally; its output can contain secrets.

| Interpolated name | Default | Purpose |
|---|---|---|
| `DETHROTTLED_AUTO_WORKERS` | `1` in Compose | Discover started local speech/layout/format workers; explicit URLs or `off` take precedence |
| `DETHROTTLED_BIND`, `DETHROTTLED_PORT` | `127.0.0.1`, `8787` | Host API publication |
| `CRAWL4AI_TOKEN` | `dethrottled-compose-local` | Private renderer credential, not caller authentication |
| `CRAWL4AI_ALLOW_INTERNAL_URLS` | `false` | Renderer access to private addresses |
| `DETHROTTLED_CHEAP_DISCOVERY` | `1` in Compose | Static DDG Lite probe before browser fallback; standalone default 0 |
| `DETHROTTLED_MULTILINGUAL_CORPUS` | `1` in Compose | Enable E5 alongside MiniLM; standalone opt-in |
| `DETHROTTLED_EXTRACT_CACHE_CHARS` | `1000000` | Retained extraction budget |
| `DETHROTTLED_CRAWL4AI_BUDGET` | `-1` | No hourly renderer quota; 0 disables; positive values cap/window |
| `DETHROTTLED_RENDER_CONCURRENCY` | `2` | API-side active renderer work |
| `DETHROTTLED_DRIVE_SESSION_TTL`, `DETHROTTLED_DRIVE_MAX_SESSIONS` | `1800`, `8` | Browser session expiry and capacity |
| `DETHROTTLED_BROWSER_GRAPHICS` | `auto` in Compose | Verify exposed hardware through GL EGL, fall back to software; `mesa` retains GL, `default` retains original args |
| `DETHROTTLED_READ_PLAN_SECONDS` | `30` | Additional recovery admission budget, clamped to 0–120; in-flight operations retain their transport timeout |
| `DETHROTTLED_USER_AGENT` | `dethrottled/1.6.0 (automated fetcher)` | Article-fetch identity |

The base file maps internal worker URLs and optional worker/key variables.
The complete interpolation map is in `docker-compose.yml` and the agents overlay;
this table covers the main controls. Keep mutable data in named volumes. Do not
point the model directory at an empty mounted path that hides the baked weights.

Component settings are not Compose interpolation; set them on the named service
through a local override:

| Name | Default | Applies to |
|---|---|---|
| `DETHROTTLED_CACHE_MAX_BYTES` | `536870912` | API: cache footprint ceiling; oldest rows are evicted past 90% and compacted |
| `DETHROTTLED_CACHE_MAINTENANCE_EVERY` | `200` | API: writes between expiry/size maintenance runs; `0` disables automatic runs |
| `DETHROTTLED_BROWSER_IDLE_SECONDS` | `300` | browser worker: close the separate crawl browser when idle; `0` keeps it warm |
| `DETHROTTLED_MEMORY_PRESSURE` | `1` | browser worker: ask Chrome to release caches after crawl/drive; `0` disables |
| `MCP_TOOL_PROFILE` | `full` | MCP adapter: `core` exposes six high-use tools; `full` exposes all 20 |
| `DETHROTTLED_SEARCH_FANOUT` | `0` | API: one extra intent-aware query variant; extra upstream requests |
| `DETHROTTLED_RERANK` | `0` | API: use a local ONNX cross-encoder when `DETHROTTLED_RERANK_MODEL` is set |
| `DETHROTTLED_RERANK_MODEL` | empty | Directory with an ONNX model, `tokenizer.json` and `config.json`; GTE ModernBERT is the measured quality leader (`scripts/fetch-rerank-model.sh`) and Ettin 68M `onnx/model.onnx` fp32 is the universal-CPU alternative. `model.onnx`, `model_quint8_avx2.onnx` and the other standard quantized names are detected |
| `DETHROTTLED_RERANK_ONNX` | empty | Optional ONNX filename inside `DETHROTTLED_RERANK_MODEL`; use when a directory holds more than one export |
| `DETHROTTLED_RERANK_MAX_TOKENS` | `512` | Tokenizer truncation length, clamped to the model maximum |
| `DETHROTTLED_RERANK_TEXT_CHARS` | `3000` | Title+body characters supplied to the reranker before token truncation |
| `DETHROTTLED_RERANK_DEPTH` | `30` | Only the first N search candidates are reranked |
| `DETHROTTLED_RERANK_THREADS` | `2` | ONNX CPU threads for reranking |
| `DETHROTTLED_SEMANTIC_CACHE` | off | API: `1` or a SQLite path enables the separate paraphrase cache |
| `DETHROTTLED_SEMANTIC_CACHE_THRESHOLD` | `0.55` | MiniLM cosine threshold; tune only with a labelled paraphrase set |
| `DETHROTTLED_SEMANTIC_CACHE_TTL` | `21600` | Seconds before a semantic cache entry is ignored |
| `DETHROTTLED_SEARCH_PROFILE` | off | Browser worker: `1` or a path persists search cookies/localStorage |
| `DETHROTTLED_SEARCH_PROXIES` | empty | Comma-separated provider proxies; round-robin per search call |
| `DETHROTTLED_<PROVIDER>_API_KEYS` | empty | Comma-separated keys for `exa`, `tavily` or `parallel`; legacy single key still works |

## Automatically connected local workers

The format reader starts by default. Speech and layout inference stay optional
because their model downloads and memory requirements differ from ordinary web
reading. Enable either, or both with the `full` profile:

```sh
docker compose --profile full up -d --build
```

Use `--profile media` or `--profile layout` for just one. The API discovers those
fixed service names through Docker DNS; no extra URLs or core restart are needed.
Discovery misses are cached for ten seconds. Capabilities and `/v2/status` reflect
what is present. `DETHROTTLED_AUTO_WORKERS=0` disables discovery. An explicit worker
URL takes precedence; `off` disables one reader even when its service is running.
Source installs do not discover network services unless explicitly enabled.

| Worker | Defaults and prerequisites |
|---|---|
| Media | Faster-Whisper `small`, CPU int8, 3 GiB container cap, one active conversion, 50 MiB input, 30 minutes audio, 570-second supervisor deadline; cached weights in media-models |
| Layout | Docling 2.145.0/CPU PyTorch, 8 GiB/four CPUs, one active conversion, 50 MiB, up to 100 selected pages, 180-second deadline; layout-models volume |
| Formats | Tika 3.3.3 for MSG/XLSB only, 2 GiB/two CPUs, 1 GiB Java heap, 50 MiB, one conversion, 60-second deadline |

Media/layout can need an initial model download. Their `/ready` and `/metrics`
are private; `/v2/status.workers` probes them with a ten-second cache. An unready
worker with `initialization=first_use_download` is waiting for its first model
download; the requested conversion initiates it without a key. Cancellation
or deadline kills and reaps supervised conversion children before releasing
admission. Reloading models per job can increase latency. Optional workers have
resource caps; the base API/browser services have no explicit Compose CPU quota
or overall memory cap. `shm_size` is not a total RAM limit.

`WHISPER_MODEL` and `MEDIA_MAX_SECONDS` are mapped by the media overlay. Larger
speech models need separate memory/quality measurements. The [1.4.0 evaluation](../evaluations/install-showcase/results/2026-11-04/REPORT.md)
exercised both inference workers on AMD64 and ARM64 with fixed fixtures. That
does not certify arbitrary documents, longer audio or every graphics profile.

## Corpus models

MiniLM and E5 are corpus retrievers, not live-web neural rerankers. E5 uses a
separate model-versioned index and reciprocal-rank fusion. MiniLM's floor is
0.22; E5's is 0.77. These are calibrated retrieval cutoffs, not truth scores.
`DETHROTTLED_EMBED_THREADS` defaults to 4. A supervised backfill resumes committed
progress on schema 1; check `/v2/status.multilingual_backfill`. [Corpus v2](CORPUS.md) uses its durable queue instead and exposes it
under `/corpus/stats.index`. Disabling E5 preserves MiniLM. Schema 2 supports
conservative `support=standard` retrieval and warned `support=broad` candidates;
the latter retains useful single-model multilingual matches at a precision cost.

For source installs, use `pip install '.[all]'` and
`./scripts/fetch-models.sh --multilingual`, then set the printed model/revision
variables. Optional extras do not start Docker workers. See [Python](PYTHON.md).

## Application workload controls

These process settings need explicit Compose mappings/overrides when not already
mapped. Change them against recorded coverage and failure cases, not just latency.

| Variable | Default | Meaning |
|---|---|---|
| `DETHROTTLED_BROWSER_RECOVERY` | `auto` | Browser worker: observed host-scoped navigation recipes and bounded readiness; `off` disables them. Forwarded by base Compose. |
| `DETHROTTLED_THIN_CHARS` | `600` | HTML threshold; structured short documents differ |
| `DETHROTTLED_PAGE_BUDGET`, `DETHROTTLED_PAGE_BUDGET_BULK` | `60`, `25` seconds | Soft ladder budgets; a known recovery case can receive a bounded headed attempt afterward |
| `DETHROTTLED_CONNECT_TIMEOUT` | `2` seconds | Direct/TLS connection establishment per attempt/address; does not shorten direct response reads. Resolver time and multiple addresses can exceed this; workers retain their own deadlines. |
| `DETHROTTLED_TLS_TIMEOUT` | `8` seconds | TLS streaming low-speed allowance; its connect allowance is bounded by `DETHROTTLED_CONNECT_TIMEOUT`. |
| `DETHROTTLED_CRAWL4AI_TIMEOUT`, `DETHROTTLED_CRAWL4AI_RENDER_MS` | `25` seconds, `20000` ms | Renderer transport/browser timing |
| `DETHROTTLED_RENDER_MAX_WAITING`, `DETHROTTLED_RENDER_PER_CLIENT` | `32`, `8` | Renderer waiting bounds |
| `DETHROTTLED_RENDER_QUEUE_SECONDS` | `60` | Renderer admission wait |
| `DETHROTTLED_HEADED_QUEUE_SECONDS` | `60` | Headed admission wait; one active, 32 total/eight per caller waiting |
| `DETHROTTLED_CHALLENGE_WAIT_SECONDS` | `15` | Headed polling deadline, separate from queue and request timeouts |
| `DETHROTTLED_MAX_HTML_BYTES`, `DETHROTTLED_PDF_MAX_BYTES`, `DETHROTTLED_DOC_MAX_BYTES` | 10,000,000; 25 MiB; 50 MiB | Input limits |
| `DETHROTTLED_OCR_PAGE_CAP`, `DETHROTTLED_OCR_PAGE_TIMEOUT` | `8`, `30` seconds | OCR work bounds |
| `DETHROTTLED_DOC_MAX_ROWS`, `DETHROTTLED_DOC_MAX_CELL` | `2000`, `32767` | Table window/cell defaults; request overrides remain bounded |
| `DETHROTTLED_CORPUS_MAX_PASSAGES`, `DETHROTTLED_CORPUS_RETENTION_DAYS` | `50000`, `90` | Corpus retention; cache lifetimes unchanged |

Mesa exposes its actual llvmpipe software renderer. It needs no GPU passthrough,
fingerprint injection or unsafe SwiftShader opt-in. Graphics-heavy sites can use
more CPU; select `default` if the compatibility override causes trouble.

## Remote access and external options

Use [public adapters](PUBLIC-ACCESS.md) for remote authentication, namespace and
admission setup. Base Compose does not install a reverse proxy or public TLS.
The [HTML-to-PDF overlay](PDF_WORKER.md) is separate and currently publishes host
port 8788 on all interfaces.

Optional `DETHROTTLED_EXA_API_KEY`, `DETHROTTLED_TAVILY_API_KEY` and
`DETHROTTLED_PARALLEL_API_KEY` stay server-side and require explicit `engines`
selection. Default profiles never spend them. No model API is required for the
standard workflow. The fetch ladder ignores robots.txt but retains local
pacing, deadlines and storage limits.

[Documentation home](README.md) · [Agent guide](AGENT-UPGRADES.md) · [API](API.md) · [Evidence](EVIDENCE.md)

[Corpus v2](CORPUS.md) documents separate harvest, lexical,
semantic, database and matrix budgets, public eligibility, migration and rollback.

## Ad/tracker filtering

`DETHROTTLED_ADBLOCK=1` is the default; `0` disables filtering
and updates across managed workers. See [coverage, diagnostics and limitations](ADBLOCK.md).
