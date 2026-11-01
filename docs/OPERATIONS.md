# Operations

Build all enabled services from one checkout and preserve mutable state during
updates. Runtime version, image source and agent contract are separate checks;
healthy processes alone do not establish useful web access.

## Build and verify

```sh
docker compose build dethrottled browser-search
docker run --rm --network none dethrottled:local python /app/verify_image.py
docker compose up -d
docker compose ps
curl -fsS http://127.0.0.1:8787/health
curl -fsS http://127.0.0.1:8787/v2/status
curl -fsS http://127.0.0.1:8787/v2/capabilities
```

The offline verifier checks dependencies and a real corpus embedding without
host model mounts. `/health` is liveness; `/ready` checks search sources;
`/v2/status` probes configured workers and backfill. Test actual fresh search,
a known-source fetch and the specific optional worker formats you use. A 200
response can still contain failed reads or no useful search results.

For optional speech/layout/formats profiles, use both Compose files and their
worker URLs as described in [configuration](CONFIGURATION.md). Public adapters
are a separate profile or host-managed deployment.

## State and backups

| Storage | Contents |
|---|---|
| dethrottled-data | Cache, corpus, retained documents/source files and jobs |
| browser-state | Sensitive checkpoints and browser operation journal |
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
compatible data. Keep Crawl4AI/SearXNG pins and the PDF overlay aligned when
updating upstream images. Browser restarts lose live DOM/tabs but saved
checkpoints can restore selected state. Core restarts interrupt unfinished jobs;
committed rows remain and resume is explicit.

When adapter code/instructions change, install/restart the adapter too. Do not
assume changing a source file reloads a running process or remote plugin capture.
Verify `initialize.instructions` against the backend workflow hash and refresh
`tools/list`. Restarting unchanged adapters is not needed for a docs-only update.
Stale request leases can temporarily consume slots after a crash/restart.

E5 backfill is supervised and resumes committed progress. Setting
`DETHROTTLED_MULTILINGUAL_CORPUS=0` preserves the original MiniLM index. Roll
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
browser worker, SearXNG, renderer and optional parsing workers are private.
The optional HTML-to-PDF overlay currently publishes 8788 on all host interfaces;
review its mapping. Public adapters do not replace network egress isolation.

Inspect `/stats` for tier rest state, cache and headed/renderer admission; research
has its own two-request semaphore. Optional workers expose private readiness and
metrics. Record exact URLs, expected facts, timestamps, input controls and raw
results; distinguish missing source evidence from a transport or limiter failure.

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
