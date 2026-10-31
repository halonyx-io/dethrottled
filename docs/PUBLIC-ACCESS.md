# Public adapters

The raw API remains a trusted-network service. `adapters/rest_gateway.py`
(FastAPI/httpx) and `adapters/mcp_server.py` (MCP SDK/httpx) are deployment
entrypoints for authenticated public access. They share the standard-library
`src/dethrottled/access.py` runtime, installed as `dethrottled_access.py` on
the adapters' PYTHONPATH. Install adapter dependencies in separate virtualenvs;
the core API does not need the MCP SDK.

Both adapters read `DETHROTTLED_TOKEN_REGISTRY` (default
`/etc/dethrottled-access/tokens.json`) on demand. Its schema is:

```json
{"tokens":[{"label":"research-client","sha256":"<64 lowercase hex characters>",
            "scopes":["web","drive","corpus"],"revoked":false}]}
```

Store SHA-256 hashes, never plaintext bearer tokens. Restrict the registry to
root and the service group (0640). Atomic replacement triggers a reload on the
next request; removing, revoking, or corrupting the registry fails closed.
Use `scripts/access-tokens.py` to list labels, add a token read from stdin, or
revoke/restore a label. Existing separate registries must be merged by hash
before switching adapters; preserve every authorized caller's scopes.

Scopes are `web`, `drive`, and `corpus`. REST checks by route; MCP checks
inside each backend tool call. The same token has the same identity and
revocation state across both surfaces. Health remains unauthenticated.

`DETHROTTLED_ADMISSION_DB` defaults to
`/var/lib/dethrottled-access/admission.sqlite`. Its parent directory must be
writable by both service users; use a dedicated shared service group if they
differ. SQLite leases share concurrency and rate admission across processes:

| Environment variable | Default |
| --- | --- |
| `DETHROTTLED_CLIENT_CONCURRENCY` | 3 |
| `DETHROTTLED_GLOBAL_CONCURRENCY` | 8 |
| `DETHROTTLED_REQUESTS_PER_MINUTE` | 120 |

Excess work returns 429 with Retry-After, storage failures return 503, and
crashed request leases expire after 300 seconds. Requests get a trace ID
returned as `X-Request-ID` and forwarded to the backend. Core fetch/render
budgets remain separate workload controls.

Both adapters accept at most ten URLs, reject oversized requests, enforce
public target policy, and namespace browser sessions by identity. Public
`/fetch` and `/drive` set `public_only`; the core rechecks direct/TLS redirects
and headed contexts reject private-network subrequests. DNS rebinding and full
Crawl4AI egress containment require network isolation beyond these checks.
Do not expose the raw API based on these adapter checks alone.

Set `MCP_BACKEND_URL` to the loopback API URL on both adapters. For MCP, set
`MCP_ALLOWED_HOSTS` to the deployed public Host values and loopback probes.
Systemd deployments with ProtectSystem=strict must include
`ReadWritePaths=/var/lib/dethrottled-access` in their drop-ins.

An edge WAF can reject requests before either adapter sees them. Use a
clear client User-Agent (for example `my-research-client/1.0`) in examples;
change edge rules narrowly for the authenticated API paths if needed. Adapter
changes cannot fix an upstream WAF block.

## Retained evidence and jobs

Public wrappers force evidence_namespace from the verified caller identity on
fetch, research, browser downloads, document reads and jobs. A token used across
REST/MCP sees the same scoped documents/jobs. Another token cannot retrieve them
by supplying a forged namespace. This does not change the existing shared-corpus
policy. Per-caller HTTP admission and background-job admission are separate.
