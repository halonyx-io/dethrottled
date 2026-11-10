# Phase 1 acceptance — 2026-11-08

**Status: complete for the local x86_64 DNB worker.** This closes its bounded-work,
cancellation and retry gate. It does not approve replacement of production 1.7.1,
claim native ARM64 readiness, or close public API/MCP integration and the remaining
phases. No release, publication or deployment was performed.

## Implementation

- Replace request-path extraction threads with two warm subprocesses in the same
  container, running upstream Crawl4AI scraping/Markdown. No second browser,
  model or service was added. Cancelled, timed-out, failed or malformed-output
  jobs terminate their process group and reap it before returning the slot.
- Per extractor: 12-second work deadline; 2-GiB virtual-address-space cap;
  eight-second additional soft CPU allowance with a 60-second hard lifetime CPU
  cap; recycle after 45 CPU-seconds. Native code may delay a Python soft-signal
  handler, so the wall deadline/hard lifetime cap remain authoritative. These
  limits are ceilings, not RAM reservations or minimum machine specifications.
- Bound browser admission to two active reads and four waiters. Queue wait is
  five seconds. Whole-request budgets include admission and context creation.
  Keep one-MiB HTTP input and eight-MiB acquired HTML limits; HTML compatibility
  remains a later release gate. Bound drive requests to six in flight (including
  its existing two execution slots), and retain its action/run budgets.
- Monitor actual ASGI disconnects for both read and drive. Kill extraction work,
  abandon cancelled browser work, and release admission after cleanup. Context
  creation and disposal have bounded cleanup. If cleanup cannot finish within
  three seconds, fail-stop the shared worker so its supervisor removes the
  process tree. This can interrupt other requests: it prevents permanent capacity
  loss, not all collateral failure.
- The acceptance lab used 4 CPU cores, 4 GiB container memory and 1,024 PIDs with
  restart enabled. These are test ceilings, not final deployment recommendations.
- Check completed/unknown/running drive operations before allocating a session
  for a retry. Reuse the existing durable mutation journal: completed actions
  replay recorded evidence; interrupted actions remain unknown and are not
  executed again. Reads deduplicate only while the scoped operation is in flight.

## Retry contract

Worker errors use a `detail` object with `code`, `retryable` and
`retry_after_seconds`. Transient refusals also send `Retry-After: 1`.

| Condition | HTTP | Automatic retry |
|---|---:|---|
| Read queue/pool/memory pressure or unexpected extractor exit | 503 | Back off; bounded attempts |
| Drive admission limit | 429 | Back off; bounded attempts |
| Same scoped read/drive operation still running | 409 | Poll/back off using the same ID |
| Changed payload under an existing operation ID | 409 | No |
| Unknown mutation outcome after cancellation/crash | 409 | No; inspect the external state |
| Extraction resource/output limits | 422 or 504 | No repeated automatic attempt on identical work |
| Browser or overall deadline | 504 | No repeated automatic attempt on identical work |
| Client disconnect | 499 in server handling | Caller abandoned the operation; no response delivery promised |

For transient read failures, clients should make at most two automatic retries,
honor Retry-After with jitter, then return control or choose another source.
In-progress polling uses the same operation ID; it is not permission to execute a
new mutation. These are client recommendations, not a claim that the server can
force an arbitrary client's retry count.

A read may execute again after its in-flight entry is removed; this is not
exactly-once processing or a durable read-result cache. Mutating drive actions
require a named session and operation ID for journal protection. Without one,
clients must not blindly repeat a timed-out action. Public API/MCP propagation
and policy integration remain later-phase gates; these are the private worker's
semantics, not a claim that every public response already carries these fields.

## Accepted evidence

[33 focused tests](phase1-tests.log) passed, covering real child-process reaping,
repeated two-slot cancellation, timeout/crash/CPU-exit classification, actual
memory-allocation refusal, oversized protocol output, replacement workers and
upstream extraction facts. Tests read the actual child's kernel limits. ASGI
regressions cover buffered/chunked body limits, disconnect preservation, partial
body abandonment, bounded hung creation/cleanup, overload and duplicate-operation
handling. They do not stress host memory or claim a hostile-browser sandbox.

The [wire harness](../../phase1_check.py) made real HTTP calls against isolated
fixtures and a signed lab worker. It verifies overload/backoff, cancellation while
both extractors are occupied, a busy JavaScript renderer, and mutation replay
safety after both disconnect and a genuine worker crash. Successful recovery reads
use a different caller identity. [Captured results](phase1-wire.json):

| Scenario | Observed result |
|---|---|
| Two active reads + four queued, then disconnect all six | Idle capacity and a healthy independent read in 0.832 s |
| Disconnect two active extractors | Both children killed/reaped; recovery plus healthy read in 1.626 s |
| Busy JavaScript renderer | 504 `browser_timeout`; recovery plus healthy read in 4.851 s |
| Disconnect after a fixture mutation | One mutation; retry refused, no duplicate; recovery plus healthy read in 0.798 s |
| Kill the worker during another mutation | Supervisor restart observed; healthy read succeeds; retry does not duplicate mutation |

Recovery timings include the subsequent healthy read, not only semaphore release.
These are single controlled observations, not latency/throughput benchmarks.
Image/source identities and lab budgets are in [provenance](phase1-provenance.json).

## Original failures retained

The wire test exposed a real problem: BaseHTTPMiddleware buffering obscured
`http.disconnect`. The old run failed its ten-second recovery bound. A pure ASGI
boundary now replays the bounded body once, then forwards the real disconnect
channel; both its regression test and wire recovery pass.

An early CPU-exit test exceeded its intentionally tiny wall limit; signal handling
was made explicit, with no core dumps and a controlled CPU-limit exit status.
The signed lab also caught a missing verifier dependency; it is now pinned, and
configured verifier/key checks run before readiness. The old browser-timeout test
was updated to assert the new 504/non-retryable contract rather than the old 200
failure body. Original logs remain private; they were not replaced by passing runs.

## What remains

Phases 2–3 contain partial, unaccepted navigation/identity work. Phase 4's two
inherited defects were reproduced and minimally fixed with focused checks, but
its full contract/documentation gate remains open. Browser/GPU selection, final
resource measurements, native ARM64, installation, full API/MCP/evidence parity,
long mixed-load testing and release/rollback gates remain pending. Full API/MCP-to-worker disconnect
propagation and durable-job cancellation are not certified by this worker gate;
they must be checked before end-to-end release/DPR claims. Earlier pilot
CPU/RAM figures do not describe this new two-extractor architecture automatically.
