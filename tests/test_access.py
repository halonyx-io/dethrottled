import asyncio
import hashlib
import json
import os
import time

import pytest

from dethrottled.access import AccessError, AccessMiddleware, Admission, Registry


def test_registry_reloads_and_revokes_without_restarting(tmp_path):
    path = tmp_path / "tokens.json"
    digest = hashlib.sha256(b"test-token").hexdigest()
    data = {"tokens": [{"sha256": digest, "label": "caller", "scopes": ["web"]}]}
    path.write_text(json.dumps(data))
    registry = Registry(path)
    assert registry.verify("Bearer test-token")["scopes"] == ["web"]
    data["tokens"][0]["revoked"] = True
    replacement = tmp_path / "replacement"
    replacement.write_text(json.dumps(data))
    os.replace(replacement, path)
    with pytest.raises(AccessError, match="invalid_bearer_token"):
        registry.verify("Bearer test-token")


def test_invalid_registry_fails_closed_even_after_a_good_read(tmp_path):
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps({"tokens": [{"sha256": hashlib.sha256(b"t").hexdigest(),
                                          "scopes": ["web"]}]}))
    registry = Registry(path)
    registry.verify("Bearer t")
    path.write_text("broken JSON")
    with pytest.raises(AccessError, match="credentials_unavailable"):
        registry.verify("Bearer t")


def test_two_adapters_share_global_and_per_caller_admission(tmp_path):
    path = tmp_path / "admission.sqlite"
    rest = Admission(path, per_client=1, global_limit=2)
    mcp = Admission(path, per_client=1, global_limit=2)
    one = rest.acquire("alice")
    with pytest.raises(AccessError, match="caller_busy"):
        mcp.acquire("alice")
    two = mcp.acquire("bob")
    with pytest.raises(AccessError, match="service_busy"):
        rest.acquire("carol")
    rest.release(one)
    three = rest.acquire("carol")
    mcp.release(two)
    rest.release(three)


def test_rate_limit_is_counted_even_when_requests_finish(tmp_path):
    gate = Admission(tmp_path / "admission.sqlite", per_minute=2)
    for _ in range(2):
        gate.release(gate.acquire("alice"))
    with pytest.raises(AccessError, match="rate_limited"):
        gate.acquire("alice")
    gate.release(gate.acquire("bob"))


def test_expired_crash_leases_are_reclaimed(tmp_path):
    gate = Admission(tmp_path / "admission.sqlite", per_client=1)
    lease = gate.acquire("alice")
    with gate.connection() as db:
        db.execute("UPDATE leases SET expires=0 WHERE id=?", (lease,))
    gate.release(gate.acquire("alice"))


def test_slow_admission_does_not_block_other_requests():
    class FakeRegistry:
        def verify(self, _):
            return {"namespace": "test", "scopes": ["web"]}

    class SlowGate:
        def acquire(self, _):
            time.sleep(.25)
            return "lease"

        def release(self, _):
            pass

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def run():
        middleware = AccessMiddleware(app, registry=FakeRegistry(), admission=SlowGate())
        async def noop(*_):
            pass
        started = time.monotonic()
        request = asyncio.create_task(middleware(
            {"type": "http", "path": "/search", "headers": []}, noop, noop))
        await asyncio.sleep(.02)
        # Synchronous admission in the event loop would delay this heartbeat by .25s.
        assert time.monotonic() - started < .15
        await request
    asyncio.run(run())


def test_cancelled_admission_releases_lease_created_by_worker_thread():
    released = []
    class FakeRegistry:
        def verify(self, _):
            return {"namespace": "test", "scopes": ["web"]}

    class SlowGate:
        def acquire(self, _):
            time.sleep(.1)
            return "abandoned-lease"

        def release(self, lease):
            released.append(lease)

    async def run():
        async def noop(*_):
            pass
        middleware = AccessMiddleware(noop, registry=FakeRegistry(), admission=SlowGate())
        request = asyncio.create_task(middleware(
            {"type": "http", "path": "/search", "headers": []}, noop, noop))
        await asyncio.sleep(.02)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        assert released == ["abandoned-lease"]
    asyncio.run(run())
