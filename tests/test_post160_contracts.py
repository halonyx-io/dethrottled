"""Agent-reported discovery/crawl/jobs scenarios, without production traffic."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from dethrottled import server
from dethrottled.jobs import Jobs
from dethrottled.site import crawl


def test_capability_fields_follow_actual_route_models():
    data = TestClient(server.app).get("/v2/capabilities").json()["request_contracts"]
    routes = {(r["method"], r["path"]): r for r in data["routes"]}
    for path, required in [
        ("/fetch", "urls"),
        ("/research", "question"),
        ("/documents/read", "document_id"),
        ("/jobs/read", "job_id"),
        ("/site/crawl", "urls"),
        ("/search", "query"),
    ]:
        assert required in routes["POST", path]["required_body_fields"]
    assert "limit" in routes["POST", "/search"]["body_fields"]
    assert "maxResults" not in routes["POST", "/search"]["body_fields"]
    assert {"name": "q", "required": True} in routes["GET", "/corpus/search"]["query_parameters"]


def test_crawl_follows_thin_navigation_without_claiming_it_is_good_evidence():
    def read(url):
        if url.endswith("/index"):
            return {
                "quality": "thin",
                "html": '<a href="/report">Read report</a>',
                "warnings": ["short index, coverage unverified"],
            }
        return {"quality": "ok", "content": "A useful report"}

    result = crawl(["https://example.org/index"], read)
    assert result["operation"] == "site_crawl"
    assert result["outcome"] == "partial"
    assert result["coverage"]["attempted"] == 2 and result["coverage"]["succeeded"] == 1
    assert result["sources"][0]["quality"] == "thin"
    assert result["sources"][0]["warnings"]


def test_crawl_exposes_all_failed_and_empty_frontiers_explicitly():
    result = crawl(
        ["https://example.org/"],
        lambda _: {
            "quality": "failed",
            "policy_blocked": "adblock",
            "failure_reason": "adblock_blocked",
        },
    )
    assert result["outcome"] == "no_ok_pages"
    assert result["coverage"]["attempted"] == 1 and result["coverage"]["failed"] == 1
    assert result["sources"][0]["policy_blocked"] == "adblock"


def test_crawl_api_is_crawl_not_research(monkeypatch):
    monkeypatch.setattr(
        server,
        "_extract_row",
        lambda *a, **k: {"quality": "failed", "failure_reason": "fixture_network_unavailable"},
    )
    result = (
        TestClient(server.app)
        .post(
            "/site/crawl",
            json={"urls": ["https://example.org/"], "max_pages": 3, "render": "never"},
        )
        .json()
    )
    assert result["operation"] == "site_crawl" and result["outcome"] == "no_ok_pages"
    assert result["coverage"]["attempted"] == 1 and len(result["sources"]) == 1
    assert "question" not in result and "queries" not in result


def test_two_url_job_completes_and_keeps_partial_progress_and_failures(tmp_path):
    store = Jobs(tmp_path / "jobs.sqlite")
    slow = threading.Event()

    def read(url):
        if url.endswith("/slow"):
            assert slow.wait(3)
            return {"url": url, "quality": "failed", "failure_reason": "controlled_failure"}
        return {"url": url, "quality": "ok", "content": "fact 47"}

    with ThreadPoolExecutor(max_workers=2) as workers:
        try:
            job = store.submit(
                "test",
                {"urls": ["https://example.org/fast", "https://example.org/slow"]},
                "",
                read,
                workers,
            )
            deadline = time.monotonic() + 3
            while store.get("test", job)["completed"] < 1 and time.monotonic() < deadline:
                time.sleep(0.01)
            partial = store.get("test", job)
            assert partial["status"] == "running" and partial["completed"] == 1
            assert partial["total"] == 2 and partial["poll_after_ms"] == 1000
            slow.set()
            while store.get("test", job)["status"] == "running" and time.monotonic() < deadline:
                time.sleep(0.01)
            complete = store.get("test", job)
            assert complete["status"] == "completed" and complete["completed"] == 2
            assert {r["quality"] for r in complete["results"]} == {"ok", "failed"}
        finally:
            slow.set()
            store.pool.shutdown(wait=True)
