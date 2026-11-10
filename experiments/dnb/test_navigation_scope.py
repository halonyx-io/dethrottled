"""Separate navigation authority from explicitly trusted asset authority."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import network_policy as network
import pytest


def test_public_assets_do_not_inherit_document_allowlist():
    scope = network.Scope(True, ("origin.test",), None, "origin.test")
    assert scope.navigation_hosts == ("origin.test",)
    assert scope.assets == scope.egress == ()


def test_internal_assets_require_trusted_authority():
    scope = network.Scope(False, ("origin.test",), None, "origin.test")
    assert scope.assets == scope.egress == ("origin.test",)
    widened = network.Scope(False, ("origin.test",), ("cdn.test",), "origin.test")
    assert widened.egress == ("cdn.test", "origin.test")
    assert widened.navigation_hosts == ("origin.test",)
    assert scope != widened


def test_explicit_empty_public_asset_list_is_restrictive():
    scope = network.Scope(True, ("origin.test",), (), "origin.test")
    assert scope.assets == ("origin.test",)
    assert scope.egress == ("origin.test",)  # Also governs non-Fetch protocols.


def test_drive_session_cannot_silently_change_asset_scope():
    async def check():
        class Browser:
            new_context = AsyncMock()

        class Context:
            close = AsyncMock()

        original = AsyncMock()
        service = SimpleNamespace(
            _make_drive_state=AsyncMock(),
            _get_drive_state=original,
            browser_api=SimpleNamespace(Browser=Browser, BrowserContext=Context),
            DRIVE_SESSIONS={
                "session": {"dnb_scope": network.Scope(True, ("origin.test",), None, "origin.test")}
            },
        )
        selected = [None]
        network.install_drive_policy(
            service, None, asset_policy=lambda: (selected[0], "origin.test")
        )
        body = SimpleNamespace(session="session", public_only=True, allowed_hosts=[])
        await service._get_drive_state(None, body)
        original.assert_awaited_once()
        selected[0] = ("cdn.test",)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as error:
            await service._get_drive_state(None, body)
        assert error.value.status_code == 409
        assert original.await_count == 1

    asyncio.run(check())


def test_browser_control_endpoint_is_never_an_asset(monkeypatch):
    import navigation_guard

    async def check():
        monkeypatch.setattr(navigation_guard, "DEBUG_PORTS", {17777})
        monkeypatch.setattr(
            asyncio.get_running_loop(),
            "getaddrinfo",
            AsyncMock(return_value=[(2, 1, 6, "", ("127.0.0.1", 17777))]),
        )
        connect = AsyncMock()
        monkeypatch.setattr(network.asyncio, "open_connection", connect)
        with pytest.raises(PermissionError, match="browser_control_endpoint"):
            await network.pinned_connect(
                "localhost", 17777, public_only=False, allowed_hosts=("localhost",)
            )
        connect.assert_not_awaited()

    asyncio.run(check())


def test_unexpected_policy_disconnect_closes_browser():
    import navigation_guard

    async def check():
        class Socket:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        class Browser:
            def on(self, *args):
                pass

            def is_connected(self):
                return True

            close = AsyncMock()

        browser = Browser()
        guard = navigation_guard.Guard(browser, SimpleNamespace(close=AsyncMock()), Socket())
        await guard.reader
        browser.close.assert_awaited_once()
        await guard.close()

    asyncio.run(check())


@pytest.mark.parametrize("stage", ["page_creation", "policy_install"])
def test_failed_drive_scope_setup_closes_context_and_gate(monkeypatch, stage):
    import navigation_guard

    async def check():
        closed = AsyncMock()

        class Context:
            async def close(self):
                await closed()

        ctx = Context()

        class Browser:
            async def new_context(self, **kwargs):
                return ctx

        gate = SimpleNamespace(start=AsyncMock(return_value={}), close=AsyncMock(), events=[])

        async def make(browser, *args, **kwargs):
            await browser.new_context()
            if stage == "page_creation":
                raise RuntimeError("page setup failed")
            return {"context": ctx}

        service = SimpleNamespace(
            _make_drive_state=make,
            _get_drive_state=AsyncMock(),
            DRIVE_SESSIONS={},
            browser_api=SimpleNamespace(Browser=Browser, BrowserContext=Context),
        )
        monkeypatch.setattr(
            navigation_guard, "install", AsyncMock(side_effect=RuntimeError("guard failed"))
        )
        network.install_drive_policy(service, lambda **kwargs: gate)
        with pytest.raises(RuntimeError):
            await service._make_drive_state(Browser(), ["origin.test"], public_only=True)
        closed.assert_awaited_once()
        gate.close.assert_awaited_once()

    asyncio.run(check())
