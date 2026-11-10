"""Phase 1 wire/capacity/journal gates. Local fixtures only; restarts lab worker.

Run with PyJWT[crypto] and httpx. Requires the phase-1 signed lab instance on
19985, fixture host port 19987 and a private --keys directory. No production data.
"""

import argparse
import asyncio
import json
import os
import subprocess
import time
from pathlib import Path

import httpx


async def main(output, keys):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from dethrottled.delegation import sign

    os.environ["DETHROTTLED_DNB_PRIVATE_KEY"] = str(keys / "private.pem")
    os.environ["DETHROTTLED_DNB_PUBLIC_KEY"] = str(keys / "public.pem")
    output.mkdir(parents=True, exist_ok=True)
    base = "http://127.0.0.1:19985"
    fixture = "http://fixture:8090"
    container = "dethrottled-dnb-phase1"
    checks = {}
    async with httpx.AsyncClient(timeout=60) as client:

        async def status():
            return (await client.get(base + "/dnb/status")).json()

        async def wait_for(predicate, limit=10):
            end = time.monotonic() + limit
            while time.monotonic() < end:
                try:
                    value = await predicate()
                    if value:
                        return value
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.05)
            raise AssertionError("bounded condition not reached")

        async def available():
            state = await status()
            return (
                state
                if not state["active"] and not state["waiting"] and not state["drive_inflight"]
                and not state["extraction"]["active"]
                else None
            )

        async def send(path, body, session="", operation="", owner="wire-caller"):
            token = sign(
                body,
                owner=owner,
                session=session,
                scope="phase1-lab",
                public_only=False,
                allowed_hosts=(),
                operation=operation,
                path=path,
            )
            return await client.post(base + path, json=body, headers={"X-DNB-Delegation": token})

        async def healthy():
            response = await send(
                "/crawl", {"urls": [fixture + "/article"]}, owner="independent-healthy-caller"
            )
            assert response.status_code == 200, response.text
            row = response.json()["results"][0]
            assert row["success"] and "cobalt-731" in row["markdown"]["raw_markdown"]
            return True

        async def cancel(jobs):
            for job in jobs:
                job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
            started = time.monotonic()
            state = await wait_for(available)
            await healthy()
            return {
                "capacity_recovery_seconds": round(time.monotonic() - started, 3),
                "state": state,
            }

        await wait_for(lambda: healthy(), 30)
        # Active requests + four queued; the next request is refused, not started.
        stalled = {
            "urls": [fixture + "/article"],
            "crawler_config": {
                "type": "CrawlerRunConfig",
                "params": {"wait_for": "css:#never", "page_timeout": 15000},
            },
        }
        first = asyncio.create_task(send("/crawl", stalled, session="one", operation="same-op"))
        second = asyncio.create_task(send("/crawl", stalled, session="two"))

        async def two_active():
            return (await status())["active"] == 2

        await wait_for(two_active)
        duplicate = await send("/crawl", stalled, session="one", operation="same-op")
        assert (
            duplicate.status_code == 409
            and duplicate.json()["detail"]["code"] == "operation_in_progress"
        )
        changed = {**stalled, "urls": [fixture + "/long"]}
        conflict = await send("/crawl", changed, session="one", operation="same-op")
        assert conflict.status_code == 409 and not conflict.json()["detail"]["retryable"]
        queued = [asyncio.create_task(send("/crawl", stalled)) for _ in range(4)]

        async def four_waiting():
            return (await status())["waiting"] == 4

        await wait_for(four_waiting)
        refused = await send("/crawl", stalled)
        assert refused.status_code == 503 and refused.headers["retry-after"] == "1"
        assert refused.json()["detail"]["retryable"]
        checks["queue_cancel_and_retry"] = await cancel([first, second, *queued])
        output.joinpath("wire-progress.json").write_text(json.dumps(checks, indent=2) + "\n")
        # Disconnect only after both real extraction processes are occupied.
        huge = {
            "urls": [fixture + "/huge"],
            "crawler_config": {
                "type": "CrawlerRunConfig",
                "params": {"page_timeout": 20000, "delay_before_return_html": 0},
            },
        }
        jobs = [asyncio.create_task(send("/crawl", huge)) for _ in range(2)]

        async def extracting():
            return (await status())["extraction"]["active"] == 2

        await wait_for(extracting, 20)
        prior = (await status())["extraction"]["counts"].get("cancelled", 0)
        checks["extracting_disconnect"] = await cancel(jobs)
        after = (await status())["extraction"]["counts"]
        assert after.get("cancelled", 0) >= prior + 2, after
        checks["extracting_disconnect"]["cancelled_workers"] = after["cancelled"] - prior
        output.joinpath("wire-progress.json").write_text(json.dumps(checks, indent=2) + "\n")
        # A busy renderer either closes within its deadline or causes a bounded
        # fail-stop/restart. Both must leave a subsequent healthy read possible.
        busy = {
            "urls": [fixture + "/busy"],
            "crawler_config": {
                "type": "CrawlerRunConfig",
                "params": {"page_timeout": 1000, "delay_before_return_html": 0.2},
            },
        }
        began = time.monotonic()
        try:
            response = await send("/crawl", busy)
            assert response.status_code == 504, response.text
            checks["busy_renderer"] = {"status": 504, "code": response.json()["detail"]["code"]}
        except httpx.HTTPError:
            checks["busy_renderer"] = {"status": "connection_closed_on_fail_stop"}
        await wait_for(lambda: healthy(), 30)
        checks["busy_renderer"]["recovery_seconds"] = round(time.monotonic() - began, 3)

        output.joinpath("wire-progress.json").write_text(json.dumps(checks, indent=2) + "\n")

        async def mutations():
            return int((await client.get("http://127.0.0.1:19987/mutation-count")).text)

        def drive_body(name):
            return {
                "url": fixture + "/mutate",
                "session": name,
                "operation_id": name,
                "steps": [
                    {"action": "click", "selector": "#mutate"},
                    {"action": "wait", "ms": 10000},
                ],
                "timeout_ms": 20000,
                "screenshot": "never",
            }

        async def occurred(before):
            return (await mutations()) > before

        before = await mutations()
        body = drive_body("cancel-mutation")
        job = asyncio.create_task(send("/drive", body, session=body["session"]))
        await wait_for(lambda: occurred(before))
        checks["drive_cancel"] = await cancel([job])
        retry = await send("/drive", body, session=body["session"])
        assert retry.status_code == 409 and not retry.json()["detail"]["retryable"], retry.text
        assert await mutations() == before + 1
        checks["drive_cancel"]["mutation_not_replayed"] = True
        output.joinpath("wire-progress.json").write_text(json.dumps(checks, indent=2) + "\n")
        before = await mutations()
        body = drive_body("crash-mutation")
        job = asyncio.create_task(send("/drive", body, session=body["session"]))
        await wait_for(lambda: occurred(before))
        restarts = int(
            subprocess.check_output(
                ["docker", "inspect", container, "--format", "{{.RestartCount}}"], text=True
            )
        )
        # Kill uvicorn inside the disposable container, so restart policy—not a
        # clean application shutdown—must recover the in-flight operation.
        script = """from pathlib import Path
import os,signal
for f in Path('/proc').glob('[0-9]*/cmdline'):
 try:a=f.read_bytes().split(b'\\0')
 except OSError:continue
 if b'dnb_service:app'in a and any(b'uvicorn'in x for x in a[:2]):
  os.kill(int(f.parent.name),signal.SIGKILL);break
"""
        subprocess.run(["docker", "exec", container, "python", "-c", script], capture_output=True)
        await asyncio.gather(job, return_exceptions=True)
        await wait_for(lambda: healthy(), 40)
        now = int(
            subprocess.check_output(
                ["docker", "inspect", container, "--format", "{{.RestartCount}}"], text=True
            )
        )
        assert now > restarts
        retry = await send("/drive", body, session=body["session"])
        assert retry.status_code == 409 and not retry.json()["detail"]["retryable"], retry.text
        assert await mutations() == before + 1
        checks["worker_crash"] = {
            "supervisor_restart_observed": True,
            "mutation_not_replayed": True,
        }
        checks["final_status"] = await status()
        output.joinpath("wire-results.json").write_text(json.dumps(checks, indent=2) + "\n")
        print(json.dumps(checks))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--keys", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(main(args.output, args.keys))
