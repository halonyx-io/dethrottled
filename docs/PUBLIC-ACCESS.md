# Public REST and MCP access

The raw API is an unauthenticated trusted-network service. The repository includes
optional REST and MCP adapters with shared bearer identity, admission and evidence
namespaces. They are separate deployment entrypoints, not raw API authentication.
Base Compose does not publish them or configure TLS automatically.

## Portable deployment

Create a protected registry file with token hashes, not plaintext tokens:

```json
{"tokens":[{"label":"research-client","sha256":"<64 lowercase hex characters>","scopes":["web","drive","corpus"],"revoked":false}]}
```

Use `scripts/access-tokens.py` to manage labels and hashes, reading plaintext
bearers from stdin rather than committing them. For the container profile, set
`DETHROTTLED_TOKEN_REGISTRY_FILE` to the existing registry path and make it readable
by UID 10004. The bind mount fails if the file is absent. Set `MCP_ALLOWED_HOSTS`
to the actual proxy Host values; its default permits only loopback-style hosts.

```sh
docker compose -f docker-compose.yml -f docker-compose.agents.yml \
  --profile public up -d --build
```

MCP binds host loopback 18184 and REST 18186 by default. A TLS reverse proxy
routes `/mcp` to MCP and supported REST paths to REST. Adapters use the same
`adapter-state` volume for admission and the same read-only registry mount.
There is no shipped default public bearer token.

## Host-managed deployments

Install the full `requirements/adapters.lock` in adapter virtualenvs.
`requirements/adapters.txt` records the direct requirements used to regenerate it;
installing only that shorter file does not freeze the transitive dependencies.
`adapters/mcp_server.py` uses the MCP SDK/httpx; `adapters/rest_gateway.py` uses
FastAPI/httpx. Install the shared `src/dethrottled/access.py` as
`dethrottled_access.py` on their PYTHONPATH. Also install
`src/dethrottled/__init__.py` as `dethrottled_version.py` and
`src/dethrottled/workflow.py` as `dethrottled_workflow.py` beside the MCP adapter.
The adapter imports the same workflow text used by the API; compare the startup
instruction hash with `capabilities.client_contract.workflow_sha256` after an
upgrade. Reconnect clients that retain older tool descriptions or instructions.
Separate virtualenvs are supported.
Set `MCP_BACKEND_URL` and `MCP_ALLOWED_HOSTS` as appropriate.

`DETHROTTLED_TOKEN_REGISTRY` defaults to `/etc/dethrottled-access/tokens.json`;
`DETHROTTLED_ADMISSION_DB` defaults to
`/var/lib/dethrottled-access/admission.sqlite`. Both service users need admission
directory access. Registry replacement/revocation reloads on request and fails
closed. A strict systemd filesystem sandbox needs the admission write path. REST
validation also needs DNS access; a loopback-only IP sandbox can reject valid
public domains before source retrieval begins.

## Version identity and SDK upgrades

MCP initialization advertises the Dethrottled release version, currently **1.1.2**.
The adapter's `/health` reports `version` separately from `sdk_version` (**1.30.0**).
It also reports backend identity as `match`, `mismatch` or `unavailable`. The bridge
checks at startup and refreshes on health requests after a ten-second cache.
Mismatch/unavailable transitions are logged; rolling upgrades remain possible.
Matching version strings alone do not prove matching code or correct retrieval.
The backend capabilities version identifies the engine actually reached. These
can differ during a rolling upgrade; the SDK number is not an engine version.

The adapter pins the maintained MCP SDK 1.x line. Version 1.30.0 adds same-origin
HTTP redirect checks and bounded idle stateful sessions; this adapter remains
stateless. The [SDK 1.30.0 release notes](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v1.30.0)
explain those changes. SDK 2.x requires a separate
[API migration](https://py.sdk.modelcontextprotocol.io/migration/). Native image CI executes
`verify_adapter.py` offline, checking the real handshake, tools, strict arguments,
authentication, revocation and private-target rejection before deployment.

## Client contract and routes

Use the connected MCP `tools/list` schemas and initialization instructions.
There are 20 tools; unknown fields are rejected. Use `categories` and `format`,
not `category` or MCP `raw`. [MCP reference](MCP-REFERENCE.md) and
[agent integration](AGENT-UPGRADES.md) explain parameters and model-visible data.
The REST gateway exposes an allowlisted subset of the core routes, including
search/read/research/drive, documents, jobs, site crawl and diagnostics; its own
health route remains unauthenticated. The [HTTP reference](HTTP-REFERENCE.md)
describes core requests, not a promise that arbitrary extra core routes are public.

Preserve structured metadata and forward native MCP image blocks. REST clients
can read the same workflow policy from capabilities. A client that strips fields
or hides tool results can defeat server-side affordances. After upgrades, refresh
tool schemas and compare the initialization/workflow hash. Remote plugin code
activation remains the client operator's responsibility.

## Result content and client parsing

Legacy list-returning tools such as search and fetch emit one complete JSON value
per `content[].text` entry. Parse each entry separately; joining the text and
parsing once loses the result-set contract. Tools with structured output also
return `structuredContent`; prefer it when present. Preserve native image blocks
separately. JSON text is compact, but parsed values, entry order and block types
are unchanged. Plain diagnostic text is not assumed to be JSON.

## Identity, limits and network policy

Scopes are `web`, `drive` and `corpus`. Both adapters verify the same hash registry.
Per-caller/global admission defaults are 3/8 concurrent requests and 120 requests
per minute. 429 responses identify the limiter and provide retry hints; storage
failure returns 503. Crashed leases expire after 300 seconds. A busy polling hint
is not the lease expiry. Stale leases can temporarily delay callers after an
adapter restart; this remains a documented limitation.

Wrappers force public-target policy and evidence namespace from verified identity.
The same bearer can reopen retained documents/jobs through REST and MCP; forged
namespaces cannot select another caller's records. Browser session namespaces
are transport-specific; a REST session ID is not an MCP session ID. The existing
shared corpus is not converted into per-token private storage by this mechanism.

Direct/TLS redirects and headed subrequests are checked against public policy.
This is not full DNS pinning or complete Crawl4AI egress containment; enforce
network isolation where needed. Keep the raw API private. Record X-Request-ID,
Server-Timing, exact arguments and version for latency investigations. An edge
WAF can block a request before either adapter; client User-Agent and proxy rules
must be investigated separately from plugin or backend behavior.

[Documentation home](README.md) · [Agent guide](AGENT-UPGRADES.md) · [API](API.md) · [Evidence](EVIDENCE.md)
