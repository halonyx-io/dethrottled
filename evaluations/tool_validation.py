"""Run using the deployed MCP SDK environment; no network or credentials needed."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/opt/dethrottled-access")
spec = importlib.util.spec_from_file_location("validation_adapter", repo / "adapters/mcp_server.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


async def run():
    calls = []

    async def backend(*args, **kwargs):
        calls.append(args)
        return {"stub_backend_reached": True}

    module._backend_post = backend
    cases = []
    for name, args in [
        ("search", {"query": "fixture", "category": "news"}),
        ("fetch", {"urls": ["https://example.com"], "raw": True}),
    ]:
        try:
            await module.mcp._tool_manager.get_tool(name).run(args)
        except Exception as exc:
            cases.append({"tool": name, "rejected": True, "error": str(exc)})
        else:
            raise AssertionError("unknown field accepted")
    assert not calls
    await module.mcp._tool_manager.get_tool("search").run(
        {"query": "fixture", "categories": "news"}
    )
    assert len(calls) == 1
    tools = module.mcp._tool_manager.list_tools()
    assert all(t.parameters.get("additionalProperties") is False for t in tools)
    print(
        json.dumps(
            {"cases": cases, "valid_backend_calls": len(calls), "strict_tool_schemas": len(tools)},
            indent=2,
        )
    )


asyncio.run(run())
