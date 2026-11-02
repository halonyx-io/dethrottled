# MCP maintenance — 2 November 2026

Dethrottled 1.0.1 updates the MCP SDK from 1.28.1 to the maintained 1.x release
1.30.0. The wire server version now identifies Dethrottled, rather than inheriting
the SDK version. Health exposes both numbers separately. SDK 2.x changes imports,
server APIs, types and validation behavior, so adopting it requires a separate
migration rather than an untested dependency bump.

The adapter's FastAPI/Uvicorn pins are aligned with the versions already verified
in the core 1.0 runtime. Container and host installations share one requirements
file. No acquisition, extraction, ranking or browser-recovery policy changes.

The packaged adapter's new offline transport probe starts the actual ASGI server
and uses a real MCP SDK client. It verifies initialization version/instructions,
20 tools, the browser-action schema, unknown-argument rejection, private-target
rejection, authentication and live token revocation. It runs without Internet
or a backend, so an unreachable backend cannot be counted as successful retrieval.
Both native Docker CI jobs run this probe. `offline-adapter.json` records the local
image observation; CI and production checks must also pass before promotion.

This upgrade does not establish greater source coverage or lower request latency.
Its measurable benefits are correct release identification and retaining the
agent/access contracts under the supported dependency upgrade. Live source
checks remain observational and preserve their individual results.
