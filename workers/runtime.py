"""Private bytes-only child supervision shared by heavy extraction workers."""

import asyncio
import json
import os
import signal
import sys
import tempfile
import time

from fastapi import HTTPException, Request


class Runner:
    def __init__(self, program, timeout=180, suffix=".bin", max_bytes=50 * 1024 * 1024):
        self.program, self.timeout, self.suffix, self.max_bytes = (
            program,
            timeout,
            suffix,
            max_bytes,
        )
        self.busy = False
        self.pid = None
        self.counts = dict(completed=0, failed=0, timed_out=0, cancelled=0, rejected=0)
        self.started = None

    def metrics(self):
        return {
            **self.counts,
            "active": int(self.busy),
            "child_pid": self.pid,
            "active_seconds": round(time.monotonic() - self.started, 2) if self.started else 0,
            "deadline_seconds": self.timeout,
            "max_input_bytes": self.max_bytes,
        }

    async def execute(self, request: Request, options=None):
        if self.busy:
            self.counts["rejected"] += 1
            raise HTTPException(429, "worker_busy")
        self.busy = True
        self.started = time.monotonic()
        process = None
        reader = None
        try:
            with tempfile.NamedTemporaryFile(suffix=self.suffix) as source:
                async def receive_source():
                    size = 0
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > self.max_bytes:
                            raise HTTPException(413, "worker_input_limit")
                        source.write(chunk)
                await asyncio.wait_for(receive_source(), timeout=self.timeout)
                source.flush()
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    self.program,
                    source.name,
                    json.dumps(options or {}),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    start_new_session=True,
                )
                self.pid = process.pid

                async def collect():
                    chunks, size = [], 0
                    while True:
                        chunk = await process.stdout.read(65536)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > 20_000_000:
                            raise HTTPException(413, "worker_output_limit")
                        chunks.append(chunk)
                    await process.wait()
                    if process.returncode:
                        raise HTTPException(422, "worker_conversion_failed")
                    try:
                        return json.loads(b"".join(chunks))
                    except ValueError:
                        raise HTTPException(422, "worker_invalid_output") from None

                reader = asyncio.create_task(collect())
                while not reader.done():
                    if await request.is_disconnected():
                        self.counts["cancelled"] += 1
                        raise HTTPException(499, "worker_client_disconnected")
                    if time.monotonic() - self.started > self.timeout:
                        self.counts["timed_out"] += 1
                        raise HTTPException(504, "worker_deadline_exceeded")
                    await asyncio.wait({reader}, timeout=0.05)
                result = await reader
                self.counts["completed"] += 1
                return result
        except asyncio.TimeoutError:
            self.counts["timed_out"] += 1
            self.counts["failed"] += 1
            raise HTTPException(504, "worker_deadline_exceeded") from None
        except asyncio.CancelledError:
            self.counts["cancelled"] += 1
            raise
        except HTTPException:
            self.counts["failed"] += 1
            raise
        finally:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await asyncio.shield(process.wait())
            if reader is not None:
                if not reader.done():
                    reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)
            self.pid = None
            self.busy = False
            self.started = None
