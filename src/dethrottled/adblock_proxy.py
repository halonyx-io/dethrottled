"""Private, per-context HTTP/CONNECT gate; TLS remains end-to-end.

Runs on the browser's existing asyncio loop, not a service/process/container.
Chaining keeps Crawl4AI's existing DNS-pinning/security proxy authoritative.
"""

from __future__ import annotations

import asyncio
import base64
import time
from collections import deque
from contextlib import suppress
from urllib.parse import urlsplit

try:
    from . import adblock
except ImportError:
    import dethrottled_adblock as adblock

_connect = asyncio.open_connection


class Gate:
    def __init__(self, upstream=None, *, connector=None):
        self.connector = connector
        self.upstream = upstream or {}
        server = self.upstream.get("server", "")
        self.up = urlsplit(server if "://" in server else "http://" + server) if server else None
        if self.up and (self.up.scheme != "http" or not self.up.hostname):
            raise ValueError("adblock_upstream_proxy_requires_http")
        self.events = deque(maxlen=100)
        self.tasks, self.writers = set(), set()
        self.capacity = asyncio.Semaphore(128)
        self.server = None

    async def start(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0, limit=65536)
        self.url = "http://127.0.0.1:" + str(self.server.sockets[0].getsockname()[1])
        return {"server": self.url, "bypass": "<-loopback>"}

    def blocked(self, url):
        domain = adblock.FILTER.match(url)
        if domain:
            adblock.FILTER.blocked(domain, "browser")
            self.events.append({"domain": domain, "kind": "browser", "at": time.monotonic()})
        return domain

    async def reply(self, writer, status, text):
        body = text.encode()
        policy_header = "X-Dethrottled-Blocked: adblock\r\n" if status.startswith("451 ") else ""
        writer.write(
            (
                f"HTTP/1.1 {status}\r\nContent-Length: {len(body)}\r\n"
                f"Connection: close\r\n{policy_header}\r\n"
            ).encode()
            + body
        )
        await writer.drain()

    def auth(self):
        if not self.upstream.get("username"):
            return b""
        secret = (self.upstream["username"] + ":" + self.upstream.get("password", "")).encode()
        return b"Proxy-Authorization: Basic " + base64.b64encode(secret) + b"\r\n"

    async def tunnel(self, source, destination, url):
        # The connection was admitted in handle(). Rule refreshes govern new
        # connections, not arbitrary chunks of a TLS download or WebSocket.
        while True:
            chunk = await source.read(65536)
            if not chunk:
                return
            destination.write(chunk)
            await destination.drain()

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        self.writers.add(writer)
        remote = None
        try:
            async with self.capacity:
                header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=15)
                line, rest = header.split(b"\r\n", 1)
                method, target, _ = line.decode("latin-1").split(" ", 2)
                connect = method.upper() == "CONNECT"
                parsed = urlsplit("https://" + target if connect else target)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
                    await self.reply(writer, "400 Bad Request", "invalid_proxy_target")
                    return
                url = parsed.geturl()
                domain = self.blocked(url)
                if domain:
                    await self.reply(
                        writer, "451 Blocked by Dethrottled", "adblock_blocked:" + domain
                    )
                    return
                port = parsed.port or (443 if connect else 80)
                host = parsed.hostname
                if self.up:
                    host, port = self.up.hostname, self.up.port or 80
                try:
                    up_reader, remote = await asyncio.wait_for(
                        (self.connector or _connect)(host, port), timeout=15
                    )
                except PermissionError as exc:
                    if self.connector is None:
                        raise
                    self.events.append(
                        {
                            "kind": "network_policy",
                            "domain": host,
                            "reason": str(exc),
                            "at": time.monotonic(),
                        }
                    )
                    await self.reply(writer, "403 Forbidden", str(exc))
                    return
                self.writers.add(remote)
                if connect:
                    if self.up:
                        remote.write(
                            b"CONNECT "
                            + target.encode("latin-1")
                            + b" HTTP/1.1\r\nHost: "
                            + target.encode("latin-1")
                            + b"\r\n"
                            + self.auth()
                            + b"\r\n"
                        )
                        await remote.drain()
                        response = await asyncio.wait_for(
                            up_reader.readuntil(b"\r\n\r\n"), timeout=15
                        )
                        writer.write(response)
                        await writer.drain()
                        if response.split(b" ", 2)[1] != b"200":
                            return  # Preserve upstream rejection; never retry direct.
                    else:
                        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                        await writer.drain()
                else:
                    # One HTTP request per connection. HTTPS/WS tunnel bytes are
                    # untouched; browser cookies, TLS and certificates stay native.
                    lines = rest.split(b"\r\n")
                    upgrade = any(x.lower().startswith(b"upgrade:") for x in lines)
                    headers = [
                        x
                        for x in lines
                        if x
                        and not x.lower().startswith(
                            (b"proxy-authorization:", b"proxy-connection:", b"connection:")
                        )
                    ]
                    headers.append(b"Connection: Upgrade" if upgrade else b"Connection: close")
                    path = (
                        target
                        if self.up
                        else (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
                    )
                    remote.write(
                        (method + " " + path + " HTTP/1.1\r\n").encode("latin-1")
                        + b"\r\n".join(headers)
                        + b"\r\n"
                        + self.auth()
                        + b"\r\n"
                    )
                    await remote.drain()
                outbound = asyncio.create_task(self.tunnel(reader, remote, url))
                inbound = asyncio.create_task(self.tunnel(up_reader, writer, url))
                try:
                    await asyncio.wait({outbound, inbound}, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    outbound.cancel()
                    inbound.cancel()
                    await asyncio.gather(outbound, inbound, return_exceptions=True)
        except (
            OSError,
            ValueError,
            asyncio.TimeoutError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
        ):
            pass  # Browser receives a closed connection; policy refusals carry 451 above.
        finally:
            for stream in [writer, remote]:
                if stream:
                    stream.close()
                    with suppress(OSError):
                        await stream.wait_closed()
                    self.writers.discard(stream)
            self.tasks.discard(task)

    async def close(self):
        if self.server:
            self.server.close()
        for writer in list(self.writers):
            writer.close()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.server:
            await self.server.wait_closed()
