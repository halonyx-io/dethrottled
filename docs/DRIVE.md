# Browser drive for agents

`POST /drive` operates the warm Patchright Chromium already managed by
Dethrottled. It is designed for agents that need to interact with a page,
preserve state across turns, and collect machine-readable evidence without
starting their own browser or taking a screenshot after every action.

## Efficient agent loop

1. Create one named session for one target and task.
2. Set `allowed_hosts` before the first navigation.
3. Request a `snapshot` to discover useful controls and selectors.
4. Perform the smallest next interaction and inspect its structured result.
5. Use a unique canary when testing whether controlled text executes.
6. Request screenshots only for failures, canary matches, or genuinely visual
   questions.
7. Close the session as soon as the task is finished.

This keeps the normal loop text-only and cheap. A screenshot is evidence, not
the browser's primary control protocol.

## Start or continue a session

```sh
curl -sS http://127.0.0.1:8787/drive \
  -H 'content-type: application/json' \
  -d '{
    "session":"target-workflow-01",
    "url":"https://example.com/",
    "allowed_hosts":["example.com"],
    "screenshot":"failure",
    "steps":[{"action":"snapshot","limit":100}]
  }'
```

Reuse the same `session` in later requests without supplying `url`. Cookies,
web storage, page state, and the current DOM remain available. Calls for the
same session are serialized. Sessions live only in worker memory, expire after
30 minutes by default, and do not survive a worker restart.

Close one explicitly:

```sh
curl -sS http://127.0.0.1:8787/drive \
  -H 'content-type: application/json' \
  -d '{"session":"target-workflow-01","close_session":true,"steps":[]}'
```

Omit `session` for an isolated one-shot context that is closed automatically.

## Actions

| Action | Important fields | Result |
| --- | --- | --- |
| `snapshot` | `selector`, `limit` | Visible interactive elements and selector hints |
| `goto` | `url`, `ms` | Final URL and HTTP status when available |
| `click` | `selector`, `index`, `ms` | Click outcome |
| `fill` | `selector`, `value` | Replace a value and emit `input` plus `change` |
| `type` | `selector`, `value`, `delay_ms` | Type sequentially when key events matter |
| `press` | `selector`, `value` | Press a key such as `Enter` |
| `select` | `selector`, `value` | Select an option |
| `check`, `uncheck` | `selector` | Set checkbox/radio state |
| `hover` | `selector` | Trigger hover behavior |
| `wait` | `ms` | Bounded delay |
| `wait_for` | `selector`, `value`, `ms` | Wait for `visible`, `hidden`, `attached`, or `detached` |
| `text` | `selector` | Read visible text |
| `html` | `selector` | Read bounded outer HTML |
| `attr` | `selector`, `name` | Read an HTML attribute |
| `count` | `selector` | Count matches |
| `url`, `title` | none | Read current page identity |

Steps stop at the first failure. Every step reports `ok`, `reason`,
`elapsed_ms`, and `data`, so the caller should repair or re-plan instead of
continuing from an assumed page state.

`fill` uses the browser's native editing path. Patchright emits `input` while
setting the value, and Dethrottled emits `change` immediately afterward. This
makes React-controlled fields and forms that wait for a committed change
deterministic without requiring a separate blur or arbitrary JavaScript.

## Canary evidence

Give each probe an unpredictable marker and pass it in `canaries`. Dethrottled
checks dialogs, console messages, page errors, the title, URL, and visible
text. Dialog, console, page-error, and title matches can establish an
`execution_signal`; visible reflection alone does not.

```json
{
  "session": "target-workflow-01",
  "canaries": ["DRIVE_CANARY_7f13"],
  "screenshot": "canary",
  "steps": [
    {"action": "fill", "selector": "input[name=title]", "value": "DRIVE_CANARY_7f13"},
    {"action": "click", "selector": "button[type=submit]"},
    {"action": "wait", "ms": 1000}
  ]
}
```

The response includes `canary_matches` and event telemetry for dialogs,
console output, page errors, failed requests, and HTTP error responses. Browser
dialogs are automatically dismissed so an alert cannot deadlock the session.

## Screenshot policy

`screenshot` accepts:

- `never`: never return pixels.
- `failure`: capture only when the run fails; this is the default.
- `canary`: capture only when a supplied canary matches.
- `always`: capture after every request.

The screenshot is a base64 PNG in `screenshot_b64`. Prefer `snapshot`, `text`,
and browser events for planning; use pixels when layout or rendered appearance
is itself the evidence.

## Boundaries

Set `allowed_hosts` for autonomous operation. It restricts top-level
navigation and includes subdomains of a listed host. The allowlist is fixed for
the lifetime of a named session, preventing a later call from silently
broadening its scope.

`/drive` intentionally does not expose arbitrary JavaScript evaluation. The
whole request and each step are time-bounded, the action set is explicit, and
the number of stored sessions is capped. These controls protect the service;
they do not determine whether a target or test is authorized.

The raw local API has no caller authentication. Keep it on a trusted network
or put an authenticated, policy-enforcing gateway in front of it before any
external exposure.
