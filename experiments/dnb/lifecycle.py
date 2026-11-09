"""Bounded cleanup and disconnect monitoring, shared by read and drive routes."""

import asyncio
import os

CLEANUP_SECONDS = 3


async def cleanup(awaitable):
    async def bounded():
        task = asyncio.ensure_future(awaitable)
        done, _ = await asyncio.wait({task}, timeout=CLEANUP_SECONDS)
        if not done:
            os._exit(70)  # Fail closed; container supervisor removes all children.
        return await task

    task = asyncio.create_task(bounded())
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    return await task


async def until_disconnect(request, awaitable, disconnected_error):
    async def watch():
        while True:
            if await request.is_disconnected():
                return
            await asyncio.sleep(0.1)

    work = asyncio.create_task(awaitable)
    monitor = asyncio.create_task(watch()) if request else None
    try:
        if monitor is None:
            return await work
        done, _ = await asyncio.wait({work, monitor}, return_when=asyncio.FIRST_COMPLETED)
        if work in done:
            return await work
        work.cancel()
        await cleanup(asyncio.gather(work, return_exceptions=True))
        raise disconnected_error()
    finally:
        if not work.done():
            if not work.cancelling():
                work.cancel()
            await cleanup(asyncio.gather(work, return_exceptions=True))
        if monitor:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
