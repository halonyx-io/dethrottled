"""Worker-side owner binding for drive sessions and checkpoints.

Pure sqlite; no Chromium, browser module or network. The DNB worker records the
first owner for a session id and rejects a different owner even when the session
id is known. Storage failures fail closed.
"""

import hashlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from session_owners import OwnerMismatch, SessionOwners, StoreUnavailable


def digest(owner):
    return hashlib.sha256(owner.encode()).hexdigest()


def test_first_owner_wins_and_same_owner_is_idempotent(tmp_path):
    owners = SessionOwners(tmp_path / "owners.sqlite")
    assert owners.claim("session-a", "alice") is True
    assert owners.claim("session-a", "alice") is False
    assert owners.owner_of("session-a") == digest("alice")
    with pytest.raises(OwnerMismatch):
        owners.claim("session-a", "bob")
    assert owners.owner_of("session-a") == digest("alice")
    owners.close()


def test_release_allows_a_new_owner_after_close(tmp_path):
    owners = SessionOwners(tmp_path / "owners.sqlite")
    owners.claim("session-a", "alice")
    owners.release("session-a")
    assert owners.claim("session-a", "bob") is True
    assert owners.count() == 1
    owners.close()


def test_binding_survives_reopen(tmp_path):
    path = tmp_path / "owners.sqlite"
    first = SessionOwners(path)
    first.claim("session-a", "alice")
    first.close()
    second = SessionOwners(path)
    assert second.owner_of("session-a") == digest("alice")
    with pytest.raises(OwnerMismatch):
        second.claim("session-a", "bob")
    second.close()


def test_concurrent_claims_have_one_winner(tmp_path):
    owners = SessionOwners(tmp_path / "owners.sqlite")

    def claim(owner):
        try:
            return owner
        finally:
            owners.claim("session-a", owner)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim, owner) for owner in ("alice", "bob")]
        results = []
        for future in futures:
            try:
                future.result()
                results.append("ok")
            except OwnerMismatch:
                results.append("mismatch")
    assert sorted(results) == ["mismatch", "ok"]
    assert owners.owner_of("session-a") in {digest("alice"), digest("bob")}
    owners.close()


def test_storage_failure_fails_closed(tmp_path):
    directory = tmp_path / "not-a-db"
    directory.mkdir()
    with pytest.raises(StoreUnavailable):
        SessionOwners(directory)


def test_owner_is_not_stored_in_clear(tmp_path):
    path = tmp_path / "owners.sqlite"
    owners = SessionOwners(path)
    owners.claim("session-a", "alice-secret-owner")
    owners.close()
    assert b"alice-secret-owner" not in path.read_bytes()
