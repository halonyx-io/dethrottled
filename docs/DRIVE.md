# Browser operation

`POST /drive` operates the existing headed Patchright browser. Use it when a
read needs controls, an export, application responses or visual inspection.
The API exposes bounded actions, not arbitrary JavaScript evaluation. Prefer
structured inspection for planning and actual pixels when appearance is evidence.

## Navigation recovery and access evidence

The browser keeps Patchright, the existing Chromium and optional real GPU. For
Reddit HTTP/S navigation, it seeds a host-scoped `cookiesEnabled=true` preference
only when absent, then waits up to five seconds within the navigation budget for
posts, and comments on thread URLs. Existing cookie values are preserved. Initial
navigation, explicit `goto` and checkpoint restoration use the same path.
`DETHROTTLED_BROWSER_RECOVERY=off` disables this recipe for comparison.

`navigation_recovery` reports the recipe, whether a cookie was added, readiness
outcome and timing. It contains no cookie value or browser credentials.
`access.status` distinguishes `challenge`, `login_required`, `http_error`,
`content_observed` and `unknown`. An action's `ok` means that action executed;
it does not mean the source answered the caller's question. `answer_verified`
and `source_complete` remain false. Long content can still contain pollution.

This recipe recovered a Reddit listing and a thread with real comment controls
in the [recorded comparison](../evaluations/drive-recovery/results/2026-11-02/REPORT.md).
It did not recover Crunchbase or G2. It is a measured site-specific compatibility
fix, not a universal challenge solver or an authenticated Reddit session.

## Sessions and the interaction loop

```sh
curl -sS http://127.0.0.1:8787/drive \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/","session":"source-task","allowed_hosts":["example.com"],"steps":[{"action":"snapshot","limit":10}],"screenshot":"failure"}'
```

Discover controls with a snapshot, perform the smallest justified interaction,
then inspect its result. Reuse `session` without a URL to continue the same live
DOM and browser state. Calls for a session are serialized. An unnamed navigation
returns a persistent `auto-*` session; reuse the returned ID. For one-shot work,
set `close_session=true`. A stateful call without navigation/session returns 422;
a missing session without a restorable checkpoint returns 409.

Live contexts expire after 30 idle minutes by default, with at most eight live
sessions. Auto sessions can be evicted before explicitly named sessions.
`checkpoint` retries a read-only state capture up to three times if navigation
detaches a frame; it never repeats the preceding action. It saves selected state for restoration after eviction/restart; it
is distinct from keeping a live page. Close a session explicitly when finished:

```json
{"session":"source-task","close_session":true,"steps":[]}
```

For automatic fetch recovery, reuse `read_plan.browser_session.id` and its
`allowed_hosts` to continue the same browser state. These reserved handles are
caller-scoped across REST and MCP; ordinary named sessions remain transport-private.
An automatic read's live page closes after five minutes unused; the handle then
restores cookies and storage from its checkpoint, not the page itself. See the
[read planner](READ-PLANNER.md) for selection and retention rules.

## Actions

| Action | Fields and meaning |
|---|---|
| `snapshot` | `selector` scopes visible nodes/controls; `limit` bounds entries; hints include ambiguity/index information |
| `goto` | Navigate to `url`, with `ms` action timing |
| `click`, `hover`, `check`, `uncheck` | Act on `selector`/`index` |
| `fill` | Replace with `value`; emits input and change |
| `type` | Sequential typing; `value` and `delay_ms` |
| `press`, `select` | Key or option in `value` |
| `wait`, `wait_for` | Delay with `ms`, or selector state in `value` (`visible`, `hidden`, `attached`, `detached`) |
| `text`, `html` | Bounded read using `selector` and `max_chars`; report actual size/truncation |
| `attr`, `count` | Attribute `name` or locator count |
| `url`, `title` | Current page identity |
| `download` | Click a real download control and parse the captured file |
| `network` | List captured same-scope XHR/fetch responses; `name="body"` reads `selector=response_id` |
| `checkpoint` | Save cookies, localStorage, IndexedDB, allowed-frame sessionStorage and history |
| `tabs`, `switch_tab` | Inspect tabs, then switch to an allowed live tab `index` |
| `history` | Read bounded action outcomes without replaying actions |
| `read_state` | Inspect ready state, a main-content selector, closed details, loading and scroll range |
| `scroll` | Scroll 650 pixels; `value="down"` or `"up"` |
| `settle` | Wait up to `ms` for the page's requests to go quiet, then scroll to the end until the document stops growing, up to `limit` rounds. Automatic headed reads use it before capture |
| `expand_details` | Open up to two visible standard details summaries; `limit` can reduce this; nested interactive controls are skipped |

Set `frame` to an iframe's CSS selector for supported locator actions. Its target
must be in the session's allowed-host scope. Tab indices are live positions, not
durable handles. Every step reports success, reason, timing and data. The run
stops on the first failure; never assume later steps ran.

Click/HTML/snapshot diagnostics help distinguish hidden, covered, detached,
disabled, unstable, out-of-viewport and selector failures. For repeated controls,
use snapshot context and selector indexes rather than guessing. `limit` is an
entry count; `max_chars` is the text/HTML budget. Steps use `ms`, not a per-step
`timeout_ms`; the top-level `timeout_ms` bounds the entire request.

## Scope and network results

Set `allowed_hosts` at session creation; the allowlist and public-target policy
cannot be broadened on reuse. Hostnames omit ports. Top-level and popup navigation
remain within scope. Public subframes may load to execute challenges, but that
does not grant arbitrary locator access to an out-of-scope frame. Public sessions
also reject private-network requests. These checks do not replace network egress
isolation or eliminate every DNS-rebinding risk.

Network capture keeps a ring of 50 responses. Use the returned stable
`response_id`; eviction makes it unavailable. Text/JSON/XML/JavaScript body reads
accept chunked bodies and enforce a 2 MB decoded limit as well as a declared
size check. This is an acceptance limit, not streaming browser-memory isolation.
Bodies can become retained documents. Binary files belong in the download path.

## Pixels, events and canaries

`screenshot` is `never`, `failure` (default), `canary` or `always`; legacy booleans
map to always/never. REST/local responses carry `screenshot_b64`; MCP forwards
native image blocks. A vision-capable model must receive the image, not a
placeholder string. Use screenshots when a chart, layout or challenge needs them.

Events include failed requests, HTTP errors, page errors, console signals and
dismissed dialogs. Optional unpredictable `canaries` distinguish visible reflection
from execution signals in dialogs/console/page-error/title channels. They are
optional inspection controls, not required for ordinary reading.

## Downloads, checkpoints and retries

Downloads must come from an actual control. The worker bounds capture at 32 MiB;
the API applies normal parsers, retains supported source bytes and returns a
scoped document handle. Unsupported parsing fails explicitly. Closing a live
session removes its browser download files; retained evidence has its own expiry.

A checkpoint lasts up to 24 hours and stores sensitive browser state locally.
It excludes live DOM, sockets and other tabs. Restore with the same session and
scope. Closing the session deletes its checkpoint. History retains up to 200
outcomes without typed values, selectors or response bodies.

Use an explicit session plus `operation_id` for retry protection. An identical
completed operation can replay its saved result; changed payloads conflict.
Completed entries expire after 24 hours. Running and unknown entries have a
seven-day retention limit. A full journal refuses new operations while existing
entries remain available for retry checks. An interrupted operation may require
inspecting the external state before acting again. Very large results retain the
completion record without storing a second copy of the evidence.

Automatic fetch recovery uses its own caller/exact-host browser identities and
checkpoints. It does not export their cookies to curl or share them between
clients. Its early-commit read policy differs from ordinary drive navigation,
which waits for DOMContentLoaded. See [architecture](PIPELINE.md).


## Repeated interaction and checkpoint verification

The worker activates a selected headed tab before clicks and when switching tabs.
`switch_tab` waits within its step/run deadline for a new popup to leave its initial
blank page; a nonblank URL outside `allowed_hosts` still fails. This avoids requiring
an agent to guess a fixed popup delay on slower hardware.

When restoring a checkpoint containing IndexedDB, the worker compares a read-back
snapshot with the saved representation before allowing page scripts to run. It
closes and retries an incomplete context up to three times, then fails while keeping
the checkpoint. `session.indexeddb_restore_attempts` reports verified restoration
attempts (zero when no IndexedDB verification was needed). This checks the captured
representation, not arbitrary application semantics or every browser serialization
type. The [recorded restart failure and follow-up checks](../evaluations/install-showcase/results/2026-11-04/ISSUES.md)
explain the observed limitation and safeguard.

[Documentation home](README.md) · [Agent guide](AGENT-UPGRADES.md) · [API](API.md) · [Evidence](EVIDENCE.md)

## Ad/tracker filtering

The [native filter](ADBLOCK.md) checks managed browser connections, including
redirects and worker/WebSocket traffic. `/drive` reports bounded blocked-domain
events and filter state. A completed UI action remains separate from a successful
read. This filter does not inject page scripts or disable service workers.
