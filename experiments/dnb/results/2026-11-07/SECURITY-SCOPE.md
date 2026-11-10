# Scoped reuse: security review and decision

**Choose reused contexts with fresh pages for ordinary scoped reads.** Retained-tab
reuse remains explicit. Anonymous/missing-session reads remain fresh contexts.
Production 1.7.1 remains unchanged; this is a local prototype, not a release.

The previous implicit session and absent security-scope label were insufficient.
Reuse now requires trusted owner + explicit session + explicit security scope,
with exact origin, network policy, supported browser configuration and page mode
also partitioning the key. Gateway credentials authorize identity selection;
public clients must never receive that credential or control trusted identity
headers. Automatic verified API/MCP forwarding is still a production gate.

The pool retains four contexts at most, expires after 60 idle seconds, recycles
at 200 reads, evicts idle entries under memory pressure, and refuses new work
while pressure persists. Active operations are never evicted or run concurrently
in one context. The pressure threshold is a conservative admission policy, not
an experimentally proven OOM guarantee. No host memory stress was induced.

## Same-workload comparison

Two blocks per variant, reverse order in the second block. Each block reads the
same article, long HTML and redirect fixtures, with 0.5-second settling. No live
providers. Six reads and 16 fact checks per variant. All facts survived, and
Markdown hashes matched across variants for every target.

| Variant | Median latency | Median CPU-seconds / three reads |
|---|---:|---:|
| Fresh context + fresh page | 648 ms | 2.100 |
| Scoped context + fresh page | 614 ms | 1.269 |
| Scoped context + retained, parked tab | 597 ms | 0.870 |

The middle choice saves about **40% CPU and 5% latency** versus fresh contexts.
The final choice is faster still but saves only another ~17 ms of response time.
Fresh pages reset tab storage, globals and document history more cleanly, so the
middle choice is the normal-reading default. It is not the absolute CPU winner.
The fresh replacement is created before the old parked page closes, avoiding a
needless zero-page lifecycle transition. Both modes discard source DOM/timers
between reads; cookies/local storage/IndexedDB intentionally persist only in the
same explicit session/scope. Small samples establish direction, not a general
performance guarantee. Results are in [security-scope.json](security-scope.json).

## Adversarial and security tests

Real Chromium checks passed with both reuse modes:

- A and B use the same origin/session/scope/config concurrently; A sets cookies,
  local storage and IndexedDB while B reads clean state. After B writes its own
  markers, concurrent reads repeatedly see only each caller's own data.
- One caller changing scope, session, requested browser configuration or allowed
  hosts sees clean storage rather than the earlier session's markers.
- Public-only requests reject the internal fixture; anonymous requests do not
  acquire a reusable identity merely because a caller header exists.
- Redirects outside an explicit host scope are refused at egress, including drive.
- Synthetic HaGeZi fixture rules block direct/redirect targets and subresources,
  while legitimate article facts remain readable.
- The selected default was tested cold then warm through HTTP: fresh pages,
  context reuse only after the first scoped request.

**36 prototype regressions and 13 existing proxy/update regressions passed.**
Deterministic tests prove resolution happens once in the connector and only the
validated numeric IP is dialled. Loopback, metadata, IPv6 loopback and mixed
public/private answers are refused before connection. Expiry/capacity/pressure,
active-use protection, cancellation, failure cleanup and key partitioning have
focused tests. Pressure tests inject the condition rather than stress the host.

## Defects actually found and fixed

The native prototype previously validated DNS separately from the connection;
that was not DNS pinning. A small optional connector hook in the existing gate
now supplies resolve/validate/pin dialing. The ordinary gate path is unchanged
when no connector is supplied, and its regression tests pass. Render/drive use
the policy connector even with filtering disabled. No new container/dependency.

Parking in `finally` could replace a navigation failure with an error from cleanup.
Failed operations now destroy their context without parking, preserving the
original error. The adversarial redirect test caught this; a regression covers it.

Browser routing did not intercept the redirected request in the controlled probe.
Allowed-host enforcement therefore also runs before DNS/dial in the gate. Explicit
prototype host lists are strict egress boundaries, including assets; callers must
include required CDN hosts. This strengthens 1.7.1's navigation-only list and is an
intentional **compatibility gate**, not an unnoticed production contract change.
The initial redirect fixture used Chromium's forbidden port 1; it was corrected
so the test exercises DNB's policy rather than Chromium's unsafe-port refusal.
Original failures are retained privately; no timing blocks ran before these fixes.

## Remaining boundaries

Pinning protects proxy-mediated HTTP(S)/WebSocket connections, not every possible
browser side channel or a complete browser sandbox. Current effective browser
configuration is narrow and fixed; unsupported settings still fail validation.
No authenticated external app, live hostile source, full mixed-load suite or
native ARM64 test was run here. Keep those and verified owner forwarding as
replacement gates. The default-selection change follows the explicitly measured
fresh-page path; the measured render implementation is unchanged. Source/image
identities are in [security-provenance.json](security-provenance.json).
