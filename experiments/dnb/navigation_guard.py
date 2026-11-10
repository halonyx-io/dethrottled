"""One browser CDP policy client, before new pages/workers resume.

Public CDP over a private loopback endpoint; no TLS interception or driver internals.
Patchright remains the browser controller. The IP gate denies browser access to
this endpoint even in explicitly internal scopes. No new dependency: aiohttp is
already part of the pinned Crawl4AI distribution.
"""

import asyncio
import socket
import time
from urllib.parse import urlsplit

import aiohttp

DEBUG_PORTS = set()


def enable(browser_api):
    original = browser_api.BrowserType.launch
    if getattr(browser_api.BrowserType, "_dnb_guard_installed", False):
        return

    async def launch(kind, *args, **kwargs):
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        kwargs["args"] = [
            *kwargs.get("args", []),
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
        ]
        DEBUG_PORTS.add(port)
        try:
            browser = await original(kind, *args, **kwargs)
        except BaseException:
            DEBUG_PORTS.discard(port)
            raise
        browser._dnb_debug_port = port
        browser.on("disconnected", lambda *_: DEBUG_PORTS.discard(port))
        return browser

    launch._dnb_guard_launch = True
    browser_api.BrowserType.launch = launch
    browser_api.BrowserType._dnb_guard_installed = True
    original_close = browser_api.Browser.close

    async def close(browser, *args, **kwargs):
        try:
            return await original_close(browser, *args, **kwargs)
        finally:
            task = getattr(browser, "_dnb_navigation_guard", None)
            if task and task.done() and not task.cancelled() and task.exception() is None:
                await task.result().close()

    browser_api.Browser.close = close


def host_allowed(url, allowed):
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return bool(host) and any(
        host == p.removeprefix("*.") or (p.startswith("*.") and host.endswith("." + p[2:]))
        for p in allowed
    )


class Guard:
    def __init__(self, browser, http, socket):
        self.browser, self.http, self.socket = browser, http, socket
        self.scopes, self.sessions, self.pending = {}, {}, {}
        self.sequence = 0
        self.closing = False
        self.auto_attach = False
        self.reader = asyncio.create_task(self.receive())
        browser.on("disconnected", lambda *_: asyncio.create_task(self.close()))

    @classmethod
    async def create(cls, browser):
        http = aiohttp.ClientSession(trust_env=False)
        try:
            port = browser._dnb_debug_port
            async with http.get(
                f"http://127.0.0.1:{port}/json/version", timeout=aiohttp.ClientTimeout(total=3)
            ) as response:
                data = await response.json()
            socket = await http.ws_connect(data["webSocketDebuggerUrl"], max_msg_size=1024 * 1024)
            return cls(browser, http, socket)
        except BaseException:
            await http.close()
            raise

    async def close(self):
        self.closing = True
        await self.http.close()
        for future in list(self.pending.values()):
            if not future.done():
                future.set_exception(ConnectionError("browser policy disconnected"))
        self.pending.clear()
        self.scopes.clear()
        self.sessions.clear()

    async def send(self, method, params=None, session=None):
        self.sequence += 1
        identity = self.sequence
        message = {"id": identity, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        future = asyncio.get_running_loop().create_future()
        self.pending[identity] = future
        try:
            await self.socket.send_json(message)
            return await asyncio.wait_for(future, 3)
        finally:
            self.pending.pop(identity, None)

    async def receive(self):
        try:
            async for event in self.socket:
                if event.type != aiohttp.WSMsgType.TEXT:
                    continue
                message = event.json()
                if "id" in message:
                    future = self.pending.get(message["id"])
                    if future and not future.done():
                        if "error" in message:
                            future.set_exception(RuntimeError(str(message["error"])))
                        else:
                            future.set_result(message.get("result", {}))
                elif message.get("method") == "Target.attachedToTarget":
                    task = asyncio.create_task(self.attach(message["params"]))
                    task.add_done_callback(self.handled)
                elif message.get("method") == "Fetch.requestPaused":
                    task = asyncio.create_task(self.paused(message["sessionId"], message["params"]))
                    task.add_done_callback(self.handled)
                elif message.get("method") == "Target.detachedFromTarget":
                    self.sessions.pop(message["params"]["sessionId"], None)
        finally:
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(ConnectionError("browser policy disconnected"))
            if not self.closing and self.browser.is_connected():
                await self.browser.close()

    @staticmethod
    def handled(task):
        # Errors leave targets paused: the enclosing operation deadline tears
        # down the context. Never turn failed policy configuration into access.
        if not task.cancelled():
            task.exception()

    async def configure(self, session, selection):
        if selection:
            self.sessions[session] = selection
            await self.send("Fetch.enable", {"patterns": [{"requestStage": "Request"}]}, session)
        await self.send("Runtime.runIfWaitingForDebugger", session=session)

    async def attach(self, event):
        info = event["targetInfo"]
        selection = self.scopes.get(info.get("browserContextId"))
        await self.configure(event["sessionId"], selection)

    async def paused(self, session, event):
        scope, events = self.sessions[session]
        url = event["request"]["url"]
        document = event.get("resourceType") == "Document"
        hosts = scope.navigation_hosts if document else scope.assets
        admitted = url == "about:blank" or (
            urlsplit(url).scheme in {"http", "https"} and (not hosts or host_allowed(url, hosts))
        )
        if admitted:
            await self.send("Fetch.continueRequest", {"requestId": event["requestId"]}, session)
        else:
            events.append(
                {
                    "kind": "navigation_policy",
                    "reason": "network_policy:document_host"
                    if document
                    else "network_policy:asset_host",
                    "domain": urlsplit(url).hostname,
                    "at": time.monotonic(),
                }
            )
            await self.send(
                "Fetch.failRequest",
                {"requestId": event["requestId"], "errorReason": "BlockedByClient"},
                session,
            )


async def install(context, scope, events):
    if not scope.navigation_hosts and not scope.assets:
        return
    browser = context.browser
    if getattr(browser, "_dnb_navigation_guard", None) is None:
        browser._dnb_navigation_guard = asyncio.create_task(Guard.create(browser))
    guard = await browser._dnb_navigation_guard
    page = context.pages[0] if context.pages else await context.new_page()
    probe = await context.new_cdp_session(page)
    info = (await probe.send("Target.getTargetInfo"))["targetInfo"]
    await probe.detach()
    context_id = info["browserContextId"]
    guard.scopes[context_id] = scope, events
    context.on("close", lambda *_: guard.scopes.pop(context_id, None))
    session = (
        await guard.send("Target.attachToTarget", {"targetId": info["targetId"], "flatten": True})
    )["sessionId"]
    await guard.configure(session, (scope, events))
    if guard.auto_attach:
        return
    guard.auto_attach = True
    await guard.send(
        "Target.setAutoAttach",
        {
            "autoAttach": True,
            "waitForDebuggerOnStart": True,
            "flatten": True,
            "filter": [{"type": t} for t in ("page", "iframe", "service_worker", "worker")]
            + [{"exclude": True}],
        },
    )
