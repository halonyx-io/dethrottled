# Deployed verification

Version 0.10.0 was deployed on 2 November 2026. The core, browser, MCP bridge,
REST gateway and shared caller-identity module were checked against the source
checkout. All 36 installed Python modules and 23 packaged Markdown guides matched.
The browser health probe reported actual AMD rendering and the expected pixel.
Browser, Crawl4AI, layout, speech and format worker status probes were ready;
SearXNG was operational. Model backfill completed.

[Runtime verification](runtime-verification.json) records source equality and the
worker snapshot. Its Git revision identifies the runtime tested, before the final
publication of these deployment records; later record/helper changes do not change
the acquisition code.

[Authenticated public verification](public-verification.json) used the actual
HTTPS endpoints and MCP SDK. It confirmed 20 tools, identical initialize/capability
workflow hashes, default fetch forwarding of read_plan, retained-document reads,
REST-to-MCP browser continuation, and rejection of another caller's attempt to use
that state. Disposable credentials were removed and the registry restored byte
for byte. This verifies the SDK/server boundary, not any remote plugin's loaded code.

The public probe initially assumed an older Example Domain body heading; the page
had changed. It was replaced with the Python documentation control. The isolation
probe initially expected a blank new session; the worker correctly refused a
nonexistent session with HTTP 409 and an instruction to navigate first. Final
assertions check that observed contract. These probe-assumption failures were not
product recovery failures or extra successful source reads.

## Deployment issues and corrections

The first rollout encountered inherited production Compose labels on disposable
containers created from layered local images. Compose stopped the live core and
browser before hitting a name conflict. The interruption lasted about 30 seconds.
Disposable containers were removed, production services recreated successfully,
and health/source/public checks completed. Other workers remained running. Future
fixture containers must have a distinct Compose project label or be removed before
rollout. This operational error is included rather than presenting deployment as
uneventful.

The host's watchdog also revealed that the GPU helper's explicit file selection
omitted an existing COMPOSE_FILE PDF overlay. The helper now asks Compose to resolve
the default project environment, preserving configured overlays without sourcing
or evaluating dotenv text. [Auto/off selection checks](compose-overlay-confirmation.json)
confirm preservation of the PDF worker, numeric GPU groups when enabled and no
DRM devices when disabled. CI validates both the optional GPU syntax and overlay
preservation. The host watchdog uses the helper with its PDF overlay and completed
successfully. Rollback image tags and previous adapter/watchdog sources were retained.

Temporary test containers were removed. No paid API, new key, model service or
proxy dependency was introduced.
