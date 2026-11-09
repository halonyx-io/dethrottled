"""Small in-memory, same-owner render pool. No reassignment or persisted storage."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import HTTPException


@dataclass
class Entry:
    state: dict | None = None
    busy: bool = True
    used: float = 0
    uses: int = 0


class ContextPool:
    def __init__(self, create, close, *, maximum=4, ttl=60, max_uses=200, pressure=lambda: False):
        self.create, self.close, self.pressure = create, close, pressure
        self.maximum, self.ttl, self.max_uses = maximum, ttl, max_uses
        self.entries = {}
        self.lock = asyncio.Lock()

    async def reap(self, now=None):
        now = time.monotonic() if now is None else now
        async with self.lock:
            expired = [
                key
                for key, e in self.entries.items()
                if not e.busy and (now - e.used >= self.ttl or self.pressure())
            ]
            states = [self.entries.pop(key).state for key in expired]
        for state in states:
            if state:
                await self.close(state)

    async def shutdown(self):
        async with self.lock:
            states = [e.state for e in self.entries.values()]
            self.entries.clear()
        for state in states:
            if state:
                await self.close(state)

    @asynccontextmanager
    async def lease(self, key):
        await self.reap()
        if self.pressure():
            raise HTTPException(503, "render paused for memory pressure")
        evicted = None
        async with self.lock:
            entry = self.entries.get(key)
            reused = entry is not None
            if entry and entry.busy:
                raise HTTPException(409, "render session busy; serialize requests in this session")
            if entry and entry.uses >= self.max_uses:
                evicted = self.entries.pop(key).state
                entry, reused = None, False
            if not entry:
                if len(self.entries) >= self.maximum:
                    idle = [(k, e) for k, e in self.entries.items() if not e.busy]
                    if not idle:
                        raise HTTPException(503, "render context pool busy")
                    old_key, _old = min(idle, key=lambda pair: pair[1].used)
                    evicted = self.entries.pop(old_key).state
                entry = self.entries[key] = Entry()
            entry.busy = True
        try:
            if evicted:
                await self.close(evicted)
            if not entry.state:
                # Cancellation cannot abandon a successfully created context.
                creation = asyncio.create_task(self.create())
                try:
                    entry.state = await asyncio.shield(creation)
                except asyncio.CancelledError:
                    from lifecycle import cleanup

                    entry.state = await cleanup(creation)
                    raise
            yield entry.state, reused
        except BaseException:
            async with self.lock:
                self.entries.pop(key, None)
            if entry.state:
                await self.close(entry.state)
            raise
        else:
            async with self.lock:
                entry.busy, entry.used = False, time.monotonic()
                entry.uses += 1
