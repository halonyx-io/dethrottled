# Native ad/tracker filtering

Unreleased candidate: this feature is not in the published 1.5.2 release.

Dethrottled uses **HaGeZi Multi PRO** with one operator switch:

```sh
DETHROTTLED_ADBLOCK=1  # default: filter and maintain the list
DETHROTTLED_ADBLOCK=0  # no filtering and no list-update activity
```

For managed installations, set the variable before `dethrottled stack up`, or in
the checkout's `.env` before recreating the stack. Rebuild updated images and
recreate the API, browser-search, SearXNG and Crawl4AI when upgrading to this
feature. The number of services and public ports is unchanged. Existing data and
model volumes are retained. `stack down` also preserves the list-cache volume.
Standalone Python uses the same switch and its normal data directory.

## Acquisition coverage

| Path | Enforcement |
|---|---|
| Direct HTTP, RSS, optional discovery-provider calls | Guarded requests sessions; redirects checked before sending |
| curl_cffi fetch/discovery and scoped identity sessions | Domain check on every redirect hop, preserving native TLS |
| DDGS native client | Guarded native HTTP boundary and redirects |
| Managed SearXNG engines | Guarded pinned asynchronous curl_cffi client and redirects |
| Managed Patchright search, `/drive` and headed recovery | Per-context in-process HTTP/CONNECT gate |
| Managed Crawl4AI browser | Same gate, chained through its existing egress-pinning proxy |
| Browser subresources, redirects, frames, popups, WebSockets and worker traffic | Browser connections pass through the context gate |
| Documents, archives, images, audio and downloaded attachments | Acquisition uses the corresponding HTTP/TLS/browser transport; local parsing is unchanged |
| Captions | Guarded transcript HTTP session |
| Format, layout and speech conversion | Uploaded bytes are processed locally; no independent source acquisition |
| Offline HTML-to-PDF worker | Already offline; all browser network access remains refused |

The browser gate runs on the worker's existing event loop and binds to loopback
only. It adds no separately managed service, process, container or dependency.
TLS remains encrypted between Chromium and the destination. The implementation
preserves existing scope/public-target checks and never retries around an upstream
proxy's refusal. It does not inject page JavaScript, disable service workers or
install a cosmetic ad blocker.

Matching checks whole DNS labels and their parents, including normalized IDNs.
IP literals, localhost, local names and configured internal RPC origins retain
existing behaviour and security checks. An RPC exemption does not carry across an
external redirect or into a content-fetch identity session. Search choices are
not reranked or removed, and extracted text is not deleted based on ad phrases.
A selected source can therefore be refused explicitly when fetched.

## Updates and availability

The requested [HaGeZi list](https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/adblock/pro.txt)
contains domain anchors. Dethrottled parses those directly rather than assuming a
separately generated format is equivalent. The official raw GitHub copy is a
fallback for the same list. One API updater maintains an atomic persistent
snapshot in managed Compose; other workers read it and publish small aggregate
observations. Standalone processes maintain their own cache.

The background updater checks approximately every 24 hours, including during
long-running operation. It uses ETag/Last-Modified validators when supplied.
Failed checks retry after five minutes without replacing working rules. Worker
readers notice a new snapshot within approximately 30 seconds. Size, header,
syntax, advertised entry count, checksum and catastrophic-count-drop checks
reject corrupt or unsupported updates. A schema change is reported rather than
silently dropping unrecognized rule types. Downloads have size and time bounds.

Startup never waits for an upstream download. **Until valid rules are loaded,
filtering is unavailable and acquisition is allowed**, with existing network
security still enforced. Offline operation retains the last valid cached/in-memory
rules. A corrupt disk cache is reported; existing in-memory rules remain active.
A restart needs a valid cached copy or a successful download. Disabling filtering
keeps its saved cache but starts no updater or browser gate.

## Diagnostics and agent behaviour

`/v2/status`, `/v2/capabilities` and `/stats` expose `adblock`: enabled/available
state, rule count, source/hash, last check/update, errors, counters and recent
managed-worker observations. Browser health and `/drive` also report their filter
state. Missing/stale worker observations are not proof of filtering coverage.
Counters are process observations rather than durable usage accounting; browser
counts are refused connection attempts, including Chromium retries. Per-drive
blocked-domain events are bounded, omit URL paths/query strings and are not logged
individually. Old process counter files are pruned.

A refused fetch includes `policy_blocked: "adblock"` and a failure reason beginning
`adblock_blocked:`. Its workflow stops and suggests no transport/browser bypass.
Agents should report the refusal or choose another relevant source. The switch is
an operator setting, not a per-request escape hatch. Discovery availability and
content quality remain separate from filter availability.

## Limits and tradeoffs

This is domain filtering, not a network firewall or universal ad removal. It
cannot distinguish legitimate content from tracking on the same hostname,
inspect ads already embedded in first-party HTML, or classify encrypted payloads.
It does not purge retained documents, corpus passages or search caches. Existing
retained evidence can still be read without new outbound acquisition.

The supported guarantee is for the shipped acquisition clients and managed
workers. A remote/unmodified renderer, externally attached browser context,
custom plugin or third-party hosted provider's own subsequent requests cannot be
controlled by this API. System/package/model downloads, arbitrary subprocesses,
browser-internal maintenance and WebRTC/other non-HTTP protocols are outside the
web-acquisition filter. HTTPS tunnelling uses TCP; proxying can affect connection
reuse/HTTP3 behaviour and needs the measured tradeoff, not a universal speed claim.
Custom upstream HTTP proxies can be chained; unsupported SOCKS/HTTPS proxy
configurations fail explicitly when filtering is enabled instead of silently
bypassing the filter.

HaGeZi can block a hostname needed by a legitimate page or a bot challenge.
There is no hidden allowlist, alternate profile or automatic bypass. Investigate
the reported domain and, if necessary, disable the switch and recreate the managed
workers. Successful local controls and a small live smoke do not establish zero
breakage across the web. See the [evaluation and resource results](../evaluations/adblock/README.md).

## Attribution and license

The list is maintained by [HaGeZi](https://github.com/hagezi/dns-blocklists) and is
published under [GPL-3.0](https://github.com/hagezi/dns-blocklists/blob/main/LICENSE).
Dethrottled's filtering implementation is its own code. The list is downloaded at
runtime rather than bundled or relabelled as MIT. The original list headers are
retained in its cache; an accompanying `license.json` records attribution and the
[bundled upstream license text](../src/dethrottled/licenses/HAGEZI-GPL-3.0.txt).
Redistributing downloaded list data requires preserving its upstream licensing.
