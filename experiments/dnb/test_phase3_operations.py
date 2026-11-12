"""Durable drive operation journal tests. No browser or network."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from operation_store import (
    OperationConflict,
    OperationState,
    OperationStore,
)
from session_owners import StoreUnavailable


def test_begin_records_running_and_rejects_conflict(tmp_path):
    store = OperationStore(tmp_path / "ops.sqlite")
    assert store.begin("alice", "s1", "op", ["fp-a"]) is None
    existing = store.begin("alice", "s1", "op", ["fp-a"])
    assert existing.state == OperationState.RUNNING
    with pytest.raises(OperationConflict):
        store.begin("alice", "s1", "op", ["fp-b"])
    store.close()


def test_completed_replays_after_reopen(tmp_path):
    path = tmp_path / "ops.sqlite"
    store = OperationStore(path)
    store.begin("alice", "s1", "op", ["fp-a"])
    store.complete("alice", "s1", "op", {"ok": True, "step": 1})
    store.close()
    reopened = OperationStore(path)
    existing = reopened.begin("alice", "s1", "op", ["fp-a"])
    assert existing.state == OperationState.COMPLETED
    assert existing.result == '{"ok": true, "step": 1}'
    reopened.close()


def test_unknown_is_not_replayable(tmp_path):
    store = OperationStore(tmp_path / "ops.sqlite")
    store.begin("alice", "s1", "op", ["fp-a"])
    store.mark_unknown("alice", "s1", "op")
    existing = store.begin("alice", "s1", "op", ["fp-a"])
    assert existing.state == OperationState.UNKNOWN
    assert existing.result is None
    store.close()


def test_owner_and_session_are_separate(tmp_path):
    store = OperationStore(tmp_path / "ops.sqlite")
    store.begin("alice", "s1", "op", ["fp-a"])
    assert store.begin("bob", "s1", "op", ["fp-a"]) is None
    assert store.begin("alice", "s2", "op", ["fp-a"]) is None
    store.complete("alice", "s1", "op", {"ok": True})
    assert store.begin("bob", "s1", "op", ["fp-a"]).state == OperationState.RUNNING
    store.close()


def test_release_session_removes_operations(tmp_path):
    store = OperationStore(tmp_path / "ops.sqlite")
    store.begin("alice", "s1", "op", ["fp-a"])
    store.release_session("alice", "s1")
    assert store.count() == 0
    store.close()


def test_storage_failure_fails_closed(tmp_path):
    directory = tmp_path / "not-a-db"
    directory.mkdir()
    with pytest.raises(StoreUnavailable):
        OperationStore(directory)


def test_capacity_preserves_unexpired_operations(tmp_path):
    store = OperationStore(tmp_path / "ops.sqlite", max_rows=2)
    try:
        store.begin("alice", "s1", "running", ["fp-a"])
        store.begin("alice", "s1", "unknown", ["fp-b"])
        store.mark_unknown("alice", "s1", "unknown")
        with pytest.raises(StoreUnavailable):
            store.begin("alice", "s1", "new", ["fp-c"])
        assert store.begin("alice", "s1", "running", ["fp-a"]).state == OperationState.RUNNING
        assert store.begin("alice", "s1", "unknown", ["fp-b"]).state == OperationState.UNKNOWN
        assert store.count() == 2
    finally:
        store.close()


def test_restart_marks_pending_operation_unknown(tmp_path):
    path = tmp_path / "ops.sqlite"
    store = OperationStore(path)
    store.begin("alice", "s1", "op", ["fp"])
    store.close()
    reopened = OperationStore(path)
    try:
        assert reopened.begin("alice", "s1", "op", ["fp"]).state == OperationState.UNKNOWN
    finally:
        reopened.close()


def test_large_result_retains_completion_without_evidence(tmp_path):
    store = OperationStore(tmp_path / "ops.sqlite")
    try:
        store.begin("alice", "s1", "op", ["fp"])
        store.complete("alice", "s1", "op", {"evidence": "a" * 1_000_000})
        existing = store.begin("alice", "s1", "op", ["fp"])
        assert existing.state == OperationState.COMPLETED
        assert existing.result is None
    finally:
        store.close()
