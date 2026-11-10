"""Phase 3 wire gate: verified identity through REST, MCP and the DNB worker.

Expects a disposable lab already running: core, REST gateway, MCP bridge and a
DNB worker. See PHASE-3.md for the exact startup commands. Publishes nothing and
uses only loopback plus a local fixture. Direct worker drive calls use signed
delegation exactly as the core does; adapter-only paths reject internal URLs by
design, so drive owner binding is exercised at the worker trust boundary.

Run with PyJWT[crypto], httpx and the mcp client installed.
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
SECRETS = []


def sign_drive(body, owner, session):
    sys.path.insert(0, str(ROOT / "src"))
    from dethrottled.delegation import sign

    token = sign(
        body,
        owner=owner,
        session=session,
        scope="public-drive",
        public_only=False,
        allowed_hosts=(),
        path="/drive",
    )
    SECRETS.append(token)
    return token


def sign_read(body, owner, session):
    sys.path.insert(0, str(ROOT / "src"))
    from dethrottled.delegation import sign

    token = sign(
        body,
        owner=owner,
        session=session,
        scope="public-read",
        public_only=False,
        allowed_hosts=(),
        path="/crawl",
    )
    SECRETS.append(token)
    return token


async def mcp_fetch(url, token, mcp_url):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(
        mcp_url, headers={"Authorization": "Bearer " + token}
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "fetch",
                {
                    "urls": [url],
                    "render": "always",
                    "response_format": "concise",
                    "max_chars": 100,
                },
            )
            text = "".join(
                item.text for item in result.content if getattr(item, "text", None)
            )
            return {"is_error": result.isError, "text": text[:400]}


async def main(args):
    tokens = json.loads(Path(args.tokens).read_text())
    os.environ.setdefault("DETHROTTLED_DNB_PRIVATE_KEY", args.private_key)
    os.environ.setdefault("DETHROTTLED_DNB_PUBLIC_KEY", args.public_key)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    results = {}
    checks = []

    def check(name, condition, detail):
        checks.append({"check": name, "passed": bool(condition), "detail": detail})
        if not condition:
            print("FAIL", name, detail)

    async with httpx.AsyncClient(timeout=180) as client:

        async def worker_status():
            return (await client.get(args.worker + "/dnb/status")).json()

        async def rest_fetch(token, url, **extra):
            body = {
                "urls": [url],
                "response_format": "concise",
                "max_chars": 120,
                **extra,
            }
            response = await client.post(
                args.gateway + "/fetch",
                json=body,
                headers={"Authorization": "Bearer " + token},
            )
            data = response.json()
            row = data[0] if isinstance(data, list) and data else data
            return response.status_code, row

        async def direct_drive(owner, body, extra_headers=None):
            token = sign_drive(body, owner, body["session"])
            response = await client.post(
                args.worker + "/drive",
                json=body,
                headers={"X-DNB-Delegation": token, **(extra_headers or {})},
            )
            return response.status_code, response.json()

        async def storage_state(owner, session, seed=None):
            url = args.fixture + (f"/state?set={seed}" if seed else "/state")
            body = {
                "session": session,
                "url": url,
                "steps": [
                    {"action": "wait_for", "selector": "#ready"},
                    {"action": "text", "selector": "#ready"},
                ],
                "public_only": False,
                "allowed_hosts": [],
            }
            status, data = await direct_drive(owner, body)
            text = next(
                (step.get("data") for step in data.get("steps", [])
                 if step.get("action") == "text"),
                "{}",
            )
            try:
                state = json.loads(text)
            except (TypeError, ValueError):
                state = {}
            return status, data.get("ok"), state

        async def adapter_cookie_state(who, seed=None):
            url = "https://httpbin.org/cookies" + (
                f"/set?p3owner={seed}" if seed else ""
            )
            body = {
                "session": "p3-shared-cookie",
                "url": url,
                "steps": [
                    {"action": "goto", "url": "https://httpbin.org/cookies"},
                    {"action": "text", "selector": "body"},
                ],
                "allowed_hosts": ["httpbin.org"],
            }
            response = await client.post(
                args.gateway + "/drive",
                json=body,
                headers={"Authorization": "Bearer " + tokens[who]},
            )
            data = response.json()
            text = next(
                (step.get("data") for step in data.get("steps", [])
                 if step.get("action") == "text"),
                "{}",
            )
            return response.status_code, data.get("ok"), text

        stamp = str(int(time.time()))
        alice, bob = tokens["alice"], tokens["bob"]

        async def restart_worker():
            if not args.worker_container:
                return
            subprocess.run(
                ["docker", "restart", args.worker_container],
                check=True, capture_output=True,
            )
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    if (await client.get(args.worker + "/dnb/status")).status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.5)
            raise AssertionError("worker did not restart within 45 seconds")

        await restart_worker()
        before = await worker_status()
        status, row = await rest_fetch(alice, f"https://example.com/?p3=cold-{stamp}",
                                       render="always", fresh=True)
        after = await worker_status()
        check("rest cold read", status == 200 and bool(row.get("content")),
              {"status": status, "tier": row.get("tier")})
        def work(state):
            return (state["pool"]["contexts"], state.get("drive_sessions", 0))

        check("rest cold read reached worker",
              work(after) != work(before),
              {"before": work(before), "after": work(after),
               "fields": ["pool.contexts", "drive_sessions"]})

        status, row = await rest_fetch(alice, f"https://example.com/?p3=reuse-{stamp}",
                                       render="always", fresh=True)
        mid = await worker_status()
        status2, _row2 = await rest_fetch(alice, f"https://example.com/?p3=reuse-{stamp}",
                                         render="always", fresh=True)
        after2 = await worker_status()
        check("same-caller reuse", status == 200 and status2 == 200
              and work(after2) == work(mid),
              {"mid": work(mid), "after": work(after2)})

        status, row = await rest_fetch(bob, f"https://example.com/?p3=cross-{stamp}",
                                       render="always", fresh=True)
        after3 = await worker_status()
        check("cross-caller partition",
              status == 200 and work(after3) != work(after2),
              {"before": work(after2), "after": work(after3)})

        def owns(state, value):
            return (
                state.get("local") == value
                and state.get("session") == value
                and state.get("idb") == value
                and value in (state.get("cookie") or "")
            )

        session_a = f"p3-store-a-{stamp}"
        session_b = f"p3-store-b-{stamp}"
        _, _, set_a = await storage_state("alice", session_a, "alice")
        _, _, read_a = await storage_state("alice", session_a)
        _, _, read_b_fresh = await storage_state("bob", session_b)
        _, _, set_b = await storage_state("bob", session_b, "bob")
        _, _, read_b = await storage_state("bob", session_b)
        _, _, read_a_after = await storage_state("alice", session_a)
        check("owner A keeps cookie/localStorage/sessionStorage/IndexedDB",
              owns(set_a, "alice") and owns(read_a, "alice"),
              {"set": set_a, "read": read_a})
        check("owner B starts with no owner A storage",
              not owns(read_b_fresh, "alice") and read_b_fresh.get("local") is None,
              read_b_fresh)
        check("owners keep separate storage concurrently",
              owns(set_b, "bob") and owns(read_b, "bob")
              and owns(read_a_after, "alice"),
              {"a": read_a_after, "b": read_b})

        pairs = await asyncio.gather(
            storage_state("alice", session_a, "alice"),
            storage_state("bob", session_b, "bob"),
            storage_state("alice", session_a),
            storage_state("bob", session_b),
        )
        concurrent_ok = (
            owns(pairs[0][2], "alice") and owns(pairs[2][2], "alice")
            and owns(pairs[1][2], "bob") and owns(pairs[3][2], "bob")
        )
        check("concurrent cross-caller storage isolation", concurrent_ok,
              {"alice": pairs[2][2], "bob": pairs[3][2]})

        cookie_a, cookie_a_ok, _ = await adapter_cookie_state("alice", "alice")
        cookie_b, cookie_b_ok, cookie_b_read = await adapter_cookie_state("bob")
        _, _, cookie_b_set = await adapter_cookie_state("bob", "bob")
        _, _, cookie_a_read = await adapter_cookie_state("alice")
        check("signed-adapter cookie isolation",
              cookie_a == 200 and cookie_a_ok and cookie_b == 200 and cookie_b_ok
              and "alice" not in cookie_b_read
              and "bob" in cookie_b_set and "alice" in cookie_a_read,
              {"b_read": cookie_b_read, "b_set": cookie_b_set, "a_read": cookie_a_read})

        status, row = await rest_fetch(
            alice, f"https://example.com/?p3=auto-{stamp}", render="auto",
            wait_for="css:h1", fresh=True)
        check("autonomous escalation carries identity",
              status == 200 and row.get("tier") == "headed/read-plan",
              {"status": status, "tier": row.get("tier"),
               "method": (row.get("acquisition") or {}).get("method")})

        mcp = await mcp_fetch(f"https://example.com/?p3=mcp-{stamp}", bob, args.mcp)
        check("mcp read", not mcp["is_error"] and "example" in mcp["text"].lower(),
              mcp)

        session = f"p3-session-{stamp}"
        drive = {
            "session": session,
            "url": args.fixture + "/state?set=alice",
            "steps": [{"action": "checkpoint"}],
            "public_only": False,
            "allowed_hosts": [],
        }
        status, data = await direct_drive("alice", drive)
        check("drive owner first use", status == 200 and data.get("ok"),
              {"status": status, "ok": data.get("ok"),
               "steps": [(s.get("action"), s.get("ok"), s.get("reason"))
                         for s in data.get("steps", [])][:6]})
        status, data = await direct_drive("bob", drive)
        check("drive owner mismatch rejected",
              status == 403 and data.get("detail", {}).get("code") == "session_owner_mismatch",
              {"status": status, "detail": data.get("detail")})
        status, data = await direct_drive("alice", {**drive, "steps": []},
                                          {"X-DNB-Owner": "bob"})
        check("spoofed owner header rejected",
              status == 403 and data.get("detail", {}).get("code") == "untrusted_owner_headers",
              {"status": status, "detail": data.get("detail")})

        replay = {
            "session": f"p3-replay-{stamp}",
            "operation_id": f"p3-op-{stamp}",
            "url": args.fixture + "/state?set=alice",
            "steps": [{"action": "checkpoint"}],
            "public_only": False,
            "allowed_hosts": [],
        }
        first_status, _ = await direct_drive("alice", replay)
        replay_status, _replay_data = await direct_drive("alice", replay)
        conflict_status, conflict_data = await direct_drive(
            "alice", {**replay, "url": args.fixture + "/article"})
        check("drive replay is idempotent",
              first_status == 200 and replay_status == 200,
              {"first": first_status, "replay": replay_status})
        check("changed payload under one operation id conflicts",
              conflict_status == 409
              and conflict_data.get("detail", {}).get("code") == "operation_id_payload_conflict",
              {"status": conflict_status, "detail": conflict_data.get("detail")})

        persisted = {
            "session": f"p3-persist-{stamp}",
            "operation_id": f"p3-persist-op-{stamp}",
            "url": args.fixture + "/state?set=alice",
            "steps": [{"action": "checkpoint"}],
            "public_only": False,
            "allowed_hosts": [],
        }
        persist_first, _ = await direct_drive("alice", persisted)

        await restart_worker()

        persist_replay, _persist_data = await direct_drive("alice", persisted)
        persist_conflict, persist_conflict_data = await direct_drive(
            "alice", {**persisted, "url": args.fixture + "/article"})
        check("completed operation survives restart",
              persist_first == 200 and persist_replay == 200,
              {"first": persist_first, "after_restart": persist_replay})
        check("changed payload after restart still conflicts",
              persist_conflict == 409
              and persist_conflict_data.get("detail", {}).get("code")
              == "operation_id_payload_conflict",
              {"status": persist_conflict})

        restore = {
            "session": session,
            "url": args.fixture + "/state",
            "steps": [{"action": "snapshot"}],
            "public_only": False,
            "allowed_hosts": [],
        }
        status, data = await direct_drive("alice", restore)
        restored = (data.get("session") or {}).get("restored_from_checkpoint")
        check("checkpoint restore for owner", status == 200 and restored is True,
              {"status": status, "restored": restored})
        status, data = await direct_drive("bob", restore)
        check("checkpoint not readable by another owner",
              status == 403 and data.get("detail", {}).get("code") == "session_owner_mismatch",
              {"status": status})

        # Rotation: rewrite the public key while the worker is running.
        if args.rotate:
            read = {"urls": [args.fixture + "/article"],
                    "browser_config": {"type": "BrowserConfig",
                                       "params": {"headless": True}}}
            old = sign_read(read, "alice", f"p3-rotation-{stamp}")
            worker = httpx.Client(timeout=90)
            first = worker.post(args.worker + "/crawl", json=read,
                                headers={"X-DNB-Delegation": old})
            private = Path(args.private_key)
            public = Path(args.public_key)
            private.replace(private.with_suffix(".pre-rotation.pem"))
            public.replace(public.with_suffix(".pre-rotation.pem"))
            from dethrottled.delegation import ensure_keys
            ensure_keys()
            os.chmod(public, 0o644)
            second = worker.post(args.worker + "/crawl", json=read,
                                 headers={"X-DNB-Delegation": old})
            new = sign_read(read, "alice", f"p3-rotation-{stamp}")
            third = worker.post(args.worker + "/crawl", json=read,
                                headers={"X-DNB-Delegation": new})
            check("rotation rejects old token",
                  first.status_code == 200 and second.status_code == 403,
                  {"before": first.status_code, "after": second.status_code})
            check("rotation accepts new token", third.status_code == 200,
                  {"status": third.status_code})

        # Redaction: bearer, delegation, assertion and key material.
        log_texts = {}
        for path in args.logs:
            log_texts[path] = (
                Path(path).read_text(errors="replace") if Path(path).exists() else ""
            )
        if args.worker_container:
            proc = subprocess.run(
                ["docker", "logs", args.worker_container],
                capture_output=True, text=True,
            )
            log_texts[f"{args.worker_container}:stdout"] = proc.stdout
            log_texts[f"{args.worker_container}:stderr"] = proc.stderr
        secrets = {
            **{f"bearer/{name}": value for name, value in tokens.items()},
            **{f"delegation/{index}": value for index, value in enumerate(SECRETS)},
        }
        findings = {}
        for name, text in log_texts.items():
            found = [label for label, value in secrets.items() if value and value in text]
            if "eyJhbGciOiJFZERTQSIs" in text:
                found.append("eddsa-jwt")
            if "BEGIN PRIVATE KEY" in text or "BEGIN RSA PRIVATE KEY" in text:
                found.append("pem-private-key")
            findings[name] = found
        check("logs expose no bearer/delegation/assertion/key material",
              all(not found for found in findings.values()), findings)

        results = {
            "checks": checks,
            "passed": sum(1 for item in checks if item["passed"]),
            "failed": sum(1 for item in checks if not item["passed"]),
            "worker_status_before": before,
            "worker_status_after": await worker_status(),
        }
    (output / "phase3-wire.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps({k: results[k] for k in ("passed", "failed")}, indent=2))
    return 0 if results["failed"] == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default="http://127.0.0.1:19983")
    parser.add_argument("--core", default="http://127.0.0.1:19984")
    parser.add_argument("--mcp", default="http://127.0.0.1:19982/mcp")
    parser.add_argument("--worker", default="http://127.0.0.1:19888")
    parser.add_argument("--fixture", default="http://127.0.0.1:8090")
    parser.add_argument("--tokens", default="/tmp/opencode/p3/tokens.json")
    parser.add_argument("--private-key", default="/tmp/opencode/p3/keys/private.pem")
    parser.add_argument("--public-key", default="/tmp/opencode/p3/keys/public.pem")
    parser.add_argument("--logs", nargs="*", default=[])
    parser.add_argument("--rotate", action="store_true")
    parser.add_argument("--worker-container", default="")
    parser.add_argument("--output", default="/tmp/opencode/p3")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args)))
