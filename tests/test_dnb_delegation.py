"""Worker delegation grants scoped authority, not arbitrary owner headers."""

import json
import os
from concurrent.futures import wait

import jwt
import pytest
from fastapi.testclient import TestClient

from dethrottled.access import CLAIMS
from dethrottled.concurrency import ContextExecutor
from dethrottled.delegation import body_digest, ensure_keys, sign, verify


@pytest.fixture
def keys(tmp_path, monkeypatch):
    monkeypatch.setenv("DETHROTTLED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DETHROTTLED_DNB_PUBLIC_KEY", str(tmp_path / "trust" / "public.pem"))
    return ensure_keys(), tmp_path / "trust" / "public.pem"


def test_request_bound_claims_and_public_only_worker_key(keys):
    (key, kid), public = keys
    body = {"urls": ["https://example.org"]}
    token = sign(body, owner="alice", session="session", scope="public-read")
    assert verify(token, body, public)["sub"] == "alice"
    assert "PRIVATE" not in public.read_text()
    with pytest.raises(ValueError):
        verify(token, {"urls": ["http://127.0.0.1"]}, public)
    with pytest.raises(jwt.InvalidSignatureError):
        verify(token[:-4] + "AAAA", body, public)
    with pytest.raises(ValueError):
        verify(token, body, public, path="/drive")


@pytest.mark.parametrize(
    "changes",
    [{"exp": 1}, {"aud": "other"}, {"iss": "other"}, {"public_only": "false"}, {"exp": 9999999999}],
)
def test_expired_wrong_audience_and_invalid_policy_rejected(keys, changes):
    (key, kid), public = keys
    body = {"urls": ["https://example.org"]}
    token = sign(body, owner="alice", session="session")
    claims = jwt.decode(token, options={"verify_signature": False})
    claims.update(changes)
    forged = jwt.encode(claims, key, algorithm="EdDSA")
    with pytest.raises((ValueError, jwt.InvalidTokenError)):
        verify(forged, body, public)


def test_rotation_rejects_previous_issuer(keys, monkeypatch, tmp_path):
    (_, kid), public = keys
    body = {"urls": ["https://example.org"]}
    old = sign(body, owner="alice", session="session")
    monkeypatch.setenv("DETHROTTLED_DNB_PRIVATE_KEY", str(tmp_path / "rotated.pem"))
    ensure_keys()
    with pytest.raises(jwt.InvalidSignatureError):
        verify(old, body, public)


def test_identity_propagates_and_does_not_leak_between_pool_tasks():
    def task():
        return CLAIMS.get()

    with ContextExecutor(max_workers=2) as pool:
        token = CLAIMS.set({"namespace": "alice"})
        first = pool.submit(task)
        CLAIMS.reset(token)
        token = CLAIMS.set({"namespace": "bob"})
        second = pool.submit(task)
        CLAIMS.reset(token)
        empty = pool.submit(task)
        assert first.result()["namespace"] == "alice"
        assert second.result()["namespace"] == "bob"
        assert empty.result() is None


def _registry(tmp_path, token="caller-token"):
    import hashlib

    path = tmp_path / "tokens.json"
    path.write_text(json.dumps({"tokens": [{
        "sha256": hashlib.sha256(token.encode()).hexdigest(),
        "label": "caller",
        "scopes": ["web", "drive"],
    }]}))
    return path


def _caller_request(tmp_path, monkeypatch, *, client=("127.0.0.1", 1234),
                    forwarded=True, cidrs=None):
    from dethrottled.delegation import CallerIdentityMiddleware

    monkeypatch.setenv("DETHROTTLED_DNB", "1")
    monkeypatch.setenv("DETHROTTLED_CALLER_REGISTRY", str(_registry(tmp_path)))
    if cidrs is None:
        monkeypatch.delenv("DETHROTTLED_ADAPTER_CIDRS", raising=False)
    else:
        monkeypatch.setenv("DETHROTTLED_ADAPTER_CIDRS", cidrs)
    seen = []

    async def inner(scope, receive, send):
        seen.append(CLAIMS.get())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = CallerIdentityMiddleware(inner)
    headers = []
    if forwarded:
        headers.append((b"x-dethrottled-caller-authorization", b"Bearer caller-token"))
    scope = {"type": "http", "method": "POST", "path": "/crawl",
             "headers": headers, "client": client}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    import asyncio
    asyncio.run(middleware(scope, receive, send))
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    parsed = json.loads(body) if body.startswith(b"{") else body.decode()
    return sent[0]["status"], parsed, seen


def test_forwarded_identity_rejected_from_untrusted_peer(tmp_path, monkeypatch):
    status, body, seen = _caller_request(
        tmp_path, monkeypatch, client=("203.0.113.9", 5555))
    assert status == 403
    assert body["error"] == "untrusted_identity_source"
    assert seen == []


def test_forwarded_identity_accepted_from_loopback(tmp_path, monkeypatch):
    status, _, seen = _caller_request(tmp_path, monkeypatch)
    assert status == 200
    assert seen[0]["label"] == "caller"
    assert seen[0]["scopes"] == ["web", "drive"]


def test_forwarded_identity_cidr_override(tmp_path, monkeypatch):
    status, _, seen = _caller_request(
        tmp_path, monkeypatch, client=("203.0.113.9", 5555),
        cidrs="203.0.113.0/24")
    assert status == 200
    assert seen[0]["namespace"]


def test_absent_identity_header_stays_anonymous(tmp_path, monkeypatch):
    status, _, seen = _caller_request(tmp_path, monkeypatch, forwarded=False)
    assert status == 200
    assert seen == [None]


def test_new_issuer_token_is_accepted_after_rotation(keys, monkeypatch, tmp_path):
    (_, _), public = keys
    body = {"urls": ["https://example.org"]}
    old = sign(body, owner="alice", session="session")
    monkeypatch.setenv("DETHROTTLED_DNB_PRIVATE_KEY", str(tmp_path / "rotated.pem"))
    ensure_keys()
    with pytest.raises(jwt.InvalidSignatureError):
        verify(old, body, public)
    rotated = sign(body, owner="alice", session="session")
    assert verify(rotated, body, public)["sub"] == "alice"


