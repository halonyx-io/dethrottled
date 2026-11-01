# Browser operation

`POST /drive` operates the existing headed Patchright browser. Use it when a
read needs controls, an export, application responses or visual inspection.
The API exposes bounded actions, not arbitrary JavaScript evaluation. Prefer
structured inspection for planning and actual pixels when appearance is evidence.

## Sessions and the interaction loop

```sh
curl -sS http://127.0.0.1:8787/drive \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/","session":"source-task","allowed_hosts":["example.com"],"steps":[{"action":"snapshot","limit":100}],"screenshot":"failure"}'
```

Discover controls with a snapshot, perform the smallest justified interaction,
then inspect its result. Reuse `session` without a URL to continue the same live
DOM and browser state. Calls for a session are serialized. An unnamed navigation
returns a persistent `auto-*` session; reuse the returned ID. For one-shot work,
set `close_session=true`. A stateful call without navigation/session returns 422;
a missing session without a restorable checkpoint returns 409.

Live contexts expire after 30 idle minutes by default, with at most eight live
sessions. Auto sessions can be evicted before explicitly named sessions.
`checkpoint` saves selected state for restoration after eviction/restart; it
is distinct from keeping a live page. Close a session explicitly when finished:

```json
{"session":"source-task","close_session":true,"steps":[]}
```

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
The durable bounded journal lasts 24 hours. Running/unknown outcomes after a
crash require inspection; it is not an exactly-once guarantee for external effects.
Very large results may retain the outcome without replayable evidence.

Automatic fetch recovery uses its own caller/exact-host browser identities and
checkpoints. It does not export their cookies to curl or share them between
clients. Its early-commit read policy differs from ordinary drive navigation,
which waits for DOMContentLoaded. See [architecture](PIPELINE.md).

[Documentation home](README.md) · [Agent guide](AGENT-UPGRADES.md) · [API](API.md) · [Evidence](EVIDENCE.md)
