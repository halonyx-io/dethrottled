import json
import subprocess
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from dethrottled import dpr_cli
from dethrottled import server as srv
from dethrottled.jobs import JobError, Jobs

ROOT = "/v1/dpr/jobs"


def terminal(store, identifier, state="completed"):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        page = store.get("local", identifier, limit=500)
        if page["status"] == state:
            return page
        time.sleep(0.01)
    pytest.fail(f"job did not become {state}: {page['status']}")


def test_500_items_survive_process_exit_and_keep_committed_rows(tmp_path):
    path = tmp_path / "bulk.sqlite"
    child = """
import os,sys,threading
from concurrent.futures import ThreadPoolExecutor
from dethrottled.jobs import Jobs
store = Jobs(sys.argv[1], bulk=True)
workers = ThreadPoolExecutor(max_workers=2)
urls = [f'https://example.org/{i // 2}' for i in range(500)]
def read(url):
    if url.endswith('/5'):
        os._exit(17)
    return {'requested_url':url, 'outcome':'usable'}
store.submit('local', {'urls':urls}, 'crash', read, workers)
threading.Event().wait(10)
"""
    result = subprocess.run([sys.executable, "-c", child, str(path)], timeout=15)
    assert result.returncode == 17
    store = Jobs(path, bulk=True)
    job_id = store.db.execute("SELECT id FROM jobs").fetchone()[0]
    assert terminal(store, job_id, "interrupted")["completed"] == 10
    seen = Counter()

    def read(url):
        seen[url] += 1
        return {"requested_url": url, "outcome": "usable"}

    with ThreadPoolExecutor(max_workers=2) as workers:
        store.resume("local", job_id, lambda _: read, workers)
        result = terminal(store, job_id)
    assert result["completed"] == 500
    assert {r["source_index"] for r in result["results"]} == set(range(500))
    assert len(seen) == 245 and max(seen.values()) == 1
    assert not any(f"https://example.org/{i}" in seen for i in range(5))


def test_bulk_cancel_drains_before_resume(tmp_path):
    store = Jobs(tmp_path / "jobs.sqlite", bulk=True)
    entered = threading.Event()
    release = threading.Event()

    def slow(url):
        entered.set()
        assert release.wait(5)
        return {"requested_url": url}

    with ThreadPoolExecutor(max_workers=2) as workers:
        identifier = store.submit("local", {"urls": ["a", "b"]}, "job", slow, workers)
        try:
            assert entered.wait(5)
            assert store.cancel("local", identifier)["status"] == "cancelled"
            with pytest.raises(JobError, match="job_draining"):
                store.resume("local", identifier, lambda _: slow, workers)
        finally:
            release.set()
        deadline = time.monotonic() + 5
        while store.executions and time.monotonic() < deadline:
            time.sleep(0.01)
        store.resume("local", identifier, lambda _: slow, workers)
        assert terminal(store, identifier)["completed"] == 2


def test_api_scopes_dedup_retries_and_exports(tmp_path, monkeypatch):
    store = Jobs(tmp_path / "dpr.sqlite", bulk=True)
    monkeypatch.setattr(srv, "_dpr_jobs", store)
    hits = Counter()

    def fetch(url, max_chars, **options):
        assert options["public_only"]
        hits[url] += 1
        if url.endswith("/bad") and hits[url] == 1:
            return {"quality": "failed", "acquisition_attempts": [
                {"http_status": 503, "final_url": url, "outcome": "failed"}]}
        return {"content": "proof", "_index_text": "proof", "quality": "ok",
                "final_url": url + "/final", "cached": True, "retrieved_at": "2026-01-01T00:00:00Z",
                "origin_response": {
                    "status": 200, "last_modified": "Wed, 01 Jan 2025 00:00:00 GMT"}}

    monkeypatch.setattr(srv, "_extract_row", fetch)
    monkeypatch.setattr(srv, "_queue_corpus", lambda *a, **k: pytest.fail("unexpected indexing"))
    client = TestClient(srv.app)
    payload = {"urls": ["https://example.org/a", "https://example.org/a",
                        "https://example.org/bad"],
               "item_keys": ["a1", "a2", "bad"], "operation_id": "original"}
    response = client.post(ROOT, json=payload)
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    terminal(store, job_id)
    assert client.post(ROOT, json=payload).json()["job_id"] == job_id
    assert client.post(ROOT + "/read", json={"job_id": job_id,
                                            "evidence_namespace": "other"}).status_code == 404

    def read(path, body):
        response = client.post(path, json=body)
        assert response.is_success, response.text
        return response.json()

    out = tmp_path / "evidence.jsonl"
    assert dpr_cli.collect(read, job_id, out, "jsonl", None) == 0
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert [r["item_key"] for r in rows] == ["a1", "a2", "bad"]
    assert rows[0]["fetched_at"] == "2026-01-01T00:00:00Z" and rows[0]["checked_at"] is None
    assert rows[0]["last_modified_source"] == "http_header"
    assert rows[0]["content_sha256"] == rows[1]["content_sha256"]
    assert rows[2]["outcome"] == "failed" and rows[2]["retryable"]
    retry = read(ROOT + "/retry", {"job_id": job_id, "operation_id": "retry"})
    terminal(store, retry["job_id"])
    assert hits == {"https://example.org/a": 1, "https://example.org/bad": 2}


def test_query_resolves_first_usable_ranked_source(monkeypatch):
    rows = [{"url": f"https://example.org/{i}", "engine": "web", "neural_score": 1 - i / 5}
            for i in range(5)]
    monkeypatch.setattr(srv, "_ranked", lambda body: (rows, {"ranking": ["neural_rerank"]}, 5))
    reads = []

    def read(_, url):
        reads.append(url)
        return {"requested_url": url, "outcome": "partial" if len(reads) == 1 else "usable"}

    monkeypatch.setattr(srv, "_dpr_read", read)
    response = TestClient(srv.app).post("/v1/dpr/resolve", json={
        "search": {"query": "fixture"}, "alternatives": 1})
    assert response.is_success
    result = response.json()
    assert result["selected"]["requested_url"] == rows[1]["url"]
    assert result["selected"]["search_candidate"]["neural_score"] == rows[1]["neural_score"]
    assert result["ranking"] == ["neural_rerank"]
    assert reads == [rows[0]["url"], rows[1]["url"]]
    assert [row["url"] for row in result["alternatives"]] == [rows[0]["url"]]


def test_verified_identity_overrides_body_namespace():
    from dethrottled.access import CLAIMS
    from dethrottled.dpr import BatchBody, BatchReadBody

    token = CLAIMS.set({"namespace": "verified", "scopes": ["web"]})
    try:
        assert BatchBody(urls=["https://example.org"],
                         evidence_namespace="forged").evidence_namespace == "verified"
        assert BatchReadBody(job_id="job",
                             evidence_namespace="forged").evidence_namespace == "verified"
        with pytest.raises(JobError, match="insufficient_corpus_scope"):
            srv._dpr_index_scope(True)
    finally:
        CLAIMS.reset(token)


def test_csv_archive_links_and_escapes_untrusted_cells(tmp_path):
    def read(path, payload):
        if path == "/documents/read":
            assert payload["document_id"] == "doc"
            return {"content": "first " if payload["offset"] == 0 else "last",
                    "next_offset": 6 if payload["offset"] == 0 else None}
        return {"schema_version": 1, "results": [
            {"source_index": 0, "item_key": "=unsafe", "outcome": "usable",
             "document_id": "doc"}], "status": "completed", "completed": 1, "next_cursor": 1}

    output = tmp_path / "report.csv"
    archive = tmp_path / "archive"
    assert dpr_cli.collect(read, "job", output, "csv", archive) == 0
    assert (archive / "0000.txt").read_text() == "first last"
    assert "'=unsafe" in output.read_text()
    assert "archive/0000.txt" in output.read_text().replace("\\", "/")
