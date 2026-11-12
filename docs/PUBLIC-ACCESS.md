# Public REST and MCP access

Dethrottled's raw API is an unauthenticated service for a trusted network. Keep
it on loopback or a private container network. The optional REST and MCP adapters
add bearer authentication, scopes, shared admission and caller-scoped evidence.
A TLS reverse proxy publishes those adapters; it does not make the raw API safe
to expose directly.

The packaged `dethrottled stack` commands manage the content engine and workers.
They do not provision public credentials, TLS or the public adapter profile.
Use the Git-checkout overlay below or run the adapters as host-managed services.
There is no shipped public bearer token.

## Deploy the container adapters

Start from a checkout of the release you intend to run. Create a protected token
registry and register each client's bearer through stdin:

```sh
mkdir -p secrets
python scripts/access-tokens.py --registry secrets/tokens.json \
  add research-client --scopes web,drive,corpus < /secure/path/client-bearer.txt
```

The input file contains a bearer of at least 24 characters. Generate and store it
securely, give the client that bearer, and keep both files out of Git. The command
stores only its SHA-256 hash; it does not generate or print the bearer. The parent
directory must exist. Administrators must serialize registry edits.

A registry entry has this shape:

```json
{"tokens":[{"label":"research-client","sha256":"<64 lowercase hex characters>","scopes":["web","drive","corpus"],"revoked":false}]}
```

Set `DETHROTTLED_TOKEN_REGISTRY_FILE` to the existing registry file. Arrange file
ownership and permissions so the API and both adapters can read it. Set
`DETHROTTLED_REGISTRY_GID` to the registry’s numeric group ID (default 10001).
The management command
uses mode 0640 and preserves existing owner/group on replacement. The bind mount
fails if the source file is absent. Do not put plaintext bearers in Compose,
command arguments, README examples or browser-side scripts.

Set `MCP_ALLOWED_HOSTS` to the Host values the proxy will forward, such as your
public hostname and any required port form. The default permits loopback hosts.
Then start the engine and adapters:

```sh
docker compose -f docker-compose.yml -f docker-compose.agents.yml \
  --profile public up -d --build
```

| Service | Default host binding | Purpose |
|---|---|---|
| Core API | `127.0.0.1:8787` | Private content engine |
| MCP | `127.0.0.1:18184` | Streamable HTTP at `/mcp` |
| REST | `127.0.0.1:18186` | Allowlisted HTTP routes |

`DETHROTTLED_MCP_PORT` and `DETHROTTLED_REST_PORT` change the adapter host ports.
Both adapters mount the same read-only registry and share `adapter-state` for
admission. They reach the API over the private Compose network.

## Publish through TLS

Route `/mcp` and `/mcp/*` to the MCP adapter, preserving the path. Route supported
REST paths to the REST adapter. For example, this Caddy configuration uses a
placeholder hostname; replace it and configure the corresponding allowed Host:

```caddyfile
retrieval.example {
    @mcp path /mcp /mcp/*
    handle @mcp {
        reverse_proxy 127.0.0.1:18184
    }
    handle {
        reverse_proxy 127.0.0.1:18186
    }
}
```

Connect an MCP client to `https://retrieval.example/mcp` with an
`Authorization: Bearer <client bearer>` header. REST requests use the same bearer.
Use the client's protected credential settings, not source-controlled config.
Configure proxy timeouts/body limits for the reads and browser operations you
intend to allow. Base Compose does not configure TLS or change your firewall.

## Verify access and the backend version

Check the engine and adapter directly on the host:

```sh
curl -fsS http://127.0.0.1:8787/health
curl -fsS http://127.0.0.1:18184/health
curl -fsS http://127.0.0.1:18186/health
```

The MCP health response separates the Dethrottled application `version` from
`sdk_version`. It reports backend identity as `match`, `mismatch` or `unavailable`.
Application version comes from the release's companion version module; it should
match the API actually reached. The bridge checks at startup and refreshes on
health requests after a ten-second cache. Mismatch/unavailable transitions are
logged; a mismatch does not itself shut down the bridge.

Matching version strings alone do not prove matching source or usable reads.
Verify backend capabilities, then perform an authenticated MCP initialization,
`tools/list` and a small search/read through the public proxy. Also confirm that
missing/revoked bearers and private-target requests are rejected. The REST
adapter's own `/health` is a liveness response, not a backend-version check.
With the proxy example above, public `/health` reaches REST; MCP's health route
remains available on its local port.

After upgrades, restart/recreate adapters with matching companion files and
refresh client connections/tool schemas. Long-running remote plugins can retain
older code or instructions; their activation is the client operator's responsibility.

## Host-managed adapters

Install the full `requirements/adapters.lock` into adapter virtual environments.
`requirements/adapters.txt` records direct dependencies for regenerating the lock;
it does not freeze the full environment. The lock pins MCP SDK **1.30.0**. Avoid
an unbounded SDK upgrade; test transport/schema compatibility before changing it.
The SDK version is separate from the engine's release number.

Install these files on the adapter Python path:

| Repository source | Installed module |
|---|---|
| `src/dethrottled/access.py` | `dethrottled_access.py` for both adapters |
| `src/dethrottled/__init__.py` | `dethrottled_version.py` beside MCP |
| `src/dethrottled/workflow.py` | `dethrottled_workflow.py` beside MCP |
| `adapters/mcp_server.py` | MCP ASGI application, commonly `server.py` |
| `adapters/rest_gateway.py` | REST ASGI application, commonly `public_gateway.py` |

Set `MCP_BACKEND_URL` and MCP's `MCP_ALLOWED_HOSTS`. Set
`DETHROTTLED_TOKEN_REGISTRY` (default `/etc/dethrottled-access/tokens.json`) and
`DETHROTTLED_ADMISSION_DB` (default `/var/lib/dethrottled-access/admission.sqlite`)
for both services. Registry files must be readable and the admission directory
writable by their service users. Separate virtual environments are supported.
A strict systemd filesystem sandbox needs the admission write path. REST URL
validation also needs DNS access; a loopback-only IP sandbox can reject valid
public domains before retrieval begins.

Compare the initialization workflow hash against
`capabilities.client_contract.workflow_sha256`. Native image CI runs
`scripts/verify_adapter.py` offline against a deterministic backend, checking
handshake, tools, strict arguments, authentication, revocation and target policy.
Those offline tests complement deployment checks through the actual proxy.

## Tools, routes and result parsing

The connected MCP server's `tools/list` schemas and initialization instructions
are authoritative. See the generated [MCP reference](MCP-REFERENCE.md) and
[agent guide](AGENT-UPGRADES.md). Use `categories` and `format`, not `category` or
MCP `raw`. The public adapter injects public-target policy and evidence namespace;
clients cannot select another identity's namespace through arguments.

The REST adapter allowlists search/read/research/drive, documents, jobs, site crawl
and diagnostics. The [HTTP reference](HTTP-REFERENCE.md) describes core requests;
it does not promise arbitrary future core routes will be public automatically.
MCP and REST parameter surfaces differ: for example, MCP HTML reads use
`format="html"`, while the core retains legacy `raw` support. Follow the selected
transport's schema rather than copying every core argument into an MCP call.

`corpus_search` exposes `mode`, `domains` and `support`. Start with standard
support and expand explicitly to broad candidates when evidence is missing;
preserve support warnings and inspect passages. Source/model agreement is not
answer verification. Registered public corpus document handles can be reopened
across caller namespaces without granting access to another caller's private
documents. See [the client playbook](AGENT-PLAYBOOK.md#reuse-public-evidence-with-corpus-v2).

Legacy list-returning tools such as search and fetch emit a complete JSON value
per `content[].text` entry. Parse each entry separately; do not concatenate blocks
and parse them as one document. Prefer `structuredContent` when supplied.
Preserve native image blocks, warnings, provenance, document IDs and continuation
metadata. Plain diagnostic text is not assumed to be JSON.

## Identity, admission and target policy

Scopes are `web`, `drive` and `corpus`. Both adapters verify the hash registry.
Host-managed registry changes/revocation reload on subsequent requests and fail
closed on unreadable or invalid credentials. For the container overlay, the
registry is a file bind mount: an atomic replacement by `access-tokens.py` can
leave an existing container reading the previous inode. After editing the host
registry, recreate the API and both adapters to remount the current file:

```sh
docker compose -f docker-compose.yml -f docker-compose.agents.yml \
  --profile public up -d --no-deps --force-recreate dethrottled mcp rest
```

Do this immediately for revocations; do not assume the replaced host file is
already visible inside running services. Revocation does not cancel work already
admitted. Named admission and engine data volumes are preserved by recreation.

MCP uses stateless Streamable HTTP. Tool calls use POST. Authenticated GET
event-stream requests return 405 without reserving an execution slot.

Default admission is three concurrent requests per bearer identity, eight
concurrent requests globally and 120 requests per minute per bearer identity.
The controls are `DETHROTTLED_CLIENT_CONCURRENCY`,
`DETHROTTLED_GLOBAL_CONCURRENCY` and `DETHROTTLED_REQUESTS_PER_MINUTE`.
HTTP 429 identifies the limiter and supplies retry hints; admission-storage failure
returns 503. Crashed leases expire after 300 seconds, so a restart can temporarily
leave stale leases. That expiry differs from a short busy/retry hint.

DPR is available through authenticated REST under `/v1/dpr/`. Jobs use the
bearer namespace and fetch only public targets. Indexing public job evidence
requires corpus scope. DPR does not add MCP tools. See [DPR](DPR.md) for limits.

The same bearer can reopen scoped documents/jobs through REST and MCP. Explicit
browser session IDs use transport-specific namespaces. Reserved `auto-read-*`
continuation handles are the exception: adapters map them to the same caller-scoped
recovery identity. The shared corpus is not made private per bearer by these scopes.
Use `POST /documents/status` or MCP `document_status` to inspect the caller's own
retained document metadata without fetching a URL.

Direct/TLS redirects and headed subrequests receive public-target checks. This is
not full DNS pinning or complete Crawl4AI egress containment; retain appropriate
network isolation. Keep the raw API private. For latency investigations, record
X-Request-ID, Server-Timing, arguments and application/backend versions. A proxy or
edge WAF can reject requests before either adapter; investigate that separately
from backend or plugin behaviour.

[Documentation home](README.md) · [Agent guide](AGENT-UPGRADES.md) · [API](API.md) · [Evidence](EVIDENCE.md)

## Domain filtering

Native adblock filtering applies in the backend for both REST and MCP clients;
it adds no public per-request override. A refused fetch reports `policy_blocked`
and stops automatic recovery. Operators should inspect backend `/v2/status` for
list availability and worker observations. See [native filtering](ADBLOCK.md).

## Admission refusals and request discovery

REST admission refusals retain their HTTP 429/503, `Retry-After`, limiter headers
and structured retry body. MCP admission refusals use a JSON-RPC error with
`error.code=-32000` and the same diagnostics in `error.data`. For a bounded,
valid POST request, `id` matches the request (including zero/string IDs). A
notification, malformed/oversize body, body-read timeout or GET has no correlated
request ID; no invented tool result is returned. Authentication errors remain
HTTP authentication failures. Clients must inspect non-2xx transport responses
and retry hints instead of reporting them as empty tool results.

Capabilities `request_contracts` derives methods, accepted body field names,
required fields and query parameter names from the actual core OpenAPI schema.
For full types/defaults/constraints use the linked `/openapi.json` or generated
HTTP reference. REST research requires `question`; search requires `query`;
corpus search is GET with `q`; fetch/crawl/job submission require `urls`;
document reads require `document_id`; job polling requires `job_id`. MCP tool
schemas remain authoritative for MCP argument names. No new REST aliases were
added to conceal these differences.

## Source selection and field extraction

The existing authenticated routes also carry search `domains`/`exclude_domains`,
fetch `selectors` and site `mode="map"`/`max_discovery_requests`. They add no public
route or scope. MCP exposes the same controls through search, search_and_fetch,
research, fetch and crawl_site. Refresh cached tool schemas after upgrading.
Host discovery filters are not network authorization: remote public-target checks,
browser allowed_hosts and caller namespaces still apply. See [the API guide](API.md#constrain-source-choices).
