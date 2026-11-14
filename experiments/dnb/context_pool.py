"""Small in-memory, same-owner render pool. No reassignment or persisted storage."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from fastapi import HTTPException


@dataclass
class Entry:
    state: dict | None = None
    busy: bool = True
    used: float = 0
    uses: int = 0
    tabs: int = 0  # extra tabs lent while the main lease is busy
    # Set once the context exists (or failed to). Concurrent requests arrive
    # together, so a tab request often finds the context still being created.
    ready: asyncio.Event = field(default_factory=asyncio.Event)


class ContextPool:
    TAB_WAIT = 15.0  # seconds a tab request waits for its context to exist
    def __init__(self, create, close, *, maximum=4, ttl=60, max_uses=200, pressure=lambda: False,
                 fork=None, max_tabs=1):
        self.create, self.close, self.pressure = create, close, pressure
        self.maximum, self.ttl, self.max_uses = maximum, ttl, max_uses
        # fork(state) is an async context manager yielding a per-request view
        # on a new tab of the same context. Concurrent requests for one key
        # share the context (and its renderer process for that site) instead
        # of being refused: measured 5 same-site tabs in one context at +184 MB
        # and 101 ms to open, against +429 MB and 496 ms for 5 contexts.
        self.fork, self.max_tabs = fork, max(1, max_tabs)
        self.entries = {}
        self.lock = asyncio.Lock()

    async def reap(self, now=None):
        now = time.monotonic() if now is None else now
        async with self.lock:
            expired = [
                key
                for key, e in self.entries.items()
                if not e.busy and not e.tabs and (now - e.used >= self.ttl or self.pressure())
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
        tab = None
        async with self.lock:
            entry = self.entries.get(key)
            reused = entry is not None
            if entry and entry.busy:
                if not (self.fork and 1 + entry.tabs < self.max_tabs):
                    raise HTTPException(
                        409, "render session busy; serialize requests in this session")
                entry.tabs += 1
                tab = entry
            elif entry and entry.uses >= self.max_uses and not entry.tabs:
                evicted = self.entries.pop(key).state
                entry, reused = None, False
            if tab is None and not entry:
                if len(self.entries) >= self.maximum:
                    idle = [(k, e) for k, e in self.entries.items()
                            if not e.busy and not e.tabs]
                    if not idle:
                        raise HTTPException(503, "render context pool busy")
                    old_key, _old = min(idle, key=lambda pair: pair[1].used)
                    evicted = self.entries.pop(old_key).state
                entry = self.entries[key] = Entry()
            if tab is None:
                entry.busy = True
        if tab is not None:
            try:
                if tab.state is None:
                    try:
                        await asyncio.wait_for(tab.ready.wait(), timeout=self.TAB_WAIT)
                    except TimeoutError:
                        pass
                if tab.state is None or self.entries.get(key) is not tab:
                    raise HTTPException(
                        409, "render session busy; serialize requests in this session")
                async with self.fork(tab.state) as view:
                    yield view, True
            finally:
                async with self.lock:
                    tab.tabs -= 1
                    tab.used = time.monotonic()
            return
        try:
            if evicted:
                await self.close(evicted)
            if not entry.state:
                # Cancellation cannot abandon a successfully created context.
                creation = asyncio.create_task(self.create())
                try:
                    entry.state = await asyncio.shield(creation)
                    entry.ready.set()
                except asyncio.CancelledError:
                    from lifecycle import cleanup

                    entry.state = await cleanup(creation)
                    raise
            yield entry.state, reused
        except BaseException:
            entry.ready.set()  # waiting tab requests see the failure
            async with self.lock:
                self.entries.pop(key, None)
            if entry.state:
                await self.close(entry.state)
            raise
        else:
            async with self.lock:
                entry.busy, entry.used = False, time.monotonic()
                entry.uses += 1
