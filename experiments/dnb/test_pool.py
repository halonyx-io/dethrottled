"""Bounded ownership, admission and cleanup; no live browser/provider required."""

import asyncio
from unittest.mock import AsyncMock

import dnb_service as dnb
import pytest
from context_pool import ContextPool
from fastapi import HTTPException
from starlette.requests import Request


def run(coro):
    return asyncio.run(coro)


def test_reuse_and_distinct_owners():
    async def check():
        create, close = AsyncMock(side_effect=[{"id": 1}, {"id": 2}]), AsyncMock()
        pool = ContextPool(create, close)
        async with pool.lease("alice") as (one, reused):
            assert not reused
        async with pool.lease("bob") as (two, reused):
            assert not reused and two != one
        async with pool.lease("alice") as (again, reused):
            assert reused and again is one
        await pool.shutdown()
        assert create.await_count == close.await_count == 2

    run(check())


def test_busy_and_capacity_do_not_evict_active_context():
    async def check():
        close = AsyncMock()
        pool = ContextPool(AsyncMock(return_value={}), close, maximum=1)
        async with pool.lease("alice"):
            for key, code in [("alice", 409), ("bob", 503)]:
                with pytest.raises(HTTPException) as error:
                    async with pool.lease(key):
                        pass
                assert error.value.status_code == code
            close.assert_not_awaited()
        await pool.shutdown()

    run(check())


def test_eviction_and_idle_expiry_destroy_instead_of_reassigning():
    async def check():
        close = AsyncMock()
        pool = ContextPool(AsyncMock(side_effect=[{"id": 1}, {"id": 2}]), close, maximum=1)
        async with pool.lease("alice"):
            pass
        async with pool.lease("bob") as (state, reused):
            assert state["id"] == 2 and not reused
        close.assert_awaited_once_with({"id": 1})
        await pool.reap(now=pool.entries["bob"].used + 61)
        assert not pool.entries and close.await_count == 2

    run(check())


def test_failure_discards_context():
    async def check():
        close = AsyncMock()
        pool = ContextPool(AsyncMock(return_value={"id": 1}), close)
        with pytest.raises(ValueError):
            async with pool.lease("alice"):
                raise ValueError("navigation failed")
        assert not pool.entries
        close.assert_awaited_once()

    run(check())


def test_cancelled_creation_does_not_orphan_context():
    async def check():
        started, finish = asyncio.Event(), asyncio.Event()

        async def create():
            started.set()
            await finish.wait()
            return {"id": 1}

        close = AsyncMock()
        pool = ContextPool(create, close)

        async def caller():
            async with pool.lease("alice"):
                pass

        task = asyncio.create_task(caller())
        await started.wait()
        task.cancel()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        close.assert_awaited_once_with({"id": 1})
        assert not pool.entries

    run(check())


def request(**headers):
    return Request(
        {"type": "http", "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}
    )


def test_owner_requires_trusted_authorization(monkeypatch):
    with pytest.raises(HTTPException) as error:
        dnb.pool_key(request(**{"x-dnb-owner": "alice"}), "https://example.org")
    assert error.value.status_code == 403
    assert dnb.pool_key(request(), "https://example.org") is None


def claimed(**changes):
    result = request()
    result.state.dnb_claims = {
        "sub": "alice",
        "session": "one",
        "scope": "public",
        "page_mode": "fresh",
        "public_only": True,
        "allowed_hosts": [],
        **changes,
    }
    return result


def test_key_separates_owner_session_origin_and_policy(monkeypatch):
    def key(url="https://example.org", **claims):
        return dnb.pool_key(claimed(**claims), url)

    original = key()
    for claims in [
        {"sub": "bob"},
        {"session": "two"},
        {"page_mode": "persistent"},
        {"asset_hosts": ["cdn.example"]},
    ]:
        assert original != key(**claims)
    assert original != key(url="https://other.example")
    monkeypatch.setattr(dnb, "ALLOW_INTERNAL", True)
    assert original != key(public_only=False)


def test_busy_entry_survives_expiry_and_active_reuse_is_bounded():
    async def check():
        close = AsyncMock()
        pool = ContextPool(AsyncMock(side_effect=[{"id": 1}, {"id": 2}]), close, max_uses=2)
        async with pool.lease("alice"):
            await pool.reap(now=10**12)
            assert "alice" in pool.entries
        async with pool.lease("alice") as (_, reused):
            assert reused
        async with pool.lease("alice") as (state, reused):
            assert state["id"] == 2 and not reused
        close.assert_awaited_once_with({"id": 1})
        await pool.shutdown()

    run(check())


def test_authorized_default_uses_fresh_page_reuse():
    assert dnb.pool_key(claimed(), "https://example.org")[-1] == "fresh"


def test_missing_explicit_session_or_scope_does_not_reuse():
    for changes in [{"session": ""}, {"scope": ""}]:
        assert dnb.pool_key(claimed(**changes), "https://example.org") is None


def test_security_scope_config_and_allowed_hosts_are_partitioned():
    first = dnb.pool_key(claimed(), "https://example.org")
    for changes in [{"scope": "internal-app"}, {"allowed_hosts": ["example.org"]}]:
        assert first != dnb.pool_key(claimed(**changes), "https://example.org")
    assert first != dnb.pool_key(claimed(), "https://example.org", {"headless": False})


def test_pressure_evicts_idle_only_and_refuses_new_work():
    async def check():
        pressured = False
        close = AsyncMock()
        pool = ContextPool(AsyncMock(return_value={"id": 1}), close, pressure=lambda: pressured)
        async with pool.lease("active"):
            pressured = True
            await pool.reap()
            assert "active" in pool.entries
            with pytest.raises(HTTPException) as error:
                async with pool.lease("new"):
                    pass
            assert error.value.status_code == 503
        await pool.reap()
        assert not pool.entries
        close.assert_awaited_once()

    run(check())


def test_failed_navigation_is_not_masked_by_parking(monkeypatch):
    from types import SimpleNamespace

    async def check():
        park = AsyncMock(side_effect=RuntimeError("parking failure"))
        state = {
            "context": SimpleNamespace(pages=[]),
            "page": SimpleNamespace(goto=park),
            "events": {},
            "responses": [],
        }
        close = AsyncMock()
        monkeypatch.setattr(dnb, "POOL", ContextPool(AsyncMock(return_value=state), close))
        with pytest.raises(ValueError, match="original navigation"):
            async with dnb.render_state(("owner", "persistent")):
                raise ValueError("original navigation")
        park.assert_not_awaited()
        close.assert_awaited_once()

    run(check())
