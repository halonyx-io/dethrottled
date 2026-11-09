# Phase 3: verified identity and automatic gateway integration

Accepted for the isolated **x86_64 DNB worker**, 2026-11-08. Production remains
Dethrottled 1.7.1. No release, deployment, main-branch change or version bump.
See [PHASE-3-PLAN.md](PHASE-3-PLAN.md) for the approved design.

## What changed

1. **Forwarded caller identity.** The repo REST and MCP adapters authenticate
   the agent bearer and forward the same credential to the core in
   `X-Dethrottled-Caller-Authorization`. The core re-verifies it against the
   registry and accepts that header only from `DETHROTTLED_ADAPTER_CIDRS`
   (default loopback). There is no adapter signing key and no second token
   format. This is the existing 1.7.1 adapter contract, carried through to the
   DNB worker.
2. **Owner-bound sessions and checkpoints.** The worker records the first
   verified owner for each durable drive session in a small sqlite store
   (`DETHROTTLED_DNB_STATE_DIR`, default `${DETHROTTLED_DATA_DIR}/dnb`). A second
   owner using a known session id receives `403 session_owner_mismatch`; the
   first owner can still restore after a worker restart. Read aliases
   (`auto-read-*`) are not persisted. Storage failures fail closed.
3. **Durable drive operation journal.** `operation_store.py` persists `running`
   before a mutation, `completed` plus the response after success, and `unknown`
   after any failure. A retry replays a completed operation across a restart when
   the payload fingerprint matches, rejects a changed payload with
   `409 operation_id_payload_conflict`, and never replays `running`/`unknown`
   outcomes. Completed records expire after 24 hours, unknown after 7 days, with
   a row cap.
4. **Wire and fixture matrix.** `phase3_check.py` exercises the real REST and MCP
   adapters through the core into the worker: cold/reused contexts, cross-caller
   cookie/localStorage/sessionStorage/IndexedDB isolation, autonomous browser
   escalation, MCP reads, drive ownership, replay/idempotency across restart,
   spoofed owner headers, checkpoint restore, key rotation and log redaction.

The core remains the only minter of `X-DNB-Delegation`. Adapters remain the
identity authority. Clients never sign delegation and never set `X-DNB-*`
fields. The worker verification key is public only and is reread per admission.
No new dependency or public REST/MCP argument was added.

Deployment note: the currently installed `/opt/halonyx-api-gateway` and
`/opt/dethrottled-mcp` services authenticate bearers but do **not** forward the
caller identity. The repo adapters do. A 1.8.0 deployment must use the repo
adapters or add the same header to the installed ones; otherwise the core sees
anonymous callers even though the adapters authenticated them.

## Evidence

- **23/23 wire checks passed** in the built Phase 3 image
  `dethrottled-dnb:phase3-20261109` (no code mounts; non-root uid 10002):
  [phase3-wire.json](phase3-wire.json), produced by
  `phase3_check.py --rotate --worker-container p3-worker`.
- **Real-network identity check passed**: [phase3-network.json](phase3-network.json)
  — forwarded credential from loopback 200, the same credential from
  `192.168.0.7` rejected 403 by the adapter-peer gate.
- **25 focused unit tests passed**: [phase3-tests.log](phase3-tests.log)
  (`tests/test_dnb_delegation.py`, `experiments/dnb/test_phase3_identity.py`,
  `experiments/dnb/test_phase3_operations.py`). The matrix covers delegation
  tamper/expiry/audience/path/body, adapter peer trust, owner-store and
  operation-store concurrency, persistence, conflicts, unknown outcomes and
  fail-closed storage.
- **Signed protocol fixture**: [phase3-fixtures.json](phase3-fixtures.json) records
  one worker-delegation header/payload, the public-key fingerprint, the body
  digest and the verification matrix. It contains no private key or bearer token.
- **Bounded live pilot**: [phase3-live-pilot.json](phase3-live-pilot.json) —
  3/3 predefined facts retained across example.com (browser read-plan),
  docs.python.org and iana.org (direct extraction); 1.1–1.8 s per read.
- **Bounded soak**: [phase3-soak.json](phase3-soak.json) — 20/20 reads succeeded
  at ~1.66 s median / 1.73 s max; worker RSS moved from 105,840 KB to
  106,548 KB; one retained context; no failure growth.
- **Phase-1/phase-2 focused regressions**: [phase3-regressions.log](phase3-regressions.log).
  Context pool, lifecycle and extraction pool: **29 passed** in the worker image.
  Navigation scope, network policy and extraction-pool units on the host:
  **17 passed**; the one host failure needs crawl4ai and passed in the image.
- Provenance, image ID, mounted overrides and environment:
  [phase3-provenance.json](phase3-provenance.json). The worker image was built
  from `experiments/dnb/Dockerfile` with the Phase 2 accepted image as its base;
  only the read-only key directory was mounted at runtime.

## Failures retained and fixed

- The first wire run reported `checkpoint restore for owner` as false because the
  session was still live in the worker; a restart is required to prove restoration
  from the checkpoint. The harness now restarts the worker between checkpoint and
  restore. Harness defect, not a product failure.
- The first cross-caller count assertion failed because earlier runs had already
  populated the context pool. The harness now restarts the worker at the start so
  the count is deterministic. No source change was needed.
- The first image run used the old fixture port `19987`; the repo fixture listens
  on `8090`. The harness now uses `8090`. Harness defect, not a product failure.
- The host environment lacked `aiohttp`, `patchright` and `crawl4ai`; tests that
  need them were run in the accepted worker image. Original host output is
  retained in the regression log.

## Reproduce

From the prototype checkout, with Docker and the phase-2 accepted image:

```sh
# 1. Worker delegation keys and two test tokens
python - <<'PY'
import json, hashlib
from dethrottled.delegation import ensure_keys
ensure_keys()
tokens = {}
for name in ("alice", "bob"):
    raw = f"token-{name}-{hashlib.sha256(name.encode()).hexdigest()[:16]}"
    tokens[name] = raw
reg = {"tokens": [{"sha256": hashlib.sha256(v.encode()).hexdigest(),
                   "label": k, "scopes": ["web", "drive", "corpus"]}
                  for k, v in tokens.items()]}
open("/tmp/p3/keys/registry.json", "w").write(json.dumps(reg))
open("/tmp/p3/keys/tokens.json", "w").write(json.dumps(tokens))
PY

# 2. Worker with the new worker files mounted
docker run -d --name p3-worker --network host \
  -e DNB_TRUST_PUBLIC_KEY=/keys/public.pem -e DNB_ALLOW_INTERNAL_URLS=true \
  -e DETHROTTLED_BROWSER_GRAPHICS=default \
  -v /tmp/p3/keys:/keys:ro \
  -v "$PWD/experiments/dnb/dnb_service.py:/app/dnb_service.py:ro" \
  -v "$PWD/experiments/dnb/session_owners.py:/app/session_owners.py:ro" \
  -v "$PWD/experiments/dnb/operation_store.py:/app/operation_store.py:ro" \
  dethrottled-dnb:phase2-accepted-20261108

# 3. Fixture, core, REST gateway and MCP bridge
python experiments/dnb/fixture.py  # loopback fixture on 8090
DETHROTTLED_DNB=1 DETHROTTLED_BROWSER_SEARCH_URL=http://127.0.0.1:19888 \
DETHROTTLED_CRAWL4AI_URL=http://127.0.0.1:19888 \
DETHROTTLED_ADAPTER_CIDRS=127.0.0.1/32,::1/128 \
uvicorn dethrottled.server:app --host 127.0.0.1 --port 19984
MCP_BACKEND_URL=http://127.0.0.1:19984 uvicorn adapters.rest_gateway:app --port 19983
MCP_BACKEND_URL=http://127.0.0.1:19984 uvicorn adapters.mcp_server:app --port 19982

# 4. The gates
python experiments/dnb/phase3_check.py --rotate --worker-container p3-worker \
  --logs /tmp/p3/core.log /tmp/p3/gateway.log /tmp/p3/mcp.log --output /tmp/p3
python experiments/dnb/phase3_network_check.py --output /tmp/p3
```

## What this does not prove

- The live pilot is three paced pages and the soak is twenty reads; neither is a
  hostile-source campaign, sustained load test or full long-running memory study.
  Those remain phase-6 parity/load gates.
- Full 1.7.1 capability parity (all drive actions, downloads, selectors, research,
  PDF/OCR/Office/media integration) remains phase 6. ARM64 validation is also
  phase 6 and was not attempted here.
- A compromised adapter can reuse bearer tokens it legitimately sees, but it
  cannot mint a new identity. A compromised worker can read live cookie jars.
  Those are process-compromise boundaries; the adapter-peer gate and worker
  delegation do not remove them.
- The adapter-to-core hop is a private HTTP link. Operators must keep the core
  private, set `DETHROTTLED_ADAPTER_CIDRS` to the adapter peers, and use TLS or a
  private network if that link crosses an untrusted segment. The product does
  not prescribe a specific deployment topology.
- The lab allows internal loopback targets and disables filtering; those are test
  settings, not production defaults. The development worker must remain private.
