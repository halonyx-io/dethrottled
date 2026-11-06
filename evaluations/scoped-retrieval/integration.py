"""Disposable 1.7.0 full-stack check. Usage: integration.py up|check|down STATE_DIR.

Requires the locally built 1.7.0 images and requirements/adapters.lock. Uses
public source reads at a bounded pace; see README before running.
"""

import asyncio
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ROOT = Path(__file__).resolve().parents[2]
STATE = Path(sys.argv[2]).resolve()
PROJECT = "dethrottled170qa"
STATE.mkdir(mode=0o700, exist_ok=True)
os.chmod(STATE, 0o700)


def run(args, **kw):
    return subprocess.run(args, check=True, text=True, **kw)


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def compose(*args):
    return ["docker", "compose", "-p", PROJECT, "-f", str(STATE / "compose.json"), *args]


def setup():
    bearer = secrets.token_urlsafe(48)
    registry = STATE / "tokens.json"
    registry.write_text(
        json.dumps(
            {
                "tokens": [
                    {
                        "sha256": hashlib.sha256(bearer.encode()).hexdigest(),
                        "label": "disposable-integration",
                        "scopes": ["web", "drive", "corpus"],
                    }
                ]
            }
        )
    )
    registry.chmod(0o644)
    (STATE / "bearer").write_text(bearer)
    (STATE / "bearer").chmod(0o600)
    env = dict(os.environ, DETHROTTLED_TOKEN_REGISTRY_FILE=str(registry))
    data = json.loads(
        subprocess.check_output(
            [
                "docker",
                "compose",
                "--project-directory",
                str(ROOT),
                "-f",
                str(ROOT / "docker-compose.yml"),
                "-f",
                str(ROOT / "docker-compose.agents.yml"),
                "--profile",
                "public",
                "config",
                "--format",
                "json",
            ],
            env=env,
            text=True,
        )
    )
    keep = {"dethrottled", "browser-search", "searxng", "crawl4ai", "format-worker", "mcp", "rest"}
    data["services"] = {k: v for k, v in data["services"].items() if k in keep}
    ports = {k: port() for k in ("api", "mcp", "rest")}
    for name, service in data["services"].items():
        service.pop("build", None)
        service.pop("profiles", None)
        service["restart"] = "no"
        for key, value in service.get("ulimits", {}).items():
            if isinstance(value, dict) and value.get("soft") == value.get("hard"):
                service["ulimits"][key] = value.get("soft", 0)
        service["pull_policy"] = "never"
        if name == "dethrottled":
            service["image"] = "dethrottled:1.7.0"
        elif name == "browser-search":
            service["image"] = "dethrottled-browser-search:1.7.0"
        elif name in {"mcp", "rest"}:
            service["image"] = "dethrottled-adapters:1.7.0"
        if name in {"dethrottled", "mcp", "rest"}:
            key = "api" if name == "dethrottled" else name
            service["ports"][0]["published"] = str(ports[key])
    for key, item in data.get("volumes", {}).items():
        item["name"] = PROJECT + "_" + key
    for key, item in data.get("networks", {}).items():
        item["name"] = PROJECT + "_" + key
    data["name"] = PROJECT
    data["services"]["fixture"] = {
        "image": "dethrottled:1.7.0",
        "restart": "no",
        "command": ["python", "/fixture.py"],
        "volumes": [str(ROOT / "evaluations/scoped-retrieval/fixture.py") + ":/fixture.py:ro"],
    }
    (STATE / "compose.json").write_text(json.dumps(data, indent=2))
    (STATE / "ports.json").write_text(json.dumps(ports))
    run(compose("up", "-d", "--no-build"))
    for _ in range(120):
        try:
            response = httpx.get("http://127.0.0.1:" + str(ports["api"]) + "/health", timeout=2)
            if response.status_code == 200 and response.json()["version"] == "1.7.0":
                break
        except (OSError, httpx.HTTPError, ValueError):
            pass
        time.sleep(1)
    else:
        raise RuntimeError("API not ready")
    print(json.dumps({"project": PROJECT, "started": True}))


def decode(result):
    assert not result.isError, str(result.content)[:400]
    if result.structuredContent is not None:
        return result.structuredContent
    return [json.loads(c.text) for c in result.content if c.type == "text"]


async def verify():
    ports = json.loads((STATE / "ports.json").read_text())
    token = (STATE / "bearer").read_text()
    bases = {k: "http://127.0.0.1:" + str(p) for k, p in ports.items()}
    headers = {"Authorization": "Bearer " + token}
    report = {
        "version": "1.7.0",
        "scope": (
            "Isolated software-rendered default Compose stack + real MCP/REST "
            "adapters; local UI/sitemap fixtures and bounded public-source reads."
        ),
    }
    async with httpx.AsyncClient(timeout=120, trust_env=False) as http:

        async def post(base, path, body, auth=False):
            r = await http.post(base + path, json=body, headers=headers if auth else {})
            r.raise_for_status()
            return r.json()

        for _ in range(90):
            try:
                bridge = (await http.get(bases["mcp"] + "/health", timeout=3)).json()
                if bridge.get("version") == "1.7.0" and bridge.get("backend") == {
                    "version": "1.7.0",
                    "status": "match",
                }:
                    break
            except (OSError, httpx.HTTPError, ValueError):
                pass
            await asyncio.sleep(1)
        else:
            raise RuntimeError("Adapter/backend mismatch")
        report["identity"] = bridge
        report["unauthorized_rest"] = (
            await http.get(bases["rest"] + "/v2/capabilities")
        ).status_code
        assert report["unauthorized_rest"] == 401
        caps = (await http.get(bases["api"] + "/v2/capabilities")).json()
        assert caps["version"] == "1.7.0" and "map" in caps["site"]["modes"]
        contracts = {(r["method"], r["path"]): r for r in caps["request_contracts"]["routes"]}
        assert "domains" in contracts["POST", "/search"]["body_fields"]
        assert "selectors" in contracts["POST", "/fetch"]["body_fields"]
        report["new_contracts"] = True
        sitemap = await post(
            bases["api"],
            "/site/crawl",
            {
                "urls": ["http://fixture:8080/index.xml"],
                "mode": "map",
                "render": "never",
                "max_discovery_requests": 2,
            },
        )
        assert len(sitemap["sources"]) == 3, sitemap
        assert (
            sitemap["coverage"]["attempted"] == 0 and sitemap["coverage"]["discovery_requests"] == 2
        )
        assert not any(r.get("document_id") for r in sitemap["sources"])
        report["nested_sitemap"] = {
            "urls": len(sitemap["sources"]),
            "discovery_requests": 2,
            "evidence_reads": 0,
        }
        drive = await post(
            bases["api"],
            "/drive",
            {
                "url": "http://fixture:8080/",
                "steps": [
                    {"action": "wait_for", "selector": 'body[data-ready="yes"]'},
                    {"action": "text", "selector": "h1"},
                    {"action": "click", "selector": "#confirm"},
                    {"action": "text", "selector": "#confirm"},
                ],
                "screenshot": "always",
            },
        )
        assert drive["ok"] and drive.get("screenshot_b64"), str(drive)[:400]
        data = [s.get("data") for s in drive["steps"] if s["action"] == "text"]
        assert "Verified live DOM" in data and "Confirmed 7341 tonnes" in data, data
        report["actual_js_browser"] = {
            "dynamic_dom": True,
            "click_effect": True,
            "screenshot": True,
        }
        impossible = await post(
            bases["rest"],
            "/v2/search",
            {"query": "climate", "domains": ["nasa.gov"], "exclude_domains": ["nasa.gov"]},
            True,
        )
        assert impossible["outcome"] == "constraints_unsatisfiable" and not impossible["results"]
        report["public_constraints_unsatisfiable"] = True
        rejected = await http.post(
            bases["rest"] + "/fetch", headers=headers, json={"urls": ["http://fixture:8080/"]}
        )
        assert rejected.status_code in {400, 403}, rejected.text[:200]
        report["public_internal_target_rejected"] = rejected.status_code
        async with streamablehttp_client(bases["mcp"] + "/mcp", headers=headers) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as client:
                init = await client.initialize()
                assert init.serverInfo.version == "1.7.0"
                assert (
                    hashlib.sha256(init.instructions.encode()).hexdigest()
                    == caps["client_contract"]["workflow_sha256"]
                )
                tools = (await client.list_tools()).tools
                assert len(tools) == 20
                assert (
                    "domains"
                    in next(t for t in tools if t.name == "search").inputSchema["properties"]
                )
                selected = decode(
                    await client.call_tool(
                        "fetch",
                        {
                            "urls": ["https://example.com/"],
                            "selectors": {"title": {"selector": "title"}},
                            "render": "never",
                            "recovery": "manual",
                            "max_chars": 200,
                        },
                    )
                )
                row = selected[0] if isinstance(selected, list) else selected
                assert row["structured"]["title"] == "Example Domain", str(row)[:600]
                assert row["structured_status"]["satisfied"]
                report["actual_mcp_selectors"] = {
                    "title": row["structured"]["title"],
                    "quality": row["quality"],
                    "source_html_partial": row["structured_status"]["source_html_partial"],
                    "provenance_hash": bool(row["structured_provenance"]["html_sha256"]),
                }
                mapped = decode(
                    await client.call_tool(
                        "crawl_site",
                        {
                            "urls": ["https://example.com/"],
                            "mode": "map",
                            "render": "never",
                            "max_pages": 3,
                            "max_discovery_requests": 1,
                        },
                    )
                )
                assert (
                    mapped["operation"] == "site_map"
                    and mapped["coverage"]["discovery_requests"] == 1
                )
                report["actual_mcp_map"] = {
                    "outcome": mapped["outcome"],
                    "urls": len(mapped["sources"]),
                    "attempted": mapped["coverage"]["attempted"],
                }
                constrained = decode(
                    await client.call_tool(
                        "search",
                        {
                            "query": "Python pathlib recursive glob",
                            "domains": ["docs.python.org"],
                            "profile": "web",
                            "limit": 3,
                            "diagnostics": True,
                            "fresh": True,
                        },
                    )
                )
                if isinstance(constrained, list):
                    constrained = constrained[0]
                from urllib.parse import urlsplit

                assert all(
                    (urlsplit(r["url"]).hostname or "") == "docs.python.org"
                    for r in constrained["results"]
                )
                report["bounded_live_search"] = {
                    "outcome": constrained["outcome"],
                    "degraded": constrained["degraded"],
                    "urls": [r["url"] for r in constrained["results"]],
                    "attempts": constrained["attempts"],
                }
                queued = decode(
                    await client.call_tool(
                        "start_fetch_job",
                        {
                            "urls": ["https://example.com/"],
                            "selectors": {"title": {"selector": "title"}},
                            "render": "never",
                            "response_format": "concise",
                            "operation_id": "integration-selector-job",
                        },
                    )
                )
                for _ in range(60):
                    job = decode(
                        await client.call_tool(
                            "read_fetch_job", {"job_id": queued["job_id"], "cursor": 0}
                        )
                    )
                    if job.get("status") in {"complete", "completed", "failed", "interrupted"}:
                        break
                    await asyncio.sleep(0.5)
                (STATE / "job-raw.json").write_text(json.dumps(job, indent=2))
                rows = job.get("sources", job.get("results", []))
                assert job["status"] in {"complete", "completed"} and rows, job
                row = rows[0].get("result", rows[0])
                assert row["structured"]["title"] == "Example Domain", row
                report["actual_mcp_job"] = {"status": job["status"], "selector_fact_retained": True}
        report["passed"] = True
        (STATE / "result.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    if sys.argv[1] == "up":
        setup()
    elif sys.argv[1] == "check":
        asyncio.run(verify())
    elif sys.argv[1] == "down":
        assert PROJECT == "dethrottled170qa"
        saved = json.loads((STATE / "compose.json").read_text())
        assert saved["name"] == PROJECT
        assert all(v["name"].startswith(PROJECT + "_") for v in saved["volumes"].values())
        run(compose("down", "--volumes", "--remove-orphans"))
