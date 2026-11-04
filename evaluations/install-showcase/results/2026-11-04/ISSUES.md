# Installation issues and original failures

## Q6A package-manager prerequisite

The first standard Docker installation stopped at `apt update`: the host's existing
signed Radxa repository changed Origin (`noble` to `Radxa`) and Label (`noble` to
`Freight`). The original failure was retained. Retrying accepted only Origin/Label
changes; signature checking was not disabled. Docker Engine and Compose then installed
through Docker's official Ubuntu ARM64 repository. This was a host prerequisite issue,
not a Dethrottled runtime failure. The stack CLI does not install system packages.

## Candidate deployment context

The first candidate managed-stack build failed because the API Dockerfile referenced
a nonexistent top-level `pdf-worker` directory. The PDF utility actually lives under
`docker/pdf-worker`. The failed wheel/log were retained privately, the incorrect COPY
was removed, and wheel validation now checks all Docker COPY source paths before
starting deployment. The corrected wheel passed 47 source checks. Only the affected
candidate builds were stopped; production containers were untouched.

## Nested package build inside the API image

The corrected context exposed a second issue: the API image copied source and packaging
metadata but not its own Dockerfile into `/app`. The nested wheel build correctly
refused an incomplete context. The Dockerfile is now included, and the package validator
checks that this self-build prerequisite is copied. The original failing log is retained.

## Repeated headed browser interaction

The first Q6A contract run passed 21/21. Reusing its session in the second run failed
three click checks (iframe, popup and checkpoint). A separate diagnostic confirmed
that the button was attached, visible, enabled, stable and received pointer events,
but Chromium timed out waiting for actionability. A previously opened popup had left
the selected tab in the background. The candidate now activates a tab before clicking
and on `switch_tab`, using Playwright's `bring_to_front` operation. The original
18/21 run and detailed diagnostics are retained; two subsequent pilot runs passed
21/21 each. Final repeated measurements follow image rebuilds with this fix.

Reference: https://playwright.dev/python/docs/api/class-page#page-bring-to-front

## Initial popup navigation race on ARM64

The rebuilt Q6A run passed 20/21: the popup click succeeded but `switch_tab`,
200 ms later, rejected its still-blank initial URL. A later tabs inspection showed
that the same tab had reached the allowed fixture URL. Tab selection now waits
within the caller's step/run deadline for creation and initial navigation; an
out-of-scope nonblank URL still fails immediately. Unit cases cover delayed creation,
blank navigation, forbidden hosts and timeout. The original failed run is preserved.

## Intermittent IndexedDB restoration

One szbox worker-restart check restored cookies/local/session storage but lost the
IndexedDB record. The on-disk checkpoint still contained it. A minimal test and five
further worker-restart restores recovered the original value; the underlying
intermittent driver/timing cause is not conclusively identified. The browser now
reads back IndexedDB immediately after restoring a context, before page scripts
run. A mismatch closes that context and retries up to three times. Continued loss
fails explicitly and preserves the original checkpoint, rather than claiming a
complete session. Fault-injection unit tests cover recovery and persistent loss;
the original failure and repeated real restores remain evidence.

## Immediate profile restart and port probing

A `media` shutdown followed immediately by `layout` startup refused port 19088.
The conservative bare bind probe could also reject recently closed POSIX TCP
connections in TIME_WAIT. It now uses POSIX SO_REUSEADDR for the availability
probe, which still rejects an active listener. Windows retains its conservative
probe because reuse semantics differ. Real socket tests cover both an active
listener and restart after a closed accepted connection. The failed profile
attempt is retained and the profile gate is repeated with the corrected manager.

## PyPI Simple-index propagation after release

Release upload succeeded, but the first actual installer still saw only versions
through 1.3.0 from the ordinary package index. The gate stopped; its stderr and
index response are retained. Once the index exposed 1.4.0, a separate fresh virtual
environment installed normally. This was an external index propagation delay;
no published package was overwritten. Both actual installation routes then passed.
