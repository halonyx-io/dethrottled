# Phase 3 plan: verified identity and automatic gateway integration

Planning checkpoint, 2026-11-08. No source, test, production, package or release
change is made by this document. Checkout: `prototype/dnb`, HEAD `9ad5fa3`.
Production remains Dethrottled 1.7.1.

This plan answers the three phase-3 gaps named in
[PHASE-2.md](PHASE-2.md:116): verified gateway forwarding, authenticated
owner/session and checkpoint-policy binding, and signed protocol fixtures.

## 0. Requirement mapping (README phase 3)

| README requirement | Plan item | Status |
|---|---|---|
| Agents reach safe reuse automatically without choosing trusted owner headers | `authorize()` rejects `X-DNB-*`; adapters set identity; e2e drive/read with no owner header | Covered |
| Derive owner, session and security policy from the gateway's verified claims | `claims["namespace"]` -> delegation `sub`; adapter-derived session; worker `session_owners` binding; scope/public-only/asset policy from claims | Covered |
| Reuse partitioned by caller, session, scope, config and policy | Existing `pool_key`; phase-3 adds cross-caller and cross-scope assertions | Covered |
| Anonymous/insufficiently scoped requests remain isolated | Existing anonymous fresh-context path; regression test | Covered |
| Short-lived, integrity-protected delegation bound to audience, operation/request, owner, session, scope and policy | Existing EdDSA JWT with `aud`, `jti`, `sub`, `session`, `scope`, body/path/method digest; phase-3 tests the full matrix | Covered |
| Separate admission credentials from signing authority | Bearer registry vs Ed25519 delegation key; adapters never hold the private signing key | Covered |
| Prefer gateway-only private signing and worker public verification | The core API is the gateway to the private worker; only it holds the private key. Adapter signing is deferred because the core rewrites the final body (`public_only`, `evidence_namespace`) after the adapter hop | Covered, documented |
| Standard mechanism, no custom crypto and no extra operator profiles | EdDSA JWT already in use; no new crypto, secret or profile | Covered |
| Carry verified identity through REST, MCP and autonomous escalation | REST and MCP e2e plus an escalation case (search/fetch -> browser fallback) | Covered |
| Retain bounded reuse, expiry, request limits, memory-pressure eviction, exclusive context use | Phase-1/phase-2 focused regressions plus phase-3 cross-caller gate | Covered |
| Exit gate: real API/MCP cold and reused paths | `phase3_check.py` runs uvicorn over real HTTP, not only TestClient | Covered |
| Exit gate: tamper, expiry, wrong aud/scope, spoofed headers, replay/idempotency, rotation, cross-caller storage | Section 3 matrix | Covered |
| Exit gate: logs expose no secrets | Redaction test over captured logs and error bodies | Covered |

One leaked admission credential must not select every cookie jar: the registry
namespace is part of every owner and session key, and the new worker
`session_owners` binding rejects a session created under a different owner even
if its id is known. The e2e gate tests exactly that case.

## 1. Trust boundaries and claim flow

| Hop | Credential / assertion | Verified by | Authority |
|---|---|---|---|
| Agent -> REST gateway or MCP bridge | Bearer token | `Registry.verify()` in `dethrottled_access` | Adapter; revocation and scopes |
| Adapter -> core API | Forwarded caller credential in `X-Dethrottled-Caller-Authorization` | Core `CallerIdentityMiddleware` re-verifies the same registry | Core, independently; adapter is the identity authority |
| Core API -> DNB worker | Short-lived EdDSA JWT in `X-DNB-Delegation` | Worker `delegation.verify()` with `DNB_TRUST_PUBLIC_KEY` | Core is the sole minter |
| Worker -> page | Existing phase-1/2 network, scope and admissibility gates | Worker and Chromium CDP policy | Unchanged |

Decisions:

1. **The core API remains the only minter of worker delegation.** It alone knows
   the body, path, operation and effective policy. Signing keys stay with the
   core; the worker gets a public key file only and reads it per admission.
2. **Adapters remain the identity authority.** They authenticate network agents,
   derive `namespace`/scopes from the registry and forward the credential. The
   core re-verifies it; it does not trust a bare owner header.
3. **Phase 3 hardens the adapter hop with a trusted-peer gate rather than a new
   shared secret.** The core accepts `X-Dethrottled-Caller-Authorization` only
   from `DETHROTTLED_ADAPTER_CIDRS` (default loopback). A LAN agent that reaches
   the core directly cannot assert identity. This keeps one credential store and
   avoids moving signing material into stdlib-only adapters.
4. **Clients never sign delegation and never set `X-DNB-*` owner fields.** The
   worker already rejects those fields with `untrusted_owner_headers`; phase 3
   proves it end to end.
5. **Local/CLI callers use the same registry credential path.** No implicit local
   owner bypass is added.
6. **Do not modify the frozen `browser-search/service.py`.** Owner binding is
   enforced in the DNB worker wrapper, so phase-6 reference comparison is
   unaffected.

### Why not a signed adapter assertion now

A second Ed25519 key pair would move private signing material into the adapters,
which are deliberately stdlib-only, and duplicate key distribution. A separate
HMAC secret would add another long-lived secret without removing the
compromised-gateway residual risk. The trusted-peer gate plus independent
re-verification gives the same property for this deployment: clients cannot
forge identity, and the core only accepts the hop from a configured adapter
peer. A signed adapter assertion remains a documented future hardening for a
deployment where adapters and core are in different trust domains.

## 2. Threat model

| Attack | Hop | Control | Residual |
|---|---|---|---|
| Stolen bearer used by another agent | Agent -> adapter | Registry revocation, scope check, admission quota | Until revoked; owner is the token namespace |
| Forged `X-Dethrottled-Caller-Authorization` from LAN | Agent -> core | Trusted-peer CIDR gate, registry re-verify, fail closed | A compromised adapter host is inside the boundary |
| Forged `X-DNB-Delegation` | Core -> worker | EdDSA verify, 60 s window, aud/iss/path/method/body digest | Core signing key compromise |
| Token replay with different body/path | Core -> worker | Body digest, path/method claims, 60 s expiry | Same body within 60 s is idempotent by design |
| Concurrent duplicate read | Core -> worker | Existing `OPERATIONS` in-flight guard | Completed reads may recompute |
| Drive replay / unknown mutation | Core -> worker | Existing mutation journal, payload fingerprint, `operation_in_progress` / `operation_conflict` / `drive_outcome_unknown` | Journal is process-local; restart discards it (documented) |
| Cross-owner session or checkpoint reuse | Worker drive store | New `session_owners` binding: first owner wins, mismatch 403 | Session id leak to the same owner is not a boundary |
| Checkpoint scope change | Worker drive store | Existing scope/public-only match plus owner binding | Frozen checkpoint format unchanged |
| Key rotation leaves old token valid | Core -> worker | Public key file reread per admission; no cached verifier | In-flight requests finish under the old key |
| Token/claim leakage in logs or errors | All hops | Generic error codes, redaction test, no header/token logging | Process memory/worker compromise |
| Internal target reached through the browser | Worker -> network | Phase-2 DNS pinning, filtering, scope and CDP policy | Unchanged; not reopened here |

## 3. Test plan (failing first, then green)

Every row maps to a phase-3 exit gate from `README.md`. Unit tests extend
`tests/test_dnb_delegation.py`; worker tests extend `experiments/dnb/test_dnb.py`;
end-to-end tests use the new `experiments/dnb/phase3_check.py`.

| Gate | Test | Level |
|---|---|---|
| Tamper | Modified signature, body, path, method, `aud`, `iss`, `exp`, `nbf`, missing claim, oversized host list, bad `asset_hosts` | Unit + e2e |
| Expiry | Valid signature with `exp` past, `iat` future, window > 60 s | Unit |
| Wrong audience/scope | `aud != dnb`, scope not in registry, wrong `public_only` | Unit + e2e |
| Spoofed headers | Client sends `X-DNB-Owner/Session/Scope/Page/Allowed-Hosts/Operation-Id` | Worker unit + e2e |
| Adapter trust | Forwarded identity header from an untrusted peer rejected; trusted peer accepted; absent header stays anonymous | Middleware unit |
| Replay / idempotency | Same drive `operation_id` + same body replays; different body 409; unknown outcome not replayed; read token replay with different body rejected | Worker + e2e |
| Rotation | Replace public key between calls; old token invalid, new token works, invalid key fails readiness | Unit + e2e |
| Cross-caller storage | Tokens A and B read the same origin; cookies/storage/checkpoints never cross; A's session id used by B -> 403 | E2E |
| Log redaction | Capture core/worker logs and error bodies; assert no token, authorization or claim substring | E2E |
| Automatic forwarding | REST search/fetch and MCP crawl/drive produce verified delegation with no caller opt-in | E2E |
| Autonomous escalation | `search`/`fetch` browser fallback carries the same verified `sub`/session/scope; no fresh anonymous identity appears | E2E |
| Reuse partition | Same caller reuses only when scope/config/origin/policy match; a changed scope or config gets a fresh context | E2E |
| Leaked credential | Token A with a known B session id cannot open B's checkpoint or drive session; A can still use its own | E2E |
| Cold and reused | Same owner reuses context; different owner gets a fresh context; counters prove it | E2E |
| Phase-1/2 regression | Existing focused commands from PHASE-1/PHASE-2 acceptance records | Worker |

Signed protocol fixtures: generate tokens during tests from an ephemeral key and
store the verification matrix plus JWKS/public-key fingerprint in
`results/2026-11-08/phase3-fixtures.json`. No private key or bearer is committed.

## 4. File-change list

New:

- `experiments/dnb/results/2026-11-08/PHASE-3-PLAN.md` (this file)
- `experiments/dnb/phase3_check.py` — end-to-end REST/MCP harness over real HTTP
  (uvicorn core, real worker, adapter apps) with two tokens and retained
  JSON/log evidence
- `experiments/dnb/test_phase3_identity.py` — worker owner-binding and adapter-gate
  tests that do not need Chromium
- `experiments/dnb/results/2026-11-08/PHASE-3.md`, `phase3-wire.json`,
  `phase3-tests.log`, `phase3-provenance.json`, `phase3-fixtures.json`

Changed (minimal, behavior-gated by `DETHROTTLED_DNB=1`):

- `src/dethrottled/delegation.py` — trusted-peer check in
  `CallerIdentityMiddleware`; helper for CIDR parsing; no secret logging
- `experiments/dnb/dnb_service.py` — persisted `session_owners` sqlite binding,
  owner check before `/drive`, delete on close, counters in `/dnb/status`
- `tests/test_dnb_delegation.py` — extend verification matrix and rotation
- `experiments/dnb/test_dnb.py` — worker owner-binding cases
- `experiments/dnb/README.md` — phase table and current-work line (after green)
- `docs/DOCUMENTATION-INVENTORY.md`, `docs/documentation-inventory.json` —
  add the new evidence and plan files only when they land
- `.env.example`, `docker-compose.yml` — document
  `DETHROTTLED_ADAPTER_CIDRS` and `DETHROTTLED_DNB_STATE_DIR`; default remains
  loopback and the existing DNB data directory

Explicitly unchanged: `browser-search/service.py`, public REST/MCP arguments,
1.7.1 defaults and production compose. No new dependency: PyJWT/cryptography are
already the DNB extra; the adapters keep their stdlib credential module.

## 5. Sequence and stop points

1. Baseline: record `git status`, run the existing delegation tests and the
   focused phase-1/phase-2 unit commands; retain failures.
2. Add failing tests for the matrix in section 3; show the failures.
3. Implement the trusted-peer gate; tests 5-6 green.
4. Implement `session_owners` binding and counters; worker tests green.
5. Add `phase3_check.py`; run cold/reused, cross-caller, rotation, replay,
   spoofed-header and redaction gates against a real worker; retain JSON/logs.
6. Write `PHASE-3.md`; update README status and the documentation inventory;
   rerun phase-1/phase-2 focused regressions.
7. Stop for final review. No commit, push, tag, release or deploy.

Change units are logical review units. Per the goal guardrail they are left as one
uncommitted, reviewable diff; I will not commit unless you authorize it.

## 6. Unresolved questions and recommendations

1. **Adapter hop mechanism.** Recommendation: trusted-peer CIDR plus core
   re-verification for phase 3. Alternative: an adapter-signed assertion, which
   needs a second key and a crypto dependency in the adapters. Approve the
   recommendation or choose the alternative.
2. **Worker state file.** Recommendation: `owners.sqlite` under the existing DNB
   data directory (`DETHROTTLED_DATA_DIR/dnb`), overridable with
   `DETHROTTLED_DNB_STATE_DIR`; fail closed on storage errors. Approve.
3. **Read-token replay cache.** Recommendation: none. Reads are body-bound,
   short-lived and idempotent; the in-flight guard already prevents duplicate
   concurrent work. A persistent jti store would add state without a security
   gain for reads.
4. **Phase-3 acceptance without live hostile sources.** Recommendation: accept
   the local worker gate here; keep live-provider and parity evidence in phase 6,
   matching the phase-1/2 pattern.
5. **Checkpoint format.** Recommendation: do not change the frozen checkpoint
   format; bind ownership beside it in the worker store. This preserves phase-6
   parity and 1.7.1 rollback.

Approval needed on questions 1 and 2 before any source or test edit.
