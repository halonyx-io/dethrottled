# Caller-isolated DNB reuse — 2026-11-07

**Decision:** use a retained, parked tab/context for authorized same-owner renders
in the prototype. Anonymous acquisition remains fresh. Production 1.7.1 and its
API/MCP identity forwarding are unchanged. Rust remains deferred.

This is a small controlled gauge, not a new release or broad anti-bot benchmark.
One x86_64 host, software rendering, the same frozen reference images and default
0.5-second settle as the [initial pilot](../2026-11-06/REPORT.md).
No live-provider traffic was used.

## What changed

A small in-memory pool is keyed by trusted owner, session, exact origin, network
policy and page mode. An internal worker bearer is required to select an owner;
unauthorized owner selection returns 403. This is a trusted gateway contract,
not authentication of public callers: future API integration must derive owners
from verified claims, never trust client-supplied identity headers or IP addresses.
Without an owner, the context is created and destroyed for that request.

At most four retained contexts, 60-second idle TTL, a ten-second reaper and
recycling after 200 reads. Idle entries are destroyed on eviction, never reassigned.
Busy same-session use returns 409; active capacity exhaustion returns 503.
Failures discard the context. Cancellation during context creation is cleaned up.
Worker shutdown destroys the pool. Render contexts remain separate from drive.

Two reuse modes were compared. Fresh-page mode retains the caller's context but
recreates pages. Persistent-tab mode retains the tab and navigates on each read.
The selected implementation **parks that tab on `about:blank` after capture**,
releasing the source DOM and its timers while retaining same-owner browser storage.
Popups are closed. The name `persistent` refers to the tab/storage, not retaining a
live website between reads. No global cookie sharing or cross-caller sanitization.

## Measurements and choice

First, three rounds of four reads per variant, with order changed between rounds.
All 48 reads retained all three known facts (36 checks per variant) and generated
identical Markdown. CPU is container cgroup usage time, not wall time.

| Initial variant | Median response | Median CPU seconds / four reads |
|---|---:|---:|
| Frozen 1.7.1 renderer | 632.6 ms | 0.903 |
| DNB fresh anonymous context | 631.5 ms | 2.782 |
| Retained context, fresh page | 627.3 ms | 2.262 |
| Retained tab, source left live | 546.7 ms | 0.599 |

Creating a fresh page saved about 19% CPU, with no convincing latency gain.
Retaining the tab saved more, but leaving source scripts running between calls
would be a poor default. The selected parked-tab version was therefore measured
separately: three blocks of four retained reads, with four fresh-context controls.

| Final parked-tab check | Fresh controls (4 reads) | Parked reuse (12 reads) |
|---|---:|---:|
| Median response | 632.9 ms | 582.0 ms |
| CPU seconds / four reads | 2.667 | 1.178 (median of three blocks) |
| Known fact checks | 12/12 | 36/36 |

That is **56% less CPU and 8% lower latency** than fresh contexts on this fixture.
The response saving is about 51 ms, not a threefold speedup. All requests still
include the half-second settle. Parking costs CPU compared with leaving the page
live; that tradeoff was deliberately accepted. Reference and final parked runs
were separate phases, so this does not establish superiority over 1.7.1 generally.

Warm state uses memory. In the initial full-page comparison, candidate post-phase
snapshots ranged 614–731 MiB with multiple retained contexts; the two reference
workers together were about 746 MiB. After parking, a single post-run snapshot was
389 MiB versus 741 MiB for the reference pair. These are snapshots, not comparable
peak/median memory benchmarks or minimum hardware requirements. The image remains
approximately 2.24 GiB logical size; the API and optional document workers are
unchanged. Scope, expiry and recycling matter more than a flattering RAM headline.

## Isolation and lifecycle checks

Real-browser assertions passed for both reuse modes:

- Same-owner cookies, local storage and IndexedDB survive navigation.
- Other owners and other sessions cannot see those stored markers.
- Fresh pages reset session storage; the retained tab preserves its own.
- Anonymous requests do not share storage.
- LRU eviction destroys the old owner's state instead of reassigning it.
- Concurrent operations cannot mutate one session's page at the same time.
- Requests without trusted worker authorization cannot select an owner.
- A real worker restart clears the render pool (initial four-variant run).

The parked version repeated the storage/isolation checks. Its timer fixture made
zero additional tick requests while parked; an explicit persistent drive control
then made nine, proving the timer fixture actually ran when left active. This
checks source-page timers, not every possible service-worker background behavior.

**26 prototype regression tests passed**, including pool capacity, busy-state
protection, expiry, eviction, reuse-count recycling, failure/cancellation cleanup,
identity partitioning and the selected default. Existing search/drive source was
not modified. This follow-up did not rerun broad live or ARM64 suites.

## Evidence and limitations

[Four-variant measurements](results.json) and
[final parked measurements](parked-results.json) preserve request timings, CPU,
fact/hash checks and isolation outcomes. Image/source identities are in
[provenance.json](provenance.json). Final default selection chooses the explicitly
measured persistent-tab path; its rendering implementation is unchanged from that
measurement. The original images are retained locally for comparison.

The first harness run lost its in-memory measurements when the restart readiness
probe received a transient connection reset. It was fixed to retain measurements
before restart and wait for health; one complete comparison was repeated. The
original failure log remains private. A CPU export initially labelled raw
microseconds as seconds; the original counters were retained and converted by
1,000,000 without rerunning acquisition. The corrected benchmark now applies that
conversion directly. Neither failure was a source acquisition/isolation defect.

This is enough evidence to choose the next prototype behavior. Remaining release
gates include verified API/MCP owner forwarding, realistic mixed traffic, native
ARM64, broader source quality and failure containment. Fixed fixture reuse is not
proof of hostile-source recovery, universal cache freshness or background-worker
quiescence. The current public API continues to use the anonymous path until a
trusted identity is forwarded; no improvement is claimed for production users yet.
