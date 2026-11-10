"""Real subprocess failure/cancellation tests, without upstream/browser traffic."""

import asyncio
import os
from pathlib import Path

import pytest
from extraction_pool import ExtractionFailure, ExtractionPool

SCRIPT = """import json,time,os,signal,resource
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
signal.signal(signal.SIGXCPU,lambda *_:os._exit(128+signal.SIGXCPU))
print('{"ready":true}',flush=True)
for line in __import__('sys').stdin:
    body=json.loads(line)
    if body['html']=='stall': time.sleep(120)
    if body['html']=='crash': os._exit(12)
    if body['html']=='cpu': os.kill(os.getpid(),signal.SIGXCPU)
    if body['html']=='memory':
        resource.setrlimit(resource.RLIMIT_AS,(64*1024**2,64*1024**2))
        try:bytearray(128*1024**2)
        except MemoryError:
            print('{"ok":false,"error":"extraction_memory_limit"}',flush=True);continue
    if body['html']=='oversized':
        print('x'*20000,flush=True);continue
    print(json.dumps({'ok':True,'result':{'success':True,'pid':os.getpid()}}),flush=True)
"""


def script(tmp_path):
    path = tmp_path / "worker.py"
    path.write_text(SCRIPT)
    return path


def test_repeated_cancel_two_slots_reaps_children_and_recovers(tmp_path):
    async def check():
        pool = ExtractionPool(script=script(tmp_path))
        try:
            await pool.warm()
            for _ in range(3):
                jobs = [
                    asyncio.create_task(pool.run("https://example.org", "stall")) for _ in range(2)
                ]
                for _ in range(100):
                    if pool.available.empty():
                        break
                    await asyncio.sleep(0.01)
                pids = [p.pid for p in pool.processes.values()]
                for job in jobs:
                    job.cancel()
                await asyncio.gather(*jobs, return_exceptions=True)
                assert pool.available.qsize() == 2 and not pool.processes
                for pid in pids:
                    with pytest.raises(ProcessLookupError):
                        os.kill(pid, 0)
                healthy = await pool.run("https://example.org", "healthy")
                assert healthy["success"]
        finally:
            await pool.close()

    asyncio.run(check())


def test_deadline_and_crash_are_bounded_and_recover(tmp_path):
    async def check():
        pool = ExtractionPool(size=1, timeout=0.1, script=script(tmp_path))
        try:
            for value, code, retry in [
                ("stall", "extraction_timeout", False),
                ("crash", "extraction_worker_exit", True),
                ("cpu", "extraction_cpu_limit", False),
            ]:
                with pytest.raises(ExtractionFailure) as error:
                    await pool.run("https://example.org", value)
                assert error.value.code == code and error.value.retryable == retry
                assert pool.available.qsize() == 1
                assert (await pool.run("https://example.org", "healthy"))["success"]
        finally:
            await pool.close()

    asyncio.run(check())


def test_actual_upstream_extractor_in_bounded_process():
    async def check():
        pool = ExtractionPool(size=1)
        try:
            result = await pool.run(
                "https://example.org",
                "<article><h1>Worker fact cobalt-731</h1>"
                + "<p>This document contains useful evidence and preserves its final fact.</p>" * 30
                + "<p>Final fact amber-592</p></article>",
            )
            limits = Path(f"/proc/{pool.processes[0].pid}/limits").read_text()
            memory_line = next(
                line for line in limits.splitlines() if line.startswith("Max address space")
            )
            assert "2147483648" in memory_line
            cpu_line = next(line for line in limits.splitlines() if line.startswith("Max cpu time"))
            assert "60" in cpu_line
            text = result["markdown"]["raw_markdown"]
            assert result["success"] and "cobalt-731" in text and "amber-592" in text
        finally:
            await pool.close()

    asyncio.run(check())


def test_memory_and_protocol_limits_recover(tmp_path):
    async def check():
        pool = ExtractionPool(size=1, timeout=2, script=script(tmp_path), output_limit=4096)
        try:
            for value, code in [
                ("memory", "extraction_memory_limit"),
                ("oversized", "extraction_worker_protocol"),
            ]:
                with pytest.raises(ExtractionFailure) as error:
                    await pool.run("https://example.org", value)
                assert error.value.code == code
                assert pool.available.qsize() == 1 and not pool.processes
                assert (await pool.run("https://example.org", "healthy"))["success"]
        finally:
            await pool.close()

    asyncio.run(check())
