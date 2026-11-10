"""Phase 1 cancellation/admission contract; fake browser, real request lifecycle."""

import asyncio
from types import SimpleNamespace

import dnb_service as dnb
import lifecycle
import pytest
from fastapi import HTTPException


class Disconnection:
    def __init__(self):
        self.closed = False

    async def is_disconnected(self):
        return self.closed


def test_disconnect_waits_for_cleanup_before_return():
    async def check():
        request = Disconnection()
        started = asyncio.Event()
        released = False

        async def work():
            nonlocal released
            started.set()
            try:
                await asyncio.sleep(120)
            finally:
                await asyncio.sleep(0.02)
                released = True

        task = asyncio.create_task(
            lifecycle.until_disconnect(request, work(), lambda: ValueError("gone"))
        )
        await started.wait()
        request.closed = True
        with pytest.raises(ValueError, match="gone"):
            await task
        assert released

    asyncio.run(check())


def test_unresponsive_cleanup_requests_supervisor_restart(monkeypatch):
    class RestartRequested(BaseException):
        pass

    async def check():
        monkeypatch.setattr(lifecycle, "CLEANUP_SECONDS", 0.02)

        def restart(code):
            assert code == 70
            raise RestartRequested()

        monkeypatch.setattr(lifecycle.os, "_exit", restart)
        pending = []

        async def stuck():
            pending.append(asyncio.current_task())
            await asyncio.sleep(120)

        with pytest.raises(RestartRequested):
            await lifecycle.cleanup(stuck())
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    asyncio.run(check())


def test_busy_queue_refuses_work_with_retry_contract(monkeypatch):
    async def check():
        monkeypatch.setattr(dnb, "WAITING", 4)
        monkeypatch.setattr(dnb, "ALLOW_INTERNAL", True)
        with pytest.raises(HTTPException) as error:
            await dnb.crawl(dnb.CrawlRequest(urls=["http://fixture:8090/article"]))
        assert error.value.status_code == 503
        assert error.value.detail["retryable"] is True
        assert error.value.headers["Retry-After"] == "1"

    asyncio.run(check())


def test_inflight_read_retry_does_not_start_duplicate(monkeypatch):
    async def check():
        claims = {
            "jti": "operation",
            "sub": "caller",
            "session": "one",
            "scope": "public",
            "public_only": True,
            "allowed_hosts": [],
            "page_mode": "fresh",
        }

        class Request:
            def __init__(self):
                self.headers = {}
                self.state = SimpleNamespace(dnb_claims=claims)

            async def json(self):
                return {"urls": ["https://example.org"]}

            async def is_disconnected(self):
                return False

        async def authorize(*args, **kwargs):
            return claims

        monkeypatch.setattr(dnb, "authorize", authorize)
        started = asyncio.Event()

        async def read(*args, **kwargs):
            started.set()
            await asyncio.sleep(120)

        monkeypatch.setattr(dnb, "_crawl", read)
        body = dnb.CrawlRequest(urls=["https://example.org"])
        first = asyncio.create_task(dnb.crawl(body, Request()))
        await started.wait()
        try:
            with pytest.raises(HTTPException) as error:
                await dnb.crawl(body, Request())
            assert error.value.status_code == 409
            assert error.value.detail["code"] == "operation_in_progress"
        finally:
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
        assert not dnb.OPERATIONS

    asyncio.run(check())


def test_body_boundary_preserves_real_disconnect_channel():
    from starlette.requests import Request

    async def check():
        messages = iter(
            [
                {"type": "http.request", "body": b'{"urls":', "more_body": True},
                {"type": "http.request", "body": b"[]}", "more_body": False},
                {"type": "http.disconnect"},
            ]
        )

        async def receive():
            return next(messages)

        async def send(message):
            pass

        async def app(scope, receive, send):
            request = Request(scope, receive)
            assert await request.json() == {"urls": []}
            assert await request.is_disconnected()

        scope = {"type": "http", "method": "POST", "path": "/crawl", "headers": []}
        await dnb.WorkerBoundary(app)(scope, receive, send)

    asyncio.run(check())


@pytest.mark.parametrize("declared", [True, False])
def test_body_boundary_rejects_oversize_before_admission(declared):
    async def check():
        reached = False
        responses = []

        async def app(*args):
            nonlocal reached
            reached = True

        async def receive():
            return {"type": "http.request", "body": b"x" * (1024**2 + 1), "more_body": False}

        async def send(message):
            responses.append(message)

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/crawl",
            "headers": [(b"content-length", b"1048577")] if declared else [],
        }
        await dnb.WorkerBoundary(app)(scope, receive, send)
        assert not reached
        assert next(r for r in responses if r["type"] == "http.response.start")["status"] == 413

    asyncio.run(check())


def test_disconnect_during_body_does_not_start_work():
    async def check():
        reached = False

        async def app(*args):
            nonlocal reached
            reached = True

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            pass

        scope = {"type": "http", "method": "POST", "path": "/crawl", "headers": []}
        await dnb.WorkerBoundary(app)(scope, receive, send)
        assert not reached

    asyncio.run(check())


@pytest.mark.parametrize(
    "state,retryable", [("outcome_unknown", False), ("running", True), ("completed", False)]
)
def test_mutation_retry_does_not_allocate_browser_state(monkeypatch, state, retryable):
    from unittest.mock import AsyncMock

    async def check():
        body = dnb.browser.DriveRequest(
            url="https://example.org",
            session="retry-session",
            operation_id="operation",
            steps=[{"action": "click", "selector": "button"}],
        )
        record = {
            "fingerprint": dnb.browser._operation_fingerprint(body),
            "state": state,
            "result": {"ok": True, "steps": []},
            "created": 0,
        }
        monkeypatch.setattr(
            dnb.browser, "DRIVE_OPERATIONS", {("retry-session", "operation"): record}
        )
        original = AsyncMock()
        monkeypatch.setattr(dnb, "ORIGINAL_DRIVE", original)
        if state == "completed":
            result = await dnb.bounded_drive(body, None)
            assert result["operation_replayed"]
        else:
            with pytest.raises(HTTPException) as error:
                await dnb.bounded_drive(body, None)
            assert error.value.status_code == 409 and error.value.detail["retryable"] == retryable
        original.assert_not_awaited()

    asyncio.run(check())


def test_cancelled_hung_context_creation_is_bounded(monkeypatch):
    from unittest.mock import AsyncMock

    from context_pool import ContextPool

    class RestartRequested(BaseException):
        pass

    async def check():
        pending = []
        started = asyncio.Event()

        async def create():
            pending.append(asyncio.current_task())
            started.set()
            await asyncio.sleep(120)

        def restart(code):
            assert code == 70
            raise RestartRequested()

        monkeypatch.setattr(lifecycle, "CLEANUP_SECONDS", 0.02)
        monkeypatch.setattr(lifecycle.os, "_exit", restart)
        pool = ContextPool(create, AsyncMock())

        async def caller():
            async with pool.lease("owned"):
                pass

        task = asyncio.create_task(caller())
        await started.wait()
        task.cancel()
        try:
            with pytest.raises(RestartRequested):
                await task
        finally:
            for child in pending:
                child.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        assert not pool.entries

    asyncio.run(check())
