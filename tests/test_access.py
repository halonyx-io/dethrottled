import hashlib
import json
import os

import pytest

from dethrottled.access import AccessError, Admission, Registry


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
