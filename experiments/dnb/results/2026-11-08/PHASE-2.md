# Phase 2: document scope and usable assets

Accepted for the isolated **x86_64 DNB worker**, 2026-11-08. Production remains
Dethrottled 1.7.1. No release, deployment, main-branch change or version bump.

## What changed

The earlier prototype used an egress allowlist for both documents and assets.
It could block legitimate CDN JavaScript/CSS. The replacement separates:

| Traffic | Public scope | Explicitly enabled internal scope |
|---|---|---|
| Documents, frames, popups, navigation redirects | `allowed_hosts`, if supplied | Explicit document hosts; initial URL host when omitted |
| Assets, including worker fetches | Any public host by default | Document hosts plus trusted additional asset hosts |
| Explicit asset list | Restricts assets to document/initial hosts plus that list | Same; never learned from page content |
| Destination IP and filtering | Validate DNS answers, pin numeric connection, apply HaGeZi | Same pinning/filtering; private IPs require operator opt-in and host authority |

`asset_hosts` is an optional signed worker-delegation claim, not a public API/MCP
argument. `None` means the defaults above; an empty list explicitly restricts
assets. Read reuse keys include this policy. An active named drive session cannot
silently change it: use a new session after HTTP 409.

One CDP policy client intercepts document requests at Chromium's request boundary.
New page/iframe/worker targets are paused before configuration and then resumed.
The existing proxy still owns DNS/IP admission and filtering. TLS, cookies and
normal browser loading remain Chromium's responsibility. Service workers remain
enabled; no alternate HTTP client fetches browser documents.

The client uses public [CDP Target](https://chromedevtools.github.io/devtools-protocol/tot/Target/)
and [Fetch](https://chromedevtools.github.io/devtools-protocol/tot/Fetch/) commands
through an ephemeral loopback debugging socket. The browser connector explicitly
denies that socket even for internal scopes. No additional service or dependency
was added: aiohttp is already installed with the pinned extraction stack. Loss of
the policy transport closes the browser; existing supervisor recovery still applies.

Drive construction now also closes contexts and their gates when page creation or
policy installation fails. This closes an ownership gap exposed by the new setup.

## Evidence

- **60 focused regressions passed**: extraction/lifecycle, pool ownership, DNS
  rebinding/mixed answers, scoped assets, immutable active sessions, denied control
  sockets, policy transport loss and failed-construction cleanup.
- The earlier [signed HTTP lifecycle gate](phase2-lifecycle-regression.json) also
  passed again: queued/active cancellation, extractor termination, stalled render
  recovery, mutation non-replay and an actual supervised process-crash restart.
  This separate replay used a private bridge and loopback-published lab ports;
  the scope gate below remained offline and published no ports.
- [Real browser results](phase2-wire.json) exercise Chromium on an internal Docker
  network with no upstream route. The final run used the built image's default
  non-root `browsersearch` user, with filtering enabled and a synthetic 10,000-rule
  fixture. Both actual ASGI `/crawl` and `/drive` handlers retained the CDN fact.
- Predefined origin and JavaScript-inserted CDN facts survived, CSS applied, and a
  host-only secure/HttpOnly origin cookie did not appear on CDN requests.
- A redirect chain reused its origin TLS connection. Forbidden navigation was
  denied on an existing page and a fresh page in the same context. Parent evidence
  survived a blocked frame redirect. Allowed popups still loaded; forbidden popup
  redirects did not reach their destination.
- A real service worker activated, fetched the allowed CDN, and supplied a
  navigation redirect which was blocked before the forbidden destination.
- Public explicit asset lists and internal defaults blocked an undeclared CDN;
  explicit trusted CDN authority restored the JavaScript fact.
- Separate destination listeners observed **0 TCP accepts each** for forbidden
  navigation, the synthetic adblock domain and the private redirect. These are
  destination-side counters, not inferences from a browser error string.

The browser gate's elapsed time is the entire small test, **not** a retrieval
latency benchmark or a speedup claim. Exact image, source hashes and test setup are
in [provenance](phase2-provenance.json). [Unit output](phase2-tests.log) is retained.

## Failures retained and fixed

The [original failing fixture requests](phase2-initial-failure.json) show that the
first overlapping route/CDP approach blocked the redirect on an existing page but
let it escape from a newly created page. Filtering was loaded in this preserved
probe; the failure was navigation scope, not adblock. Re-enabling interception was
insufficient. The final implementation removes the overlapping routing owner.

Development also caught a test-only missing filter initialization, a nested CDP
attachment that stalled, and a service-worker probe which ran in Patchright's
isolated world. The latter was replaced with signals emitted by the page's own
script. Endpoint testing exposed duplicate launch wrapping across imports; the
installation marker now lives on the browser class. Original development logs
remain in private lab evidence; no failed probe is counted as a passing gate.
The first lifecycle-replay setup used an internal Docker network which did not
publish its requested loopback ports on this engine; no request reached the
worker. Recreating only that lab on a private ordinary bridge allowed the frozen
wire harness to run and pass. No source change was needed.

Five old pool tests still assumed the removed bearer/header protocol. They now
exercise verified request-state claims; they do not certify signature verification
or automatic gateway integration, which belong to phase 3.

## Reproduce

From the prototype checkout, with Docker and a built matching image:

```sh
DNB_IMAGE=dethrottled-dnb:phase2-accepted-20261108 \
  experiments/dnb/phase2_lab.sh /tmp/dnb-phase2
```

The script creates and removes only its own lab container/network. It publishes no
ports and mounts no production state. The test subnet `11.253.72.0/24` must be free;
a globally classified address tests the real public-IP gate without granting a
private-network exception. The internal Docker network prevents upstream access.
The generated fixture certificate's SPKI is trusted only by the test launch.

## What this does not prove

This is a controlled local scope acceptance, not proof of hostile-source recovery,
universal browser compatibility, or a new CPU/RAM figure. Synthetic block rules
test wiring, not HaGeZi coverage. HTTP/1.1 keep-alive was exercised; HTTP/2
coalescing, live sites, long-running load and ARM64 remain release/parity gates.

Phase 3 must finish verified gateway forwarding, authenticated owner/session and
checkpoint-policy binding, and the signed protocol fixtures. Phase 4 still needs
its complete compatibility evidence/docs. Phases 5–6 cover browser/GPU choice,
resource measurements, full 1.7.1 capability parity, packaging and release approval.
The development worker must remain private until those gates pass.
