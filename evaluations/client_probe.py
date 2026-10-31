"""Record a real MCP SDK handshake and reading workflow without recording credentials.

Run in an environment with mcp[cli], with a mode-600 bearer-token file. This
tests the SDK boundary, not whether a particular agent forwards metadata to its model.
"""

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main(args):
    headers = {"Authorization": "Bearer " + args.token_file.read_text().strip(),
               "User-Agent": "dethrottled-sdk-compatibility/1"}
    output = {"endpoint": args.endpoint, "sdk": importlib.metadata.version("mcp"),
              "events": [], "client_limit": "Does not inspect a remote plugin's loaded code."}
    args.output.parent.mkdir(parents=True, exist_ok=True)

    async def record(label, call):
        start = time.perf_counter()
        try:
            result = await call
            value = result.model_dump(mode="json", by_alias=True)
            output["events"].append({"label": label,
                "wall_ms": round((time.perf_counter() - start) * 1000, 2), "result": value})
            return value
        finally:
            args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    async with streamablehttp_client(args.endpoint, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as client:
            init = await record("initialize", client.initialize())
            output["instructions_sha256"] = hashlib.sha256(
                init.get("instructions", "").encode()).hexdigest()
            listing = await record("tools/list", client.list_tools())
            names = {t["name"] for t in listing["tools"]}
            assert {"fetch", "inspect_document", "crawl_site", "resume_fetch_job"} <= names
            capabilities = await record("capabilities", client.call_tool("capabilities", {}))
            caps = capabilities.get("structuredContent") or json.loads(
                capabilities["content"][0]["text"])
            assert caps["client_contract"]["workflow_sha256"] == output["instructions_sha256"]
            output["service_version"] = caps["version"]
            result = await record("fetch", client.call_tool("fetch", {
                "urls": [args.url], "max_chars": 2000, "recovery": "manual"}))
            assert not result.get("isError"), result
            data = result.get("structuredContent")
            if not data:
                data = json.loads(result["content"][0]["text"])
            if isinstance(data, dict) and "result" in data:
                data = data["result"]
            row = data[0] if isinstance(data, list) else data
            assert row.get("quality") == "ok" and row.get("document_id"), row
            await record("inspect_document", client.call_tool("inspect_document", {
                "document_id": row["document_id"], "limit": 3}))
            await record("read_document", client.call_tool("read_document", {
                "document_id": row["document_id"], "max_chars": 2000}))
    output["completed"] = True
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print("SDK workflow complete; recorded", len(output["events"]), "events")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--url", default="https://docs.python.org/3/library/sqlite3.html")
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
