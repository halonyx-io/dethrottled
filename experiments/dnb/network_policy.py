"""Render-only network admission: resolve once, validate all IPs, dial numeric IP.

Uses the existing adblock HTTP/CONNECT gate; no TLS interception or new service.
"""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Scope:
    public_only: bool
    navigation_hosts: tuple = ()
    asset_hosts: tuple | None = None
    initial_host: str = ""

    @property
    def assets(self):
        if self.public_only and self.asset_hosts is None:
            return ()  # Any public destination, still pinned/filtered per connection.
        return tuple(
            sorted(
                set((self.initial_host, *self.navigation_hosts, *(self.asset_hosts or ()))) - {""}
            )
        )

    @property
    def egress(self):
        return self.assets


async def pinned_connect(host, port, *, public_only=True, allowed_hosts=()):
    normalized = host.lower().rstrip(".")
    if allowed_hosts and not any(
        normalized == pattern.lstrip("*.")
        or (pattern.startswith("*.") and normalized.endswith("." + pattern[2:]))
        for pattern in allowed_hosts
    ):
        raise PermissionError("network_policy:allowed_host")
    loop = asyncio.get_running_loop()
    rows = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(row[4][0] for row in rows))
    if not addresses or (
        public_only and any(not ipaddress.ip_address(ip).is_global for ip in addresses)
    ):
        raise PermissionError("network_policy:non_public_destination")
    from navigation_guard import DEBUG_PORTS

    if port in DEBUG_PORTS and any(ipaddress.ip_address(ip).is_loopback for ip in addresses):
        raise PermissionError("network_policy:browser_control_endpoint")
    error = None
    for ip in addresses:
        try:
            return await asyncio.open_connection(ip, port)
        except OSError as exc:
            error = exc
    raise error or OSError("network_policy:no_address")


def memory_pressure():
    try:
        limit = Path("/sys/fs/cgroup/memory.max").read_text().strip()
        if limit != "max":
            return int(Path("/sys/fs/cgroup/memory.current").read_text()) > int(limit) * 0.85
    except (OSError, ValueError):
        pass
    try:
        info = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
        return int(info["MemAvailable"].split()[0]) < int(info["MemTotal"].split()[0]) * 0.15
    except (OSError, ValueError, KeyError):
        return False


def install_drive_policy(service, gate_type, asset_policy=lambda: (None, "")):
    """Keep existing drive behavior, adding pinning at context creation only."""
    from contextvars import ContextVar

    selected = ContextVar("dnb_drive_network", default=None)
    original_make = service._make_drive_state
    original_context = service.browser_api.Browser.new_context
    original_close = service.browser_api.BrowserContext.close

    async def make(browser, allowed_hosts, public_only=False, **kwargs):
        # A drive scope is explicit. Internal scopes with no host boundary cannot
        # safely enable arbitrary external assets; the initial URL is supplied by
        # the request-scoped callback when no navigation host was specified.
        extra, initial = asset_policy()
        hosts = tuple(allowed_hosts) or (() if public_only else (initial,) if initial else ())
        network = Scope(public_only, hosts, extra, initial)
        if not public_only and not network.egress:
            raise ValueError("internal_drive_requires_navigation_scope")
        created = []
        token = selected.set((network, created))
        try:
            state = await original_make(browser, [], public_only=False, **kwargs)
            state["allowed_hosts"] = list(hosts)
            state["public_only"] = public_only
            from navigation_guard import install

            await install(state["context"], network, state["context"]._dnb_drive_gate.events)
            state["dnb_scope"] = network
            return state
        except BaseException:
            from lifecycle import cleanup

            await cleanup(asyncio.gather(*(ctx.close() for ctx in created)))
            raise
        finally:
            selected.reset(token)

    async def context(browser, *args, **kwargs):
        selection = selected.get()
        if selection is None:
            return await original_context(browser, *args, **kwargs)
        scope, created = selection
        from functools import partial

        gate = gate_type(
            connector=partial(
                pinned_connect, public_only=scope.public_only, allowed_hosts=scope.egress
            )
        )
        kwargs["proxy"] = await gate.start()
        creation = asyncio.create_task(original_context(browser, *args, **kwargs))
        try:
            result = await asyncio.shield(creation)
            result._dnb_drive_gate = gate
            created.append(result)
            return result
        except asyncio.CancelledError:
            from lifecycle import cleanup

            async def abandon():
                result = await creation
                await result.close()
                await gate.close()

            await cleanup(abandon())
            raise
        except BaseException:
            await gate.close()
            raise

    async def close(context, *args, **kwargs):
        try:
            return await original_close(context, *args, **kwargs)
        finally:
            gate = getattr(context, "_dnb_drive_gate", None)
            if gate:
                await gate.close()

    original_get = service._get_drive_state

    async def get_state(browser, body):
        old = service.DRIVE_SESSIONS.get(body.session) if body.session else None
        if old and old.get("dnb_scope"):
            previous = old["dnb_scope"]
            extra, _initial = asset_policy()
            effective = Scope(
                body.public_only,
                tuple(body.allowed_hosts) or previous.navigation_hosts,
                extra,
                previous.initial_host,
            )
            if effective != previous:
                from fastapi import HTTPException

                raise HTTPException(409, "session_scope_changed_use_new_session")
        return await original_get(browser, body)

    service._get_drive_state = get_state
    service._make_drive_state = make
    service.browser_api.Browser.new_context = context
    service.browser_api.BrowserContext.close = close
