# Operations and deployment

## Build and verify

From a checkout of this repository:

```sh
cp .env.example .env
docker compose build dethrottled browser-search
docker run --rm --network none dethrottled:local python /app/verify_image.py
docker compose up -d
docker compose ps
curl -fsS http://127.0.0.1:8787/health
curl -fsS http://127.0.0.1:8787/v2/capabilities
```

The offline image verifier imports the included dependencies, runs a real
corpus embedding, checks representative document readers, and confirms the
model path does not require a host mount. A green `/health` only proves the API
process is alive. Check `/ready`, `/v2/status`, `/stats`, and an actual search
and fetch to verify the sources used by your installation.

```sh
curl -sS http://127.0.0.1:8787/search \
  -H 'content-type: application/json' \
  -d '{"query":"Python documentation","limit":3,"fresh":true}'
curl -sS http://127.0.0.1:8787/fetch \
  -H 'content-type: application/json' \
  -d '{"urls":["https://example.com/"],"fresh":true}'
```

Inspect the returned rows. A result page with HTTP 200 can still contain no
usable results; a fetch response with HTTP 200 can contain failed rows. A
successful browser worker must yield real URLs and snippets, not only an HTTP
status from its search engine.

## Logs and state

```sh
docker compose logs --tail=100 dethrottled browser-search searxng crawl4ai
docker compose ps
curl -fsS http://127.0.0.1:8787/stats
curl -fsS http://127.0.0.1:8787/corpus/stats
```

The named `dethrottled-data` volume holds `cache.sqlite`, `corpus.sqlite`,
and local engine/domain-health records. Keep this volume when rebuilding or
moving the service if the corpus and cached pages matter. Model weights are in
the immutable API image, not this volume. `docker compose down` preserves the
volume; `docker compose down -v` removes it.

Before a stateful host move, stop writers, archive the volume, restore it on
the destination, then start the destination Compose project. A portable
example using a temporary helper container is:

```sh
docker compose stop dethrottled
docker run --rm -v dethrottled_dethrottled-data:/data:ro \
  -v "$PWD":/backup alpine tar -C /data -czf /backup/dethrottled-data.tar.gz .
```

Check the actual volume name with `docker volume ls` before running the
example; Compose project names can change it. Store the archive outside the
checkout and protect it as collected page data. Restart the stopped service
after the backup. Do not delete a source volume before a restored corpus has
been read successfully.

## Updating

The API and browser worker build from this repository. SearXNG and Crawl4AI
are pinned to specific upstream tags and digests in `docker-compose.yml`; the
optional PDF worker uses the same Crawl4AI pin. Update those pins deliberately
and test actual browser search, JavaScript rendering, document reading, and
the PDF worker if enabled. Rebuild images and recreate affected services with
Compose; preserve the data volume. `git status` should show only intended
source/configuration changes. Roll back by restoring the prior source and image
tags while retaining the newest compatible volume data.

## Network exposure

The default API host bind is loopback. Dethrottled itself has no caller
authentication. It can fetch requested HTTP(S) URLs, including local targets
through its raw `/fetch`; serving that API to untrusted callers without a
gateway permits unwanted network access. A public gateway should authenticate
callers, allow only intended routes, constrain request size and concurrency,
and reject private/local fetch targets. The `/research` path performs its own
public-source selection, but this does not replace gateway controls.

Browser-search, SearXNG, and Crawl4AI are not host-published by the base
Compose file. The optional PDF worker currently publishes port 8788 on all
host interfaces; adjust its overlay if that is not appropriate for your
network. Network and firewall policy belong to the deployment operator; these
docs make no firewall changes.

The default Compose project is keyless for search and fetch. Its
`CRAWL4AI_TOKEN` is an internal renderer credential, not a paid API key and
not a caller token. A hosted REST gateway and MCP bridge, if present, manage
their own separate external bearer tokens. Neither is bundled in this image.
