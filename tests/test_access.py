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


def test_stateless_mcp_stream_does_not_reserve_admission():
    from starlette.testclient import TestClient

    class FakeRegistry:
        def verify(self, authorization):
            if authorization != "Bearer test-token":
                raise AccessError("invalid_bearer_token")
            return {"namespace": "test", "scopes": ["web"]}

    class NoAdmission:
        def acquire(self, _):
            pytest.fail("idle stream reserved a tool slot")

    async def forbidden(*_):
        pytest.fail("idle stream reached the SDK")

    client = TestClient(AccessMiddleware(
        forbidden, registry=FakeRegistry(), admission=NoAdmission(), mcp=True
    ))
    assert client.get("/mcp").status_code == 401
    assert client.get("/mcp", headers=[(b"authorization", b"Bearer \xff")]).status_code == 401
    response = client.get("/mcp", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 405
    assert response.headers["allow"] == "POST"


@pytest.mark.parametrize('identifier', [0, 17, 'call-17', ''])
def test_mcp_admission_errors_correlate_request_and_preserve_retry_metadata(identifier):
    from starlette.testclient import TestClient
    class FakeRegistry:
        def verify(self, _):
            return {'namespace': 'test', 'scopes': ['web']}
    class Busy:
        def acquire(self, _):
            raise AccessError('caller_busy', 429, retry_after=2)
    async def forbidden(*_):
        pytest.fail('busy request reached backend')
    app = AccessMiddleware(forbidden, registry=FakeRegistry(), admission=Busy(), mcp=True)
    response = TestClient(app).post('/mcp', json={
        'jsonrpc': '2.0', 'id': identifier, 'method': 'tools/call', 'params': {}})
    data = response.json()
    assert response.status_code == 429 and response.headers['retry-after'] == '2'
    assert data['jsonrpc'] == '2.0' and data['id'] == identifier
    assert data['error']['code'] == -32000
    assert data['error']['data']['limiter'] == 'caller_concurrency'
    assert data['error']['data']['request_id'] == response.headers['x-request-id']
    assert data['error']['data']['retryable']


def test_rest_admission_contract_and_accepted_mcp_body_are_unchanged():
    from starlette.testclient import TestClient
    class FakeRegistry:
        def verify(self, _):
            return {'namespace': 'test', 'scopes': ['web']}
    class Gate:
        def acquire(self, _):
            raise AccessError('caller_busy', 429)
        def release(self, _):
            pass
    async def echo(scope, receive, send):
        message = await receive()
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': message['body']})
    gate = Gate()
    response = TestClient(AccessMiddleware(echo, registry=FakeRegistry(), admission=gate)).post(
        '/fetch', json={'urls': ['https://example.org']})
    assert response.json()['error'] == 'caller_busy' and 'jsonrpc' not in response.json()
    gate.acquire = lambda _: 'lease'
    request = {'jsonrpc': '2.0', 'id': 11, 'method': 'tools/list'}
    response = TestClient(AccessMiddleware(
        echo, registry=FakeRegistry(), admission=gate, mcp=True)).post('/mcp', json=request)
    assert response.json() == request


@pytest.mark.parametrize('payload', [
    {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
    {'jsonrpc': '2.0', 'id': True, 'method': 'tools/list'},
    ['unsupported batch'], 'invalid',
])
def test_busy_mcp_does_not_invent_request_ids(payload):
    from starlette.testclient import TestClient
    class FakeRegistry:
        def verify(self, _):
            return {'namespace': 'test', 'scopes': ['web']}
    class Busy:
        def acquire(self, _):
            raise AccessError('service_busy', 429)
    async def forbidden(*_):
        pytest.fail('busy request reached backend')
    response = TestClient(AccessMiddleware(
        forbidden, registry=FakeRegistry(), admission=Busy(), mcp=True)).post('/mcp', json=payload)
    assert response.status_code == 429 and 'id' not in response.json()
    assert response.json()['error']['data']['reason'] == 'service_busy'


def test_rejected_mcp_body_read_is_bounded_and_preserves_transport_error():
    class FakeRegistry:
        def verify(self, _):
            return {'namespace': 'test', 'scopes': ['web']}
    class Busy:
        def acquire(self, _):
            raise AccessError('service_busy', 503, retry_after=3)
    async def forbidden(*_):
        pytest.fail('busy request reached backend')
    async def run(receive):
        sent = []
        async def send(message):
            sent.append(message)
        app = AccessMiddleware(forbidden, registry=FakeRegistry(), admission=Busy(), mcp=True)
        await asyncio.wait_for(app({'type': 'http', 'path': '/mcp', 'method': 'POST',
                                   'headers': []}, receive, send), 3)
        assert sent[0]['status'] == 503
        payload = json.loads(sent[1]['body'])
        assert 'id' not in payload
        assert payload['error']['data']['limiter'] == 'global_concurrency'
        assert payload['error']['data']['retry_after_seconds'] == 3
    async def oversized():
        return {'type': 'http.request', 'body': b' ' * 262145, 'more_body': True}
    async def stalled():
        await asyncio.sleep(10)
    asyncio.run(run(oversized))
    asyncio.run(run(stalled))
