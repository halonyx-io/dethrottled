"""Authenticated REST/MCP parity against disposable adapters, no registry mutation."""

import argparse
import asyncio
import hashlib
import json
import time
import uuid
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

p = argparse.ArgumentParser()
p.add_argument("--rest", default="http://127.0.0.1:19086")
p.add_argument("--mcp", default="http://127.0.0.1:19084/mcp")
p.add_argument("--token-files", nargs=2, type=Path, required=True)
p.add_argument("--out", type=Path, required=True)
a = p.parse_args()
keys = [path.read_text().strip() for path in a.token_files]
url = (
    "https://www.reddit.com/r/programming/comments/1xl8d57/"
    "jepsen_on_particledb_we_tested_versions_114/"
)
scope = dict(
    session="auto-read-" + uuid.uuid4().hex,
    allowed_hosts=["www.reddit.com"], screenshot="never",
)
record = {}


def unpack(result):
    assert not result.isError
    value = result.structuredContent
    if value is None:
        value = json.loads(result.content[0].text)
    return value.get("result", value) if isinstance(value, dict) else value


async def main():
    async with httpx.AsyncClient(
        base_url=a.rest, headers={"Authorization": "Bearer " + keys[0]}, timeout=100
    ) as rest:
        try:
            response = await rest.get("/v2/capabilities")
            response.raise_for_status()
            caps = response.json()
            record["version"] = caps["version"]
            at = time.monotonic()
            response = await rest.post(
                "/drive",
                json=dict(
                    scope,
                    url=url,
                    steps=[{"action": "text", "selector": "body"}, {"action": "checkpoint"}],
                ),
            )
            response.raise_for_status()
            result = response.json()
            assert result["ok"] and "WHERE 4 = 5" in str(result["steps"])
            record["rest_fact_and_checkpoint_ms"] = round((time.monotonic() - at) * 1000, 2)
            async with streamablehttp_client(
                a.mcp, headers={"Authorization": "Bearer " + keys[0]}
            ) as (read, write, _):
                async with ClientSession(read, write) as client:
                    init = await client.initialize()
                    assert (
                        hashlib.sha256(init.instructions.encode()).hexdigest()
                        == (caps["client_contract"]["workflow_sha256"])
                    )
                    listing = await client.list_tools()
                    assert len(listing.tools) == 20
                    record.update(instructions_match=True, tools=20)
                    operation = dict(
                        scope,
                        operation_id="public-sort-" + uuid.uuid4().hex[:12],
                        steps=[
                            {"action": "click", "selector": "shreddit-sort-dropdown button"},
                            {"action": "count", "selector": '[role="menuitem"]:visible'},
                        ],
                    )
                    at = time.monotonic()
                    result = unpack(await client.call_tool("drive", operation))
                    assert result["ok"] and result["steps"][-1]["data"] > 0
                    record["native_click_ms"] = round((time.monotonic() - at) * 1000, 2)
                    replay = unpack(await client.call_tool("drive", operation))
                    assert replay["operation_replayed"]
                    response = await rest.post(
                        "/drive",
                        json=dict(
                            scope,
                            steps=[
                                {
                                    "action": "attr",
                                    "selector": "shreddit-sort-dropdown button",
                                    "name": "aria-expanded",
                                }
                            ],
                        ),
                    )
                    response.raise_for_status()
                    assert response.json()["steps"][-1]["data"] == "true"
                    record.update(rest_mcp_state_shared=True, operation_replay=True)
                    value = unpack(
                        await client.call_tool(
                            "fetch",
                            dict(
                                urls=[url],
                                max_chars=24000,
                                cache_mode="bypass",
                                focus="WHERE 4 = 5",
                            ),
                        )
                    )
                    row = value[0] if isinstance(value, list) else value
                    assert row["document_id"] and row["read_plan"]
                    retained = unpack(
                        await client.call_tool(
                            "read_document", dict(document_id=row["document_id"], max_chars=12000)
                        )
                    )
                    assert retained.get("content")
                    record["retained_document_forwarded"] = True
                    other = await rest.post(
                        "/drive",
                        headers={"Authorization": "Bearer " + keys[1]},
                        json=dict(scope, steps=[{"action": "text", "selector": "body"}]),
                    )
                    assert other.status_code == 409
                    other_doc = await rest.post(
                        "/read_document",
                        headers={"Authorization": "Bearer " + keys[1]},
                        json=dict(document_id=row["document_id"]),
                    )
                    assert other_doc.status_code == 404
                    record["caller_isolation"] = True
                    private = await rest.post("/fetch", json=dict(urls=["http://127.0.0.1/"]))
                    assert private.status_code == 400
                    record["private_target_rejected"] = True
            record["passed"] = True
        finally:
            await rest.post("/drive", json=dict(scope, steps=[], close_session=True))
            a.out.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record))


asyncio.run(main())
