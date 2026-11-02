"""Run inside the pinned SearXNG container, with networking disabled."""

import json
from types import SimpleNamespace

import searx.webapp  # noqa: F401 -- initializes the configured plugins
from searx.exceptions import SearxEngineAccessDeniedException
from searx.network import network

handler = network.raise_for_httperror
assert getattr(handler, "_dethrottled_retry_after", False), "Cooldown plugin did not load"
checks = []
for status, header in [(429, "7200"), (403, "7200"), (429, "60"), (429, "invalid")]:
    response = SimpleNamespace(status_code=status, headers={"Retry-After": header}, text="")
    try:
        handler(response)
    except SearxEngineAccessDeniedException as exc:
        assert exc.suspended_time >= (7200 if header == "7200" else 180)
        checks.append({"status": status, "retry_after": header,
                       "suspended_seconds": exc.suspended_time,
                       "exception": type(exc).__name__})
    else:
        raise AssertionError("Expected upstream refusal")
print(json.dumps({"plugin_loaded": True, "checks": checks}))
