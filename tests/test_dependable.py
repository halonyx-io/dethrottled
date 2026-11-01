"""Coverage accounting and optional acquisition must remain honest on failure."""
import json

import pytest
from fastapi.testclient import TestClient

from dethrottled import formats, layout, providers, research, search, server


@pytest.mark.parametrize("name", providers.NAMES)
def test_provider_never_sends_without_explicit_key(name, monkeypatch):
    monkeypatch.delenv("DETHROTTLED_" + name.upper() + "_API_KEY", raising=False)
    monkeypatch.setattr(providers.requests, "post", lambda *a, **k: pytest.fail("network"))
    diagnostics = {}
    assert providers.search(name, "question", 3, diagnostics) == []
    assert diagnostics["status"] == "not_configured"


@pytest.mark.parametrize("name", providers.NAMES)
def test_provider_contract_and_provenance(name, monkeypatch):
    monkeypatch.setenv("DETHROTTLED_" + name.upper() + "_API_KEY", "test-secret")
    sent = {}
    class Response:
        status_code = 200
        is_redirect = False
        def raise_for_status(self):
            pass
        def json(self):
            return {"results": [{"url": "https://example.org/report", "title": "Report",
                                  "content": "17 tonnes", "excerpts": ["17 tonnes"]}]}
    def post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return Response()
    monkeypatch.setattr(providers.requests, "post", post)
    diagnostics = {}
    rows = providers.search(name, "allocation", 3, diagnostics)
    assert "17 tonnes" in rows[0]["snippet"]
    assert rows[0]["discovery"] == [{"provider": name, "query": "allocation"}]
    assert not sent["allow_redirects"]
    assert "test-secret" not in json.dumps([rows, diagnostics])
    assert diagnostics["status"] == "ok" and diagnostics["cost"] == "unknown"
    if name == "parallel":
        assert "max_results" not in sent["json"]


def test_paid_failure_preserves_free_results_and_distinct_matching_titles(monkeypatch):
    title = "A long independent report about regional allocation"
    rows = [{"url": f"https://{host}/report", "title": title, "snippet": "allocation",
             "engine": "web-ddg"} for host in ["one.org", "two.org"]]
    monkeypatch.setattr(search, "web_search", lambda *a, **kw: rows)
    def failed(name, query, limit, diagnostics):
        diagnostics.update(status="failed", http_status=429)
        return []
    monkeypatch.setattr(providers, "search", failed)
    result, meta = search.search("allocation", engines="web,exa", max_items=4)
    assert len(result) == 2
    assert next(a for a in server._attempts(meta) if a["engine"] == "exa")["status"] == "failed"
    assert all(r["discovery"][0]["provider"] == "web" for r in result)


def test_duplicate_urls_merge_discovery_provenance(monkeypatch):
    row = {"url": "https://example.org/report", "title": "Allocation", "snippet": "allocation"}
    monkeypatch.setattr(search, "web_search", lambda *a, **kw: [row])
    monkeypatch.setattr(providers, "search", lambda *a: [dict(row, discovery=[
        {"provider": "exa", "query": "allocation"}])])
    result, _ = search.search("allocation", engines="web,exa")
    assert len(result) == 1 and len(result[0]["discovery"]) == 2


def test_coverage_distinguishes_all_retrieval_states_without_verifying_answers():
    queries = ["solar capacity", "wind", "hydro", "missing"]
    searches = [[{"url": "https://a.org"}], [{"url": "https://b.org"}],
                [{"url": "https://c.org"}], []]
    ledger = research.coverage_ledger(queries, searches,
        [{"url": "https://a.org", "id": "S1", "content": "solar deployment"}],
        [{"url": "https://b.org", "reason": "timeout"}])
    assert [f["state"] for f in ledger["facets"]] == [
        "evidence_available", "read_failed", "unread", "no_candidates"]
    assert ledger["facets"][0]["evidence"][0]["missing_terms"] == ["capacity"]
    assert all(not f["answer_verified"] for f in ledger["facets"])
    assert ledger["facets"][2]["next_actions"][0]["arguments"]["urls"] == ["https://c.org"]


def test_research_rejects_mistyped_engine_before_search():
    result = TestClient(server.app).post("/research", json={
        "question": "allocation figures", "engines": "tavilly"})
    assert result.status_code == 422


@pytest.fixture
def pdf_bytes():
    pdf = pytest.importorskip("pymupdf")
    doc = pdf.open()
    page = doc.new_page()
    page.insert_text((60, 60), "ALPHA allocation is 7341 tonnes.")
    data = doc.tobytes()
    doc.close()
    return data


def test_layout_missing_worker_keeps_native_text(pdf_bytes, monkeypatch):
    monkeypatch.delenv("DETHROTTLED_LAYOUT_WORKER_URL", raising=False)
    text, meta = formats.read_blob(pdf_bytes, "pdf", 10000, allow_ocr=False,
                                   options={"document_mode": "layout"})
    assert "7341" in text
    assert "layout_worker_not_configured; native_parser_used" in meta["warnings"]


def test_layout_rejects_success_that_drops_most_text(pdf_bytes, monkeypatch):
    monkeypatch.setenv("DETHROTTLED_LAYOUT_WORKER_URL", "http://layout:19891")
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"text": "x", "status": "success"}
    monkeypatch.setattr(layout.requests, "post", lambda *a, **kw: Response())
    text, meta = formats.read_blob(pdf_bytes, "pdf", 10000, allow_ocr=False,
                                   options={"document_mode": "layout"})
    assert "7341" in text and "parser" not in meta
    assert any("native_parser_used" in w for w in meta["warnings"])


def test_explicit_native_never_contacts_layout_worker(pdf_bytes, monkeypatch):
    monkeypatch.setenv("DETHROTTLED_LAYOUT_WORKER_URL", "http://layout:19891")
    monkeypatch.setattr(layout.requests, "post", lambda *a, **k: pytest.fail("network"))
    text, _ = formats.read_blob(pdf_bytes, "pdf", 10000, allow_ocr=False,
                                options={"document_mode": "native"})
    assert "7341" in text


def test_research_redirect_is_not_counted_as_unread():
    ledger = research.coverage_ledger(['allocation'], [[{'url': 'https://a.org/old'}]],
        [{'url': 'https://a.org/new', 'requested_url': 'https://a.org/old',
          'id': 'S1', 'content': 'allocation 7341'}], [])
    assert ledger['facets'][0]['evidence'][0]['source_id'] == 'S1'
    assert ledger['facets'][0]['unread'] == []
