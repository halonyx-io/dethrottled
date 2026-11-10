"""Ensure the address validated is the address dialled, including rebinding."""

import asyncio
from unittest.mock import AsyncMock

import network_policy as network
import pytest


def test_resolve_once_connect_only_numeric_ip(monkeypatch):
    async def check():
        loop = asyncio.get_running_loop()
        resolve = AsyncMock(return_value=[(2, 1, 6, "", ("93.184.216.34", 443))])
        connect = AsyncMock(return_value=("reader", "writer"))
        monkeypatch.setattr(loop, "getaddrinfo", resolve)
        monkeypatch.setattr(network.asyncio, "open_connection", connect)
        assert await network.pinned_connect("rebinding.example", 443) == ("reader", "writer")
        resolve.assert_awaited_once()
        connect.assert_awaited_once_with("93.184.216.34", 443)

    asyncio.run(check())


@pytest.mark.parametrize(
    "addresses", [["127.0.0.1"], ["169.254.169.254"], ["::1"], ["93.184.216.34", "198.51.100.1"]]
)
def test_no_private_or_mixed_answers_are_dialled(monkeypatch, addresses):
    async def check():
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(
            loop,
            "getaddrinfo",
            AsyncMock(return_value=[(2, 1, 6, "", (ip, 443)) for ip in addresses]),
        )
        connect = AsyncMock()
        monkeypatch.setattr(network.asyncio, "open_connection", connect)
        with pytest.raises(PermissionError):
            await network.pinned_connect("rebinding.example", 443)
        connect.assert_not_awaited()

    asyncio.run(check())


def test_allowed_host_is_checked_before_resolution(monkeypatch):
    async def check():
        resolve = AsyncMock()
        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
        with pytest.raises(PermissionError, match="allowed_host"):
            await network.pinned_connect("other.example", 443, allowed_hosts=("allowed.example",))
        resolve.assert_not_awaited()

    asyncio.run(check())
