"""Check inferred host bounds and native image output in the MCP adapter runtime."""

import asyncio
import importlib.util
import sys
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, "/opt/dethrottled-access")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


m = load("eval_mcp_adapter", repo / "adapters/mcp_server.py")
r = load("eval_rest_adapter", repo / "adapters/rest_gateway.py")
for module, url_attr, host_attr in [
    (m, "_public_url", "_public_hostname"),
    (r, "public_url", "public_hostname"),
]:
    setattr(module, url_attr, lambda url: url.startswith("https://example.org/"))
    setattr(module, host_attr, lambda host: host in {"example.org", "other.org"})


async def run():
    captured = []

    async def backend(path, payload, **kwargs):
        captured.append(payload)
        return {"ok": True, "screenshot_b64": "aGVsbG8="}

    m._backend_post = backend
    result = await m.drive(url="https://example.org/source", screenshot="always")
    assert captured[-1]["allowed_hosts"] == ["example.org"]
    assert [item.type for item in result.content] == ["text", "image"]
    assert "screenshot_b64" not in result.structuredContent
    for args in [
        dict(url="https://example.org/source", allowed_hosts=["other.org"]),
        dict(url="http://127.0.0.1/private"),
    ]:
        try:
            await m.drive(**args)
        except ValueError:
            pass
        else:
            raise AssertionError("Navigation policy was not enforced")
    payload = {"url": "https://example.org/source", "steps": []}
    assert r.validate_drive(payload) is None and payload["allowed_hosts"] == ["example.org"]
    assert r.validate_drive({"url": "https://example.org/source", "allowed_hosts": ["other.org"]})
    assert r.validate_drive({"url": "http://127.0.0.1/private"})
    print(
        "Adapter checks passed: inferred hosts, explicit bounds, private "
        "rejection, native MCP pixels."
    )


asyncio.run(run())
