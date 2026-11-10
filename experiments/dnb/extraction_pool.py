"""Two warm, killable extraction processes; cancellation waits for real cleanup."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from collections import Counter
from pathlib import Path


class ExtractionFailure(Exception):
    def __init__(self, code, status=422, retryable=False):
        self.code, self.status, self.retryable = code, status, retryable
        super().__init__(code)


class ExtractionPool:
    def __init__(self, size=2, timeout=12, script=None, output_limit=32 * 1024**2):
        self.size, self.timeout, self.output_limit = size, timeout, output_limit
        self.script = str(script or Path(__file__).with_name("extract_worker.py"))
        self.available = asyncio.Queue(size)
        self.processes = {}
        self.counts = Counter()
        for slot in range(size):
            self.available.put_nowait(slot)

    async def _stop(self, slot):
        process = self.processes.get(slot)
        if not process:
            return
        self.counts["reaped"] += 1
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        # Closing the read pipe also releases a paused oversized-output buffer;
        # Process.wait must not depend on draining hostile output indefinitely.
        if process.stdout:
            process.stdout._transport.close()
        try:
            await asyncio.wait_for(process.wait(), 0.3)
        except TimeoutError:
            pass
        # Kill descendants as well, even if their parent exited on SIGTERM.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), 2)
        except TimeoutError:
            os._exit(70)  # Fail closed; supervisor stops this worker and its children.
        self.processes.pop(slot, None)
        if process.stdin:
            process.stdin.close()

    async def _process(self, slot):
        process = self.processes.get(slot)
        if process and process.returncode is None:
            return process
        await self._stop(slot)
        launch = asyncio.create_task(
            asyncio.create_subprocess_exec(
                sys.executable,
                "-u",
                self.script,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=self.output_limit + 1024,
                start_new_session=True,
                env={
                    **os.environ,
                    "OPENBLAS_NUM_THREADS": "1",
                    "OMP_NUM_THREADS": "1",
                    "CRAWL4AI_NO_CLOUD_NOTICE": "1",
                },
            )
        )
        try:
            process = await asyncio.shield(launch)
        except asyncio.CancelledError:
            from lifecycle import cleanup

            process = await cleanup(launch)
            self.processes[slot] = process
            await self._stop(slot)
            raise
        self.processes[slot] = process
        self.counts["started"] += 1
        ready = await asyncio.wait_for(process.stdout.readline(), 15)
        if json.loads(ready or b"{}") != {"ready": True}:
            raise ExtractionFailure("extraction_worker_startup", 503, True)
        return process

    async def warm(self):
        await asyncio.gather(*(self._process(slot) for slot in range(self.size)))

    async def run(self, url, html):
        slot = await self.available.get()
        try:
            process = await self._process(slot)
            async with asyncio.timeout(self.timeout):
                payload = json.dumps({"url": url, "html": html}, ensure_ascii=True).encode() + b"\n"
                process.stdin.write(payload)
                await process.stdin.drain()
                raw = await process.stdout.readline()
                if not raw:
                    await process.wait()
                    code = (
                        "extraction_cpu_limit"
                        if process.returncode in {-signal.SIGXCPU, 128 + signal.SIGXCPU}
                        else "extraction_worker_exit"
                    )
                    raise ExtractionFailure(
                        code, 503 if code.endswith("exit") else 422, code.endswith("exit")
                    )
                output = json.loads(raw)
                if not output.get("ok"):
                    raise ExtractionFailure(output.get("error", "extraction_failed"))
                self.counts["completed"] += 1
                if output.get("recycle"):
                    await self._stop(slot)
                return output["result"]
        except TimeoutError:
            self.counts["timeouts"] += 1
            await self._stop(slot)
            raise ExtractionFailure("extraction_timeout", 504) from None
        except asyncio.CancelledError:
            self.counts["cancelled"] += 1
            cleanup = asyncio.create_task(self._stop(slot))
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    continue
            await cleanup
            raise
        except ExtractionFailure:
            await self._stop(slot)
            raise
        except (ValueError, OSError, EOFError, asyncio.LimitOverrunError):
            await self._stop(slot)
            raise ExtractionFailure("extraction_worker_protocol", 503, True) from None
        finally:
            self.available.put_nowait(slot)

    async def close(self):
        await asyncio.gather(*(self._stop(slot) for slot in list(self.processes)))
