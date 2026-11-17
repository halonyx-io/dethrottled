# Operations

Use the package-managed stack or build all enabled services from one checkout.
Preserve mutable state during updates. Runtime version, image source and agent contract are separate checks;
healthy processes alone do not establish useful web access.

## Package-managed installations

Run these commands in the Python environment used for installation:

```sh
python -m pip install --upgrade dethrottled
dethrottled stack up
dethrottled stack status
```

Repeat the original `--project`, `--port` and `--profile` options when using a
custom installation. `stack up` explicitly rebuilds/recreates the managed
services using the installed package's matching context; upgrading the package
alone does not change running services. `stack down` preserves volumes. Use
[the Python guide](PYTHON.md) for profiles, isolation and state locations.

## Build and verify

For a Git checkout:

```sh
docker compose build dethrottled dnb
docker run --rm --network none dethrottled:local python /app/verify_image.py
docker compose up -d
docker compose ps
curl -fsS http://127.0.0.1:8787/health
curl -fsS http://127.0.0.1:8787/v2/status
curl -fsS http://127.0.0.1:8787/v2/capabilities
```

The Docker image installs the tested Linux/Python 3.12 package versions from
`requirements/docker-py312.txt`; source installs retain their compatibility ranges.
Dependency/model layers precede application source so code-only rebuilds reuse them.
Changing the pins requires the release gates on both native architectures. All six Python Dockerfiles also pin the same multi-architecture base-image
digest. This freezes the base image and declared Python package versions, not
every later apt download, browser asset or build byte. Refresh base digests
and dependency locks deliberately, then rerun native release gates.

The offline verifier checks those versions, dependencies and a real corpus embedding without
host model mounts. `/health` is liveness; `/ready` reports recent real-search observations (cold/stale
is unknown, not down, and polling sends no upstream search probes);
`/v2/status` probes configured workers and backfill. Test actual fresh search,
a known-source fetch and the specific optional worker formats you use. A 200
response can still contain failed reads or no useful search results.

For optional automatic Linux Mesa GPU setup, use `scripts/compose-auto.sh` in place
of `docker compose` for builds and updates. It selects the GPU override only when
host devices exist and supplies numeric groups. Verify `workers.browser.graphics`
in `/v2/status`; mapped devices alone do not establish hardware rendering. See
the [read planner and GPU setup](READ-PLANNER.md).

Speech/layout profiles live in the base file and connect automatically. Use
`docker compose --profile full up -d --build` for both, as described in
[configuration](CONFIGURATION.md). Public adapters
are a separate profile or host-managed deployment.

## Publishing a release

The canonical repository is `halonyx-io/dethrottled`. Prepare a pull request with
matching versions in `pyproject.toml`, `src/dethrottled/__init__.py`, the Compose
user agent and `.env.example`. Update current guides while leaving dated test
records intact. Require all CI checks, including native AMD64/ARM64 fresh-stack
contracts, before merging and tagging `v<version>` at the tested commit.

Publishing a GitHub release triggers `.github/workflows/release.yml`. It checks
the tag against package metadata, builds a wheel and source archive, checks the
rendered metadata, and installs/imports the wheel in a clean environment before
uploading to PyPI. The workflow uses Trusted Publishing, not a stored API token.
Configure the existing PyPI project's GitHub publisher with owner `halonyx-io`,
repository `dethrottled`, workflow `release.yml` and environment `pypi`. A publisher
for an old repository does not authorize this repository. Remove obsolete
publishers after verifying the new one. TestPyPI requires its own publisher.

Verify the release workflow and PyPI version/download hashes after upload; a
GitHub release alone does not prove PyPI publication. Attach the tested wheel,
source archive and SHA256 manifest to the GitHub release. Updating source, a
GitHub release or PyPI never upgrades an already running Docker deployment.

When upgrading from before 1.6.0, rebuild/recreate API and browser images plus SearXNG/Crawl4AI so
all four receive the filtering setting, shared cache volume and integration hooks.
Refresh host-managed MCP adapter code, workflow and version modules together;
its SDK remains pinned to 1.30.0. Verify actual worker filter observations and
public adapter/backend identity after rollout. See [filter operations](ADBLOCK.md).

For 1.6.1, rebuild the API and browser images, then recreate SearXNG/Crawl4AI
so their mounted filter modules reload too. Update the public adapter's shared
access module, MCP source, workflow and version module together; the SDK stays
pinned to 1.30.0. Preserve all data/browser/filter/model volumes. Existing cached
partial PDF extractions are not rewritten: use refresh/bypass to reassess them.
Reconnect MCP clients that cache instructions or tool schemas.

For 1.6.2, rebuild/recreate the API and browser services and refresh the host-managed
MCP source, workflow and application-version modules together. The MCP SDK stays
pinned to 1.30.0; unchanged supplementary/format/model workers need no restart.
MCP fetch/research/document reads now default to concise presentation; request
`response_format="detailed"` explicitly for full PDF text-layer blocks. REST keeps
its detailed default. Retained full text and source completeness are unchanged.
No cache/model/data volume reset is required. Refresh MCP tool descriptions.

For 1.7.0, rebuild/recreate the API and browser services and update the MCP source,
workflow and application version together. This loads host constraints, CSS field
extraction, site mapping and terminal-target handling on every affected transport.
The packaged root SKILL-dethrottled.md and generated references describe the new controls.
Unchanged workers and the pinned MCP SDK need no upgrade. Preserve all volumes.

For 1.7.1, rebuild/recreate the API and refresh the host-managed MCP application
version module so backend identity remains matched. Containerized adapters need
the matching adapter image. The browser runtime and unchanged parsing workers
need no restart. Preserve all volumes; no cache or corpus migration is required.
The default direct/TLS connect allowance is two seconds, independently of
response reading; override `DETHROTTLED_CONNECT_TIMEOUT` for slower networks.
REST still defaults to detailed responses and now warns on large text payloads.
The renamed root `SKILL-dethrottled.md` is included in the package and image.

For 1.8.1, use the base Compose configuration to build the API and DNB. Keep the
same Compose project name when upgrading an existing DNB deployment so that
`dnb-state`, `dethrottled-data` and model volumes remain attached. If the old
deployment supplied host-managed signing keys, preserve the issuer by installing
its private key as `dnb/issuer.pem` in the API data volume before the first start.
The API publishes the matching public key in `dnb-trust`. Keep the previous
deployment configuration and image IDs until the new stack passes smoke checks.

Layout and speech workers use Compose networking. Operators using a host wake
proxy can retain their host-specific worker URL overrides.

For 1.8.2, rebuild the API and DNB with the existing Compose project and enabled
profiles. Rebuild the authenticated adapters together if you use them, and check
that they report a matching backend version. Keep the existing signing keys,
browser state, corpus and model volumes. Compose seeds the Ettin model at startup
and enables it by default. Set `DETHROTTLED_RERANK=0` to opt out. The default
SearXNG engine selection is unchanged.

For 1.8.3, rebuild the API, DNB and authenticated adapters with the existing
Compose project and enabled profiles, and update any operator override that pins
an adapter image tag. Keep all volumes; DPR creates `dpr-jobs.sqlite` in the API
data volume on first use. Ettin now orders only results two and three by default
and the first-stage winner keeps its slot (`DETHROTTLED_RERANK_DEPTH=3`,
`DETHROTTLED_RERANK_KEEP_FIRST=1`). DDG Lite titles and snippets, link text and
asset labels keep the spaces around inline markup; earlier releases joined
highlighted terms to their neighbours. Search and semantic caches written by
earlier releases can still hold joined snippets until they expire, so use
`cache_mode="refresh"` where that matters.

For 1.8.4, rebuild the API, DNB, browser and authenticated adapter images with
the existing Compose project and enabled profiles, and update any operator
override that pins an adapter image tag. Keep all volumes. Browser reads of
public targets now load subresources from any public host, rendered reads can
take a second settled capture, and DNB crawls scroll bounded infinite feeds.
The retained extraction budget defaults to 4,000,000 characters while responses
stay capped; an operator `.env` that pins `DETHROTTLED_EXTRACT_CACHE_CHARS` keeps
the old limit until it is raised. Cached extractions are not rewritten, so use
`cache_mode="refresh"` to reassess a page read by an earlier release.

For 1.8.5, rebuild the API, DNB and authenticated adapter images with the
existing Compose project and enabled profiles, and update any operator override
that pins an adapter image tag. Keep all volumes; no corpus migration is needed.
Search rows gain `duplicates`, `date_coverage` and `deduplication`, and fetched
pages report publisher-declared dates with `date_source: "page"`. Browser
settling now ends once visible text is stable, endless feeds stop at 50,000
added characters (`DNB_SCROLL_MAX_ADDED_CHARS`), and a target site's 403 or
timeout no longer rests the renderer for other sites.

For 1.8.6, rebuild the API, DNB and authenticated adapter images with the
existing Compose project and enabled profiles, and update any operator override
that pins an adapter image tag. Keep all volumes. The rewritten agent skill and
[third-party notices](../THIRD-PARTY-NOTICES.md) ship in the package and image.
Compose no longer pins an old version in the default user agent: leave
`DETHROTTLED_USER_AGENT` unset or empty to send the current version and project
URL.

For 1.8.7, rebuild the API, DNB, layout (Docling) and authenticated adapter
images with the existing Compose project and enabled profiles, update any
override that pins an adapter image tag, and pull the new SearXNG pin
(2026.11.6). Keep all volumes. The API data volume gains `waymarks.json`,
`waymarks.key` (owner-only) and `engine-policy.json`; deleting them only resets
what was learned. Cached reads keep their old 21-day lifetime until they expire
or are refreshed; new front pages, feeds, live blogs and limited reads use the
shorter lifetimes. `/stats` no longer shows domain names to adapter callers.
The layout worker moves to torch 2.14.1 for a published torch advisory.

For 1.8.8, rebuild the API image (and the adapters with it, to keep versions
matched) with the existing Compose project; keep all volumes. News searches add
Google News and Reuters through Google News RSS and stop asking SearXNG for its
whole news category, which in 1.8.7 added undated Brave rows. Set
`DETHROTTLED_NEWS_FEEDS=` to turn the two new engines off.

For 1.8.9, rebuild the API and adapter images with the existing Compose project;
keep all volumes. News results are ordered fresh, undated, stale, then front
pages, social posts and headline roundups, with at most two leading places per
site; SearXNG's news call is capped at 1.5 s (a missed cap is reported as
`capped` and never rests the engine) and no longer asks its own Bing News engine.

For 1.8.10, rebuild the API and adapter images; keep all volumes. A SearXNG
engine that SearXNG itself briefly suspends after a missed time cap
(`Suspended: timeout`) is no longer rested for 30 minutes, and news searches
return `engine_order` (order, demotions and `ordering` counts) in the
`/v2/search` response. An engine rested by 1.8.9 recovers on its own within 30
minutes; removing its `searxng:` entry from `engine-health.json` clears it at once.

For 1.8.11, rebuild the API and adapter images; keep all volumes. A SearXNG
engine that misses the news time cap three searches running is rested for half
an hour (`rested_after_caps`) instead of being asked, and waited for, on every
search; a single miss still never rests it. The package description on PyPI now
uses absolute links, and `scripts/check_docs.py` rejects relative README links.
Reads of 50 heavily used sites start at their measured step and use official
keyless APIs where they exist (`sites.py`); Google's "unusual traffic" page and
similar block pages, including script-only verification pages such as
Google Scholar's, are reported as blocks instead of content (`/drive` reports
Google's `/sorry/` page as `access.status: challenge`); automatic
browser reads of a bare domain may follow its redirect to the `www.` host.

For 1.9.1, rebuild the API and DNB images; keep all volumes. Search: after DDG
Lite, Bing's and Yahoo's result pages are read directly (SearXNG's Yahoo engine
returned nothing on every live search, 17 Nov 2026) and Google in the browser is
the last resort. Google's `/goto` links are resolved one at a time and resolution
stops at Google's first throttle page (never waited out); the rest are matched to
rows already collected where the domain and title agree (`destination.inferred`)
or listed under `unresolved`. Measured 18 Nov 2026 on 8 queries: 35 of 65 Google
results resolved before the throttle; of the 30 throttled, 1 was recovered from
Yandex/Mwmbl alone (5 with every engine's rows). Mwmbl's keyless API replaces
SearXNG Yahoo as a supplement.
`engines` lists every provider that found a URL. Research resolves its candidates'
DNS concurrently (3-10 s saved per call) and keeps one spare read queued. `/status`
no longer turns degraded when the server has merely been idle for a minute. A site
with an official API reader is no longer skipped by its browser-wall record.

For 1.9.0, rebuild the API, DNB, format and adapter images; keep all volumes.
Measured in web-bench `browser-settings-ab` (rounds 1-6, 17 Nov 2026):

- **Chrome.** The browser worker runs Google Chrome on amd64 (Patchright's
  Chromium on arm64), always headed. `DETHROTTLED_BROWSER_HEADLESS`,
  `DETHROTTLED_CRAWL_HEADLESS` and `DETHROTTLED_CRAWL_GRAPHICS` are gone. The
  render browser keeps default graphics, which uses half the CPU of the Mesa
  drive browser.
- **No Crawl4AI.** The worker returns the rendered HTML, and the API extracts
  it whole-page (`extract.rendered_text`). On rendered pages this matched
  Crawl4AI's markdown fact for fact, with a third of the text. The render step
  is called `render` (it was `crawl4ai`) in `tier`, `acquisition_attempts`,
  `/stats` and site pins. Settings are `DETHROTTLED_RENDER_URL`,
  `_TIMEOUT`, `_PAGE_MS` and `_BUDGET`; the 1.8 `DETHROTTLED_CRAWL4AI_*`
  names are still read, and saved waymarks are translated on load. The
  `legacy-browser-search` and `legacy-crawl4ai` profiles and
  `docker/crawl4ai/` are removed; the old `browser-state` volume is unused and
  can be deleted by hand.
- **Native lane.** Public pages connect directly (HTTP/3 included), and Indeed
  reads again. The worker needs `cap_add: [NET_ADMIN]` (in the Compose file)
  and starts as root only to:
  - load an nftables egress firewall atomically and verify it from each identity;
  - start the DNS filter on 127.0.0.1:53;
  - start one unprivileged Playwright server per browser identity.

  Every long-running process then has empty capability and bounding sets and
  `no_new_privs`. The identities:
  - **public Chrome** (UID 10005), for search, render and /drive of public
    pages, may reach public addresses and the DNS filter only. It cannot reach
    loopback, private, reserved, link-local, multicast, CGNAT or translation
    ranges, cloud metadata, Docker peers, the host via the bridge, or any
    network the container has a route to (`DETHROTTLED_EGRESS_DENY` adds more);
  - **scoped Chrome** (UID 10006), for private-network reads and host
    allowlists, may reach only the CONNECT gate's loopback ports
    (`DETHROTTLED_GATE_PORTS`).

  The rules match the socket's owner, so they hold for HTTP, QUIC, WebSockets
  and WebRTC alike, whether adblocking is on or off. The DNS filter applies the
  HaGeZi list and never returns a private address. Chrome policy turns secure
  DNS off and stops WebRTC UDP outside a proxy, which also closes a STUN path to
  private addresses that the 1.8 gate did not cover. A gate with nothing
  chained behind it now refuses non-public destinations, which closes 1.8's
  path from browser-search pages to private addresses. If the firewall cannot
  be loaded or verified, the worker exits instead of starting.
  `DETHROTTLED_BROWSER_NETWORK=gate` is the 1.8 arrangement, chosen
  explicitly. Validation with destination-side listeners and packet captures
  is in web-bench `browser-settings-ab/security-1.9.0`.
- **GPU.** With `docker-compose.gpu.yml` (added automatically by
  `scripts/compose-auto.sh` when the host has `/dev/dri`), each browser identity
  gets the device groups. Chrome then reports the real GPU instead of llvmpipe,
  and uses about a third of the CPU per page (0.58 s against 1.96 s). It changed
  no site's blocking decision in a 56-load test (browser-settings-ab, round 9).
  `DETHROTTLED_BROWSER_TIMEZONE` and `DETHROTTLED_BROWSER_LANG` give the browser
  the machine's own timezone and language; compose-auto fills them from the host.
- **Browser identity, measured per site** (browser-settings-ab rounds 10-11):
  - Chrome 157's `Accept` header advertises JPEG XL. DataDome on forbes.com
    refuses that combination together with an en-US `Accept-Language`, so
    `DETHROTTLED_BROWSER_DISABLE_FEATURES` turns JPEG XL off by default.
  - Each browser context now takes the machine's language as its locale.
    With Chrome's own en-GB header, Reddit answered every read with a
    verification page; with the locale it reads.
  - Neither change cost any other measured site. A user-agent override that
    claims an older Chrome was measured and rejected: eBay returned 403 and
    LinkedIn 429.
- **Ladder.** A render 401/403 now escalates to the headed browser, which
  recovered Bloomberg Markets.
- **Search.** The `ddgs` fallback and `DETHROTTLED_WEB_ENGINES` are removed.
  DuckDuckGo is read over TLS, then by the browser worker, with SearXNG and
  the news sources as before.

## Guided Setup and DPR

[Guided Setup](GUIDED-SETUP.md) saves an override without starting services.
Keep the existing Compose project name and inspect the plan before applying it.
DPR jobs use `dpr-jobs.sqlite` in the API data volume. Active jobs become
interrupted after an API process restart and can be [resumed by the caller](DPR.md).

## State and backups

| Storage | Contents |
|---|---|
| dethrottled-data | Cache, corpus, retained documents/source files and jobs |
| dnb-state | Sensitive DNB checkpoints and browser operation journal |
| dnb-trust | Public DNB issuer key |
| browser-state | Checkpoints for the optional legacy browser |
| adblock-state | Last-good HaGeZi list, attribution, validators and worker observations |
| media-models, layout-models | Optional downloaded model assets |
| adapter-state / host admission path | Public shared request admission |
| Registry bind / protected host path | Public bearer hashes and scopes |

Image weights live in `/opt/dethrottled/models`, not the data volume. Retain
model/source hashes, previous image tags, Compose/config files and registry
permissions before updates. Protect browser/login and collected source data.

For live SQLite backups use SQLite's backup API, not a lone copy of a database
with an active WAL. For a whole-volume archive, stop its writers first, archive
outside the checkout, restore on the destination and verify before deleting the
source. `docker compose down` preserves named volumes; `down -v` destroys them.
Check actual volume names rather than assuming a project prefix.

## Upgrade and rollback

Rebuild and recreate only changed services. Retain rollback image tags and
compatible data. Verify SearXNG pins when updating upstream images. The offline PDF
print utility retains its independently tested runtime; it does not run the
renderer HTTP server. Browser restarts lose live DOM/tabs but saved
checkpoints can restore selected state. Core restarts interrupt unfinished jobs;
committed rows remain and resume is explicit.

When adapter code/instructions change, install/restart the adapter too. Do not
assume changing a source file reloads a running process or remote plugin capture.
Verify `initialize.instructions` against the backend workflow hash and refresh
`tools/list`. Restarting unchanged adapters is not needed for a docs-only update.
Stale request leases can temporarily consume slots after a crash/restart.

Corpus v2 uses a durable background queue for the configured MiniLM/E5 models.
Check `/corpus/stats.index` for jobs, coverage, disk use and pending maintenance.
Its 90-day retention does not extend extraction or full-document cache lifetimes.
Run bounded local migration with `python -m dethrottled.corpus_migrate --limit 32`;
repeat batches, allowing the API worker to drain accepted jobs. Unknown legacy
visibility is skipped; inspect the counts rather than assuming old prefix
embeddings became full public documents. See [Corpus migration](CORPUS.md#migration-repair-and-rollback).
Schema 1 remains an explicit rollback and retains its supervised E5 backfill.
Setting `DETHROTTLED_MULTILINGUAL_CORPUS=0` disables E5 retrieval/indexing. Roll
back images and worker URLs together when required; do not delete data to roll
back code. Unknown external browser-operation outcomes remain inspect-before-retry.

## Architecture support

The base stack has historical paired x86_64/ARM64 measurements and CI native
build/start coverage. Buildx can target either architecture; cross-execution
needs binfmt/QEMU and is slower. Those checks do not certify every newer optional
worker, Mesa profile or external site's behavior. Validate the actual enabled
stack on its target host. See [evidence](EVIDENCE.md).

## Network and diagnostics

The API binds host loopback by default and has no caller authentication. The
browser worker, SearXNG and optional parsing workers are private. Since 1.9.0 the
browser worker's public pages leave natively through its DNS filter (see Adblock
operations); its `/health` reports `network_lane` (`native` or `gate`).
The optional HTML-to-PDF overlay currently publishes 8788 on all host interfaces;
review its mapping. Public adapters do not replace network egress isolation.

Inspect `/stats` for tier rest state, cache and headed/renderer admission; the
cache block reports `bytes`, `max_bytes` and the last expiry/eviction run.
Research has its own two-request semaphore. Optional workers expose private readiness and
metrics. Record exact URLs, expected facts, timestamps, input controls and raw
results; distinguish missing source evidence from a transport or limiter failure.

## Search upstream cooldowns

The core rests refused SearXNG engines for
`DETHROTTLED_ENGINE_REST_SECONDS` (default 1800 seconds). A sole selected engine
and an entirely blocked selection stay rested too; neither bypasses the timer.
The default DDG family additionally rests only after TLS Lite **and both** browser
Lite/HTML paths explicitly refuse in the same failed acquisition. A TLS-only refusal
still gets browser recovery. Repeated confirmed refusals use 30/60/120-second rests,
bounded by the existing engine-rest setting; a longer parsed TLS `Retry-After` is
honoured up to one day. Pacing intervals are unchanged. The state is persisted in
the existing engine-health file. After expiry, one default-family recovery is in
flight per API process; only a fresh successful DDG acquisition clears the state.
Cached choices remain readable and do not prove upstream recovery. Independent
The Bing and Yahoo doors (rested separately), Yandex, Mwmbl and explicitly configured non-DDG fallbacks remain eligible.

API-coordinated rest applies to its DDG acquisition chain and active-rest filtering
of explicitly requested SearXNG `duckduckgo` web. News engines are not automatically
classified as the same failure. Direct private browser-worker calls and separate API
processes do not share the process-local recovery guard; this is not a distributed
rate limiter. Ordinary timeouts/HTTP 500s do not by themselves trigger family rest.

SearXNG also has its own suspensions. The pinned image's measured defaults are
180 seconds for ordinary access-denied/429 responses and 3600 for CAPTCHA,
with longer Cloudflare/reCAPTCHA policies. These are separate layers.

The default Compose stack mounts a small SearXNG plugin that extends refusal
suspension when `Retry-After` specifies a longer delay, accepting seconds or
HTTP dates. Keep both plugin mounts and its settings entry together when
customizing Compose. Existing stronger suspension policies are preserved. A
source-installed Python API using an independently managed SearXNG does not
install that Compose plugin automatically.

A local cooldown expiring does not establish upstream recovery. Preserve the
next probe's actual status and usable results. In the recorded study Brave
still returned HTTP429 just over 30 minutes after its first refusal. Do not
repeatedly probe it per search. See the
[source-choice report](../evaluations/agent-search/results/2026-11-03/REPORT.md)
for effective settings and negative observations.

## Documentation parity

The API image includes `/app/README.md`, `/app/docs` and recorded evaluation
material at `/app/evaluations`. Current guides link to dated evidence rather than
mixing release notes into setup. Regenerate request references and check links
when source contracts change:

```sh
python scripts/docs_reference.py --check
python scripts/check_docs.py
```

Run these in an installed development environment, or the API image with a
checkout mounted. Rebuild/recreate the API to update its immutable documentation
copy; changing host Markdown alone does not update an existing container. Verify
file hashes and readability as its service user after promotion.

[Documentation home](README.md) · [Agent guide](AGENT-UPGRADES.md) · [API](API.md) · [Evidence](EVIDENCE.md)

## Adblock operations

The [native domain filter](ADBLOCK.md), introduced in 1.6.0, needs the updated API and browser
images plus a recreated SearXNG worker. Since 1.9.0 the browser worker applies it
in its DNS filter for public pages and in the CONNECT gate for scoped ones; its
blocks still count in the worker's `/stats` observation. Its `adblock-state` volume holds the
last working list and attribution; preserve it for offline restarts. Check each
worker observation in `/stats` rather than inferring coverage from API readiness.

### Interpreting discovery observations

Readiness observes real searches; it does not probe providers on status requests.
An observation older than 60 seconds becomes `availability="unknown"`, not a
confirmed outage. Inspect `observation_state` (`current`, `stale`, `unobserved`),
`last_observed_availability`, `age_seconds` and `upstream_status` together. Existing
boolean readiness fields remain conservative. Bing News is not requested by a
normal web search, so its false readiness flag alone is not a web-search failure.

Browser discovery accepts one or two validated source choices for narrow queries;
it does not require three results to declare success. Empty/challenge responses
still fail explicitly. Worker `/metrics` retains the last 20 failed searches'
provider/status/reason summaries and timings, without queries or page text.
API attempts preserve worker refusal reasons and service/queue timings. This
helps distinguish sparse results, upstream refusals and local admission failures;
it cannot guarantee that an intermittently refusing provider has recovered.

A headerless TLS-only DDG refusal can recover through Patchright automatically.
A server-supplied `Retry-After` on a refused/unavailable direct or browser
acquisition pauses further DDG-family acquisition; other providers and eligible cached results
remain usable. Expiry permits one recovery probe, not a claim of upstream recovery.
Empty DDG paths cannot turn earlier refusals into a genuine zero-result query.
The [live refusal test](../evaluations/ddg-recovery/results/2026-11-06/REPORT.md)
records the transport-ablation scope and remaining IP-wide blocking limit.
