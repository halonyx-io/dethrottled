# 2026-11-01 findings review / 0.9 evidence

Compare deployed 0.8.0 (commit 5bd95f5) with the recovery candidate. See
[review and limitations](../../REVIEWED-BOT-FINDINGS.md). D6 is excluded.

The frozen live protocol includes four hostile sources and a normal documentation
control. Early sweeps used trusted internal reads; `*-final-live.json` uses
`public_only=true` and a clean candidate browser with normal production policy.
Responses vary upstream, so these are observations rather than a causal browser
bypass-rate estimate. Final diagnostic fields were refined after those sweeps;
production checks record the promoted package. No hostile success is inferred
from a challenge page, HTTP 200, a nonempty response, or a green fingerprint test.

Controlled clearance uses the included fixture.py, served at port 19890 inside
a test-only Docker network. The browser fixture uses the unchanged pinned browser
stack. The script delays clearance by 2200 ms, sets a fixture cookie and reloads
into a known 7341-tonne report. It is not Cloudflare or a commercial CAPTCHA.
The four challenge cases test ordinary/default reads, same-caller reuse, caller
separation and explicit headed fallback; a fifth plain case guards the direct path.
`restored-controlled.json` is collected after restarting that isolated browser.

The frame probe adds a cross-host subframe that completes the fixture challenge.
Its evaluation wrapper allows only the two exact fixture hosts as public targets;
that exception is never installed on the real worker. Private subframe and foreign
top-level controls remain blocked. The popup probe confirms the foreign popup is
replaced by a browser error page and is not an allowed tab. Its initial probe
incorrectly expected popup failures in the main page event list; the corrected
assertion uses the actual popup tab's URL and scope result. Original local test
logs retain that harness failure.

The research probe uses real concurrent ASGI requests with a controlled delayed
search function. No render request occurs. It reproduces the n=1/2/3/6 pattern
and demonstrates which limiter fires, including response body and retry headers.
The SDK and gateway evaluations run in their respective installed environments:
`evaluations/tool_validation.py` and `evaluations/gateway_validation.py`. No network
or credentials are needed for those validation checks.

Fingerprint results publish selected non-identifying checks only. Full fingerprint
HTML, unique hashes, browser storage and credentials are not distributed. An
OpenGL backend experiment did not restore WebGL and was rejected; no launch flags
or browser dependencies were changed. Exact external-site success cannot be
replayed offline; fixtures and validation tests can. The source report's hash
identifies the revision reviewed. Trailing whitespace may be normalized in logs.

## Harness setup

These are recorded integration harnesses, not production startup commands. Use a
separate Docker network/project and disposable data/browser volumes. Build the old
core/browser from `5bd95f5` and the candidate from the reviewed commit. Serve
`fixture.py` on port 19890 as `dethrottled-findings-fixture`, with network alias
`dethrottled-findings-frame`. For frame/popup tests only, mount the evaluation-only
`fixture_browser.py` alongside the worker's service module and use
`start-fixture.sh`; expose old/new workers at loopback 18409/18410. The wrapper's
only address exceptions are those two exact private fixture names. Never install
that wrapper on a public or production worker.

For `controlled_probe.py`, run each core image on this test network with this
directory mounted writable at `/evidence`, `LABEL=baseline` or `LABEL=candidate`,
`DETHROTTLED_CRAWL4AI_URL=` and `DETHROTTLED_BROWSER_SEARCH_URL` pointing at its
respective isolated browser's port 19888. The probe imports the installed core
package. Use fresh browser state per build; restart the candidate browser with its
checkpoint volume retained for the restoration run. The final API probe expects
an isolated candidate core on loopback 18405, configured with that fixture browser.
Live probes need a normal browser without fixture exceptions. The public SDK
probe uses `evaluations/client_probe.py`; supply a private mode-600 token file and
never add that file to the evidence bundle.

`summary.json` indexes the measured outcomes. `public-first-attempt.json` preserves
the busy rollout response; `public-probes.json`, `public-sdk.json` and
`public-diagnostics.json` preserve successful post-expiry verification plus the
still-failed hostile read. `public-checks.json` is the assertion checklist;
`live-v2-status.json` records worker readiness and keyless provider configuration.
