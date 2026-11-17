"""Public ("native") browser lane, 1.9.0.

A native-lane context has no proxy. Chrome connects by itself, so HTTP/3 works:
Indeed read 6 times in 6 natively, and was refused 3 times in 3 through the
CONNECT gate (web-bench browser-settings-ab, round 5). What the gate did is
enforced elsewhere, below the browser:

* Addresses. The public Chrome runs as its own UID, and the worker's nftables
  table (egress_firewall) lets that UID reach public addresses and the DNS
  filter only. That covers every protocol: HTTP, QUIC, WebSockets, WebRTC and
  workers. It holds whether adblocking is on or off.
* Names. The DNS filter (dns_filter) is the container's only resolver. It
  answers NXDOMAIN for HaGeZi domains and never returns a non-public address.
  Chrome's secure DNS is off by policy.

Nothing in the page's traffic is intercepted. Playwright's WebSocket routing
was tried here and crashed NSE India's app (browser-settings-ab, round 7).
This module only records adblocked requests per context, so read reports and
counters stay as complete as they were with the gate.
"""
from __future__ import annotations

import time
from collections import deque

try:
    from . import adblock
except ImportError:  # inside the browser image, modules are flat
    import dethrottled_adblock as adblock


async def install(context, events=None):
    """Mark a native-lane context and record its adblocked requests."""
    events = events if events is not None else deque(maxlen=100)

    def failed(request):
        domain = adblock.FILTER.match(request.url)
        if domain and "NAME_NOT_RESOLVED" in (request.failure or ""):
            adblock.FILTER.blocked(domain, "browser")
            events.append({"domain": domain, "kind": "browser", "at": time.monotonic()})

    context.on("requestfailed", failed)
    context._dethrottled_adblock_events = events
    context._dethrottled_lane = "native"
    return events
