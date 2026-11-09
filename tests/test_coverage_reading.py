"""Acceptance cases for source coverage, reliable escalation and retained evidence."""

import hashlib
import io
import json
import sys
import threading
import time
import types
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from dethrottled import fetch, formats, server
from dethrottled.cache import Cache, CacheView
from dethrottled.evidence import Documents
from dethrottled.jobs import JobError, Jobs

ARTICLE = "<html><article>" + "<p>Useful source background and accurate documentation.</p>" * 30


def test_render_escalation_rejects_an_incompatible_warm_cache(monkeypatch, tmp_path):
    store = CacheView(Cache(tmp_path / "cache.sqlite"))
    monkeypatch.setattr(fetch, "ENABLE_TLS", False)
    monkeypatch.setattr(fetch, "CRAWL4AI_URL", "http://renderer")
    monkeypatch.setattr(fetch, "_tier_direct", lambda url, *a: ({"html": ARTICLE}, "", url))
    calls = []
    monkeypatch.setattr(
        fetch,
        "_tier_crawl4ai",
        lambda url: (
            calls.append(url) or {"html": ARTICLE + "<p>READY_ANSWER_MARKER</p>"},
            "",
            url,
        ),
    )
    first = fetch.fetch_and_extract("https://example.org/read", cache=store, allow_render=False)
    assert not first["acquisition"]["rendered"]
    second = fetch.fetch_and_extract(
        "https://example.org/read", cache=store, render_first=True, wait_for="#resolved"
    )
    assert "READY_ANSWER_MARKER" in second["text"] and not second["cached"]
    third = fetch.fetch_and_extract(
        "https://example.org/read", cache=store, render_first=True, wait_for="#resolved"
    )
    assert third["cached"] and len(calls) == 1
    fetch.fetch_and_extract(
        "https://example.org/read", cache=store, render_first=True, wait_for="#another"
    )
    assert len(calls) == 2


def test_selected_pdf_page_cache_does_not_replace_an_ordinary_read(monkeypatch, tmp_path):
    store = CacheView(Cache(tmp_path / "cache.sqlite"))
    monkeypatch.setattr(fetch, "ENABLE_TLS", False)
    calls = []

    def direct(url, *args):
        page = fetch._READ_OPTIONS.get()["page_start"]
        calls.append(page)
        return {"text": f"PAGE {page}", "structured": True}, "", url

    monkeypatch.setattr(fetch, "_tier_direct", direct)
    fetch.fetch_and_extract("https://example.org/report.pdf", cache=store, page_start=2, page_end=2)
    result = fetch.fetch_and_extract("https://example.org/report.pdf", cache=store)
    assert result["text"] == "PAGE 1" and calls == [2, 1]


@pytest.mark.parametrize(
    "kind,ctype,url,data,expected",
    [
        ("text", "text/plain", "/document", b"Only one fact: 47 items.", "47 items"),
        ("text", "text/markdown", "/readme.md", "# Header\nCafé\n47".encode(), "Café"),
        ("json", "application/json", "/data", b'{"count":47,"status":"ready"}', '"count": 47'),
        ("jsonl", "application/x-ndjson", "/data", b'{"x":1}\n{"x":2}', '"x": 2'),
        (
            "xml",
            "application/xml",
            "/data",
            b'<data><item count="47">ready</item></data>',
            'count="47"',
        ),
        ("xml", "image/svg+xml", "/data", b"<svg><text>47 items</text></svg>", "47 items"),
        (
            "eml",
            "message/rfc822",
            "/message",
            b"Subject: Source evidence\nContent-Type: text/plain\n\n47 items",
            "Subject: Source evidence",
        ),
    ],
)
def test_additional_formats_preserve_data(kind, ctype, url, data, expected):
    assert formats.kind_of(data, url, ctype) == kind
    text, meta = formats.read_blob(data, kind, 20000)
    assert expected in text and not meta["partial"]


def test_xml_external_entities_are_rejected():
    data = b'<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>'
    with pytest.raises(Exception, match="EntitiesForbidden"):
        formats.read_blob(data, "xml", 1000)


def test_mislabelled_html_never_becomes_json_or_a_document():
    assert (
        formats.kind_of(b"<!doctype html><html>Error</html>", "/data.json", "application/json")
        == ""
    )


def test_zip_provenance_and_unsupported_members_are_explicit():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("source.json", '{"verified_number":47}')
        archive.writestr("notes.txt", "Source attribution remains available.")
        archive.writestr("unknown.bin", b"\x00\xff")
    text, meta = formats.read_blob(data.getvalue(), "zip", 10000)
    assert "verified_number" in text and "source.json" in text and "notes.txt" in text
    assert meta["partial"] and meta["skipped_members"] == ["unknown.bin: unsupported format"]


def test_archive_expansion_is_bounded_before_reading_members(monkeypatch):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("notes.txt", "a" * 1000)
    monkeypatch.setattr(formats, "EXPANDED_LIMIT", 100)
    with pytest.raises(ValueError, match="expanded_limit"):
        formats.read_blob(data.getvalue(), "zip", 10000)


def test_tls_routes_binary_documents_instead_of_decoding_them_as_html(monkeypatch):
    class Response:
        status_code = 200
        headers = {"Content-Type": "application/json"}  # noqa: RUF012
        url = "https://example.org/data"

        def iter_content(self, size):
            yield b'{"recovered_via_tls":47}'

        def close(self):
            pass

    fake = types.SimpleNamespace(requests=types.SimpleNamespace(get=lambda *a, **k: Response()))
    monkeypatch.setitem(sys.modules, "curl_cffi", fake)
    monkeypatch.setattr(fetch, "ENABLE_TLS", True)
    payload, why, _ = fetch._tier_tls_once("https://example.org/data")
    assert not why and payload["content_type"] == "json"
    assert "47" in payload["text"] and "html" not in payload


def test_pdf_page_selection_exposes_page_numbers_and_continuation():
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    for label in ["FIRST PAGE EVIDENCE", "SECOND PAGE EVIDENCE", "THIRD PAGE EVIDENCE"]:
        page = doc.new_page()
        page.insert_text((50, 70), label)
    text, meta = formats.read_blob(
        doc.tobytes(), "pdf", 10000, options={"page_start": 2, "page_end": 2}
    )
    assert "SECOND PAGE" in text and "FIRST PAGE" not in text and "THIRD PAGE" not in text
    assert meta["total_pages"] == 3 and meta["next_page"] == 3 and meta["partial"]
    assert meta["pages"][0]["page"] == 2


def test_mixed_pdf_ocr_does_not_lose_scan_after_a_text_page(monkeypatch):
    pymupdf = pytest.importorskip("pymupdf")
    image = pytest.importorskip("PIL.Image")
    doc = pymupdf.open()
    first = doc.new_page()
    first.insert_text((50, 70), "Native source text. " * 10)
    scanned = doc.new_page()
    data = io.BytesIO()
    image.new("RGB", (100, 100), "white").save(data, format="PNG")
    scanned.insert_image(scanned.rect, stream=data.getvalue())
    monkeypatch.setattr(
        formats,
        "image_text",
        lambda *a, **k: ("SCANNED ANSWER 47", {"warnings": ["OCR requires verification"]}),
    )
    text, meta = formats.read_blob(doc.tobytes(), "pdf", 10000)
    assert "Native source" in text and "SCANNED ANSWER 47" in text
    assert [p["method"] for p in meta["pages"]] == ["text", "ocr"]


def test_document_versions_are_scoped_and_immutable(tmp_path):
    docs = Documents(tmp_path / "evidence.sqlite")
    one = docs.put(
        "alice", "https://example.org", "Original evidence 47", {"retrieved_at": "first"}
    )
    same = docs.put("alice", "https://example.org", "Original evidence 47", {})
    newer = docs.put("alice", "https://example.org", "Changed evidence 48", {})
    assert one["document_id"] == same["document_id"] != newer["document_id"]
    assert docs.get("bob", one["document_id"]) is None
    assert docs.get("alice", one["document_id"])["text"] == "Original evidence 47"
    assert one["document_sha256"] == hashlib.sha256(b"Original evidence 47").hexdigest()


def test_document_expiry_and_size_eviction(tmp_path):
    docs = Documents(tmp_path / "evidence.sqlite", max_bytes=5)
    first = docs.put("a", "https://first", "12345", {})
    second = docs.put("a", "https://second", "67890", {})
    assert docs.get("a", first["document_id"]) is None
    assert docs.get("a", second["document_id"])
    docs.db.execute("UPDATE documents SET expires=0")
    docs.db.commit()
    assert docs.get("a", second["document_id"]) is None


def test_focused_read_reuses_full_retained_evidence_and_can_continue(monkeypatch, tmp_path):
    docs = Documents(tmp_path / "evidence.sqlite")
    monkeypatch.setattr(server, "_documents", docs)
    text = "General source introduction. " * 300 + "Required ANSWER_MARKER forty-seven. " * 20
    record = docs.put("alice", "https://example.org", text, {"quality": "ok", "warnings": []})
    client = TestClient(server.app)
    focused = client.post(
        "/documents/read",
        json={
            "document_id": record["document_id"],
            "evidence_namespace": "alice",
            "focus": "ANSWER_MARKER forty-seven",
            "max_chars": 1000,
        },
    ).json()
    assert "ANSWER_MARKER" in focused["content"] and focused["document_sha256"]
    assert (
        client.post(
            "/documents/read",
            json={"document_id": record["document_id"], "evidence_namespace": "bob"},
        ).status_code
        == 404
    )
    first = client.post(
        "/documents/read",
        json={
            "document_id": record["document_id"],
            "evidence_namespace": "alice",
            "max_chars": 100,
        },
    ).json()
    second = client.post(
        "/documents/read",
        json={
            "document_id": record["document_id"],
            "evidence_namespace": "alice",
            "max_chars": 100,
            "offset": first["next_offset"],
        },
    ).json()
    assert first["content"] + second["content"] == text[:200]


@pytest.mark.parametrize(
    "body",
    [
        {"page_start": 3, "page_end": 2},
        {"page_start": 1, "page_end": 101},
        {"render": "never", "wait_for": "#answer"},
        {"profile": "fast", "wait_for": "#answer"},
        {"format": "html", "focus": "question"},
        {"ocr_language": "../../etc/passwd"},
    ],
)
def test_conflicting_or_unsafe_read_controls_are_rejected(body):
    assert (
        TestClient(server.app)
        .post("/fetch", json={"urls": ["https://example.org"], **body})
        .status_code
        == 422
    )


def test_progressive_job_returns_fast_source_before_slow_source(tmp_path):
    jobs = Jobs(tmp_path / "jobs.sqlite")
    release = threading.Event()
    workers = ThreadPoolExecutor(max_workers=4)

    def read(url):
        if url == "slow":
            release.wait(5)
        return {"url": url, "content": "Evidence", "quality": "ok"}

    try:
        identifier = jobs.submit("alice", {"urls": ["slow", "fast"]}, "operation", read, workers)
        assert (
            jobs.submit("alice", {"urls": ["slow", "fast"]}, "operation", read, workers)
            == identifier
        )
        with pytest.raises(JobError, match="payload_conflict"):
            jobs.submit("alice", {"urls": ["changed"]}, "operation", read, workers)
        with pytest.raises(JobError, match="missing"):
            jobs.get("bob", identifier)
        until = time.monotonic() + 3
        while time.monotonic() < until:
            state = jobs.get("alice", identifier)
            if state["completed"]:
                break
            time.sleep(0.01)
        assert state["status"] == "running" and state["results"][0]["url"] == "fast"
        assert state["results"][0]["source_index"] == 1
        release.set()
        until = time.monotonic() + 3
        while time.monotonic() < until and jobs.get("alice", identifier)["status"] != "completed":
            time.sleep(0.01)
        later = jobs.get("alice", identifier, cursor=state["next_cursor"])
        assert len(later["results"]) == 1 and later["results"][0]["url"] == "slow"
    finally:
        release.set()
        jobs.pool.shutdown(wait=True)
        workers.shutdown(wait=True)


def test_job_cancellation_preserves_results_and_stops_scheduling(tmp_path):
    jobs = Jobs(tmp_path / "jobs.sqlite")
    workers = ThreadPoolExecutor(max_workers=4)
    release = threading.Event()
    calls = []

    def read(url):
        calls.append(url)
        release.wait(3)
        return {"url": url, "quality": "ok"}

    try:
        identifier = jobs.submit("a", {"urls": list(map(str, range(10)))}, "", read, workers)
        until = time.monotonic() + 2
        while not calls and time.monotonic() < until:
            time.sleep(0.01)
        assert jobs.cancel("a", identifier)["status"] == "cancelled"
        release.set()
        jobs.pool.shutdown(wait=True)
        assert len(calls) <= 4
        assert jobs.get("a", identifier)["status"] == "cancelled"
    finally:
        release.set()
        workers.shutdown(wait=True)


def test_restart_marks_unfinished_jobs_interrupted_and_retains_completed_rows(tmp_path):
    path = tmp_path / "jobs.sqlite"
    first = Jobs(path)
    first.db.execute(
        "INSERT INTO jobs (id,namespace,operation,fingerprint,status,total,created,expires) "
        "VALUES(?,?,?,?,?,?,?,?)",
        ("job_old", "alice", None, "digest", "running", 2, time.time(), time.time() + 100),
    )
    first.db.execute(
        "INSERT INTO results VALUES(?,?,?,?)",
        ("job_old", 0, 1, json.dumps({"url": "fast", "content": "retained"})),
    )
    first.db.commit()
    restarted = Jobs(path)
    state = restarted.get("alice", "job_old")
    assert state["status"] == "interrupted" and state["results"][0]["content"] == "retained"
    first.pool.shutdown()
    restarted.pool.shutdown()


def test_xlsx_does_not_silently_drop_uncached_formulas():
    openpyxl = pytest.importorskip("openpyxl")

    book = openpyxl.Workbook()
    book.active.append(["Input", "Formula"])
    book.active.append([47, "=A2*2"])
    stream = io.BytesIO()
    book.save(stream)
    text, meta = formats.read_blob(stream.getvalue(), "xlsx", 10000)
    assert "47" in text and "=A2*2" in text and "cached value unavailable" in text
    assert meta["warnings"]


def test_octet_stream_jsonl_uses_the_filename_before_json_sniffing():
    data = b'{"quantity":47}\n{"quantity":48}'
    assert formats.kind_of(data, "source.jsonl", "application/octet-stream") == "jsonl"
    text, _ = formats.read_blob(data, "jsonl", 10000)
    assert "47" in text and "48" in text


def test_download_is_parsed_and_retained_without_returning_binary_transport(monkeypatch, tmp_path):
    import base64

    monkeypatch.setattr(server, "_documents", Documents(tmp_path / "evidence.sqlite"))
    monkeypatch.setattr(
        server.fs,
        "browser_drive",
        lambda body: {
            "ok": True,
            "steps": [
                {
                    "action": "download",
                    "ok": True,
                    "data": {
                        "filename": "evidence.csv",
                        "source_url": "blob:https://example.org/uuid",
                        "download_b64": base64.b64encode(b"quantity,units\n47,items").decode(),
                    },
                }
            ],
        },
    )
    response = TestClient(server.app).post(
        "/drive",
        json={
            "url": "https://example.org",
            "steps": [{"action": "download", "selector": "button"}],
        },
    )
    assert response.status_code == 200
    data = response.json()["steps"][0]["data"]
    assert "47 | items" in data["content"] and data["document_id"]
    assert "download_b64" not in data and data["file_sha256"]


def test_research_follows_an_image_asset_and_keeps_parent_provenance(monkeypatch):
    item = {"url": "https://example.org/schedule", "title": "Official schedule"}
    monkeypatch.setattr(server, "_ranked", lambda *a: ([item], {"elapsed_ms": 1}, 1))
    monkeypatch.setattr(server.research_engine, "public_url", lambda url: True)

    def read(url, *a, **k):
        if url.endswith(".png"):
            return {
                "url": url,
                "quality": "ok",
                "content": "Verified timetable quantity 47",
                "content_status": "complete",
                "warnings": ["OCR requires verification"],
                "extraction": {"pages": [{"method": "ocr"}]},
            }
        return {
            "url": url,
            "quality": "ok",
            "content": "Timetable heading",
            "content_status": "image_content",
            "assets": [{"url": "https://example.org/timetable.png", "kind": "image"}],
        }

    monkeypatch.setattr(server, "_extract_row", read)
    response = TestClient(server.app).post(
        "/research", json={"question": "What is the timetable quantity?", "max_sources": 1}
    )
    source = response.json()["sources"][0]
    assert source["url"].endswith(".png") and source["parent_url"] == item["url"]
    assert source["warnings"] == ["OCR requires verification"]


def test_compact_evidence_offsets_reconstruct_the_original_source_text():
    from dethrottled.content import compact_row

    row = {
        "content": "Source evidence: 47 items.",
        "evidence": [{"excerpt": "47 items", "offset": 100, "offset_in": "full_extraction"}],
    }
    compact = compact_row(row)
    evidence = compact["evidence"][0]
    assert compact["content"][evidence["content_start"] : evidence["content_end"]] == "47 items"
    assert evidence["offset"] == 100 and "excerpt" not in evidence


def test_forced_pdf_ocr_preserves_native_text_and_recovers_visual_content(monkeypatch):
    pymupdf = pytest.importorskip("pymupdf")
    document = pymupdf.open()
    document.new_page().insert_text((50, 70), "Native text must remain available.")
    monkeypatch.setattr(
        formats,
        "image_text",
        lambda *a, **k: ("VISUAL CHART ANSWER 89", {"warnings": ["OCR requires verification"]}),
    )
    text, meta = formats.read_blob(document.tobytes(), "pdf", 10000, options={"ocr_mode": "always"})
    assert "Native text must remain" in text and "VISUAL CHART ANSWER 89" in text
    assert meta["pages"][0]["method"] == "text+ocr"


def test_retained_evidence_can_focus_beyond_the_previous_120k_limit(monkeypatch, tmp_path):
    docs = Documents(tmp_path / "evidence.sqlite")
    monkeypatch.setattr(server, "_documents", docs)
    text = "General source introduction. " * 10000 + "DEEP_EVIDENCE answer 47. " * 30
    handle = docs.put("local", "https://example.org/long", text, {})
    response = TestClient(server.app).post(
        "/documents/read",
        json={
            "document_id": handle["document_id"],
            "focus": "DEEP_EVIDENCE answer",
            "max_chars": 1500,
        },
    )
    assert "DEEP_EVIDENCE" in response.json()["content"]
    assert response.json()["document_chars"] > 120000


def test_table_empty_columns_and_literal_separators_are_preserved():
    data = b"name,quantity,note\n,47,\nA|B,48,R&D\n"
    text, meta = formats.read_blob(data, "csv", 10000)
    lines = text.splitlines()
    assert lines[1] == "|  | 47 |  |"
    assert "A&#124;B" in text and "R&amp;D" in text
    assert meta["tables"][0]["total_rows"] == 3


def test_csv_row_window_reaches_beyond_default_cap_and_reports_positions():
    data = ("id,quantity\n" + "\n".join(f"{n},{n * 10}" for n in range(1, 3001))).encode()
    text, meta = formats.read_blob(data, "csv", 10000, options={"row_start": 2500, "row_end": 2502})
    assert "| 2499 | 24990 |" in text and "| 2501 | 25010 |" in text
    assert "Source row 1 (context)" in text
    assert meta["partial"] and meta["tables"][0]["next_row"] == 2503
    assert meta["tables"][0]["total_rows"] == 3001


def test_xlsx_sheet_and_row_selection_keeps_correct_context():
    openpyxl = pytest.importorskip("openpyxl")

    book = openpyxl.Workbook()
    book.active.title = "Other"
    book.active.append(["wrong", 999])
    sheet = book.create_sheet("Evidence")
    sheet.append(["id", "quantity"])
    for n in range(1, 3001):
        sheet.append([n, n * 10])
    data = io.BytesIO()
    book.save(data)
    text, meta = formats.read_blob(
        data.getvalue(),
        "xlsx",
        10000,
        options={"row_start": 2500, "row_end": 2501, "sheet": "Evidence"},
    )
    assert "| 2499 | 24990 |" in text and "wrong" not in text
    assert meta["available_sheets"] == ["Other", "Evidence"] and meta["partial"]
    assert meta["tables"][0]["next_row"] == 2502


def test_long_cell_truncation_is_explicit_and_can_be_overridden():
    data = ("name,value\nsource," + "x" * 50000 + "ANSWER_AT_END\n").encode()
    limited, meta = formats.read_blob(data, "csv", 100000)
    assert "ANSWER_AT_END" not in limited and meta["partial"] and meta["truncated_cells"] == 1
    complete, meta = formats.read_blob(data, "csv", 100000, options={"max_cell_chars": 100000})
    assert "ANSWER_AT_END" in complete and not meta["partial"]


def test_downloaded_artifact_can_be_reparsed_for_later_rows_without_reexport(monkeypatch, tmp_path):
    docs = Documents(tmp_path / "evidence.sqlite")
    monkeypatch.setattr(server, "_documents", docs)
    data = ("id,quantity\n" + "\n".join(f"{n},{n * 10}" for n in range(1, 3001))).encode()
    artifact = docs.put_artifact("alice", "evidence.csv", data)
    original = docs.put(
        "alice", "blob:https://example.org/uuid", "original first range", {"artifact_id": artifact}
    )
    result = (
        TestClient(server.app)
        .post(
            "/documents/read",
            json={
                "document_id": original["document_id"],
                "evidence_namespace": "alice",
                "row_start": 2500,
                "row_end": 2501,
            },
        )
        .json()
    )
    assert "| 2499 | 24990 |" in result["content"] and result["source_partial"]
    assert result["document_id"] != original["document_id"]
    assert docs.get_artifact("bob", artifact) is None


def test_retained_pdf_pixels_keep_source_hash_and_scope(monkeypatch, tmp_path):
    import base64

    pymupdf = pytest.importorskip("pymupdf")
    document = pymupdf.open()
    document.new_page().insert_text((50, 70), "VERIFY SOURCE 47")
    blob = document.tobytes()
    docs = Documents(tmp_path / "evidence.sqlite")
    monkeypatch.setattr(server, "_documents", docs)
    artifact = docs.put_artifact("alice", "source.pdf", blob)
    record = docs.put(
        "alice", "https://example.org/file.pdf", "VERIFY SOURCE 47", {"artifact_id": artifact}
    )
    client = TestClient(server.app)
    result = client.post(
        "/documents/image",
        json={"document_id": record["document_id"], "evidence_namespace": "alice", "page": 1},
    ).json()
    assert base64.b64decode(result["image_b64"]).startswith(b"\x89PNG")
    assert result["source_sha256"] == hashlib.sha256(blob).hexdigest()
    assert (
        client.post(
            "/documents/image",
            json={"document_id": record["document_id"], "evidence_namespace": "bob"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/documents/image",
            json={
                "document_id": record["document_id"],
                "evidence_namespace": "alice",
                "crop": [-1, 0, 10, 10],
            },
        ).status_code
        == 422
    )


def test_combined_search_and_read_allows_ocr_by_default(monkeypatch):
    monkeypatch.setattr(
        server, "_ranked", lambda body: ([{"url": "https://example.org/scan.pdf"}], {}, 1)
    )
    seen = []

    def read(url, *args, **kwargs):
        seen.append(kwargs["allow_ocr"])
        return {"url": url, "quality": "ok", "content": "Verified source text"}

    monkeypatch.setattr(server, "_extract_row", read)
    client = TestClient(server.app)
    assert client.post("/search-and-fetch", json={"query": "scanned evidence"}).status_code == 200
    assert (
        client.post(
            "/search-and-fetch", json={"query": "scanned evidence", "ocr_mode": "never"}
        ).status_code
        == 200
    )
    assert seen == [True, False]


def test_source_file_versions_do_not_alias_when_extracted_text_is_identical(tmp_path):
    docs = Documents(tmp_path / "evidence.sqlite")
    first = docs.put(
        "a", "https://example.org/file", "same extracted text", {"file_sha256": "first"}
    )
    second = docs.put(
        "a", "https://example.org/file", "same extracted text", {"file_sha256": "second"}
    )
    assert first["document_id"] != second["document_id"]
    assert first["document_sha256"] == second["document_sha256"]
    assert docs.get("a", first["document_id"])["metadata"]["file_sha256"] == "first"


def test_invalid_unicode_json_can_be_reported_without_breaking_response_serialization():
    text, meta = formats.read_blob(b'{"value":"\\ud800"}', "json", 1000)
    assert "\\ud800" in text and meta["warnings"]
    assert text.encode("utf-8")


def test_corpus_retains_embedded_image_ocr_with_provenance():
    row = {
        "url": "https://example.org/report.docx",
        "quality": "ok",
        "content": "shown passage",
        "_index_text": "Native accurate prose.\n\n## Embedded image: image.png\nOCR number 89",
        "extraction": {"embedded_images": ["image.png"]},
    }
    result = server._harvest([row])
    assert "OCR number 89" in result[0][1]["content"]
    assert result[0][1]["extraction"]["embedded_images"] == ["image.png"]


def test_corpus_preserves_all_pdf_pages_with_ocr_provenance():
    row = {
        "url": "https://example.org/report.pdf",
        "quality": "ok",
        "content": "shown passage",
        "content_type": "application/pdf",
        "_index_text": "## Page 1\nNative quantity 47.\n\n## Page 2\nOCR quantity 89.",
        "extraction": {"pages": [{"page": 1, "method": "text"}, {"page": 2, "method": "ocr"}]},
    }
    result = server._harvest([row])
    assert "Native quantity 47" in result[0][1]["content"]
    assert "OCR quantity" in result[0][1]["content"]
    assert result[0][1]["extraction"]["pages"][1]["method"] == "ocr"


def test_concise_pdf_omits_full_document_blocks_without_mutating_evidence():
    from copy import deepcopy

    from dethrottled.content import compact_row

    row = {
        "content": "Requested evidence excerpt.", "document_id": "doc_retained",
        "document_chars": 466034, "next_offset": 8000, "truncated": True,
        "source_partial": False, "warnings": ["verify inferred tables"],
        "extraction": {"total_pages": 194, "partial": False, "next_page": None,
                       "native_table_scan": {"partial": True},
                       "pages": [{"page": n, "method": "text", "text_chars": 5000,
                                  "layout_may_be_incomplete": True,
                                  "text_layer_blocks": [{"bbox": [1, 2, 3, 4],
                                                         "text": "Evidence " * 500}]}
                                 for n in range(1, 195)]},
    }
    before = deepcopy(row)
    compact = compact_row(row)
    assert row == before
    assert len(json.dumps(compact)) < len(json.dumps(row)) / 10
    assert compact["content"] == row["content"]
    for field in ("document_id", "document_chars", "next_offset", "truncated",
                  "source_partial", "warnings"):
        assert compact[field] == row[field]
    assert len(compact["extraction"]["pages"]) == 194
    assert all(p["text_layer_block_count"] == 1 for p in compact["extraction"]["pages"])
    assert compact["extraction"]["native_table_scan"] == row["extraction"]["native_table_scan"]
    assert compact["extraction"]["presentation"]["omitted_text_layer_blocks"] == 194
    assert compact_row(compact) == compact


def test_concise_keeps_other_document_page_metadata():
    from dethrottled.content import compact_row

    row = {"content": "OCR evidence", "extraction": {"pages": [
        {"page": 1, "method": "ocr", "language": "eng", "warnings": ["verify pixels"]},
        {"page": 2, "method": "ocr", "text_layer_blocks": None}]}}
    assert compact_row(row) == row


def test_concise_pdf_omits_structured_table_metadata():
    from copy import deepcopy

    from dethrottled.content import compact_row

    row = {
        "content": "Requested evidence excerpt.",
        "document_id": "doc_large",
        "document_chars": 900000,
        "truncated": True,
        "warnings": ["table_structure_is_inferred; verify_critical_cells_against_source"],
        "extraction": {
            "total_pages": 200,
            "pages": [{"page": n, "method": "text", "text_chars": 5000,
                       "text_layer_blocks": [{"text": "block " * 200, "bbox": [0, 0, 1, 1]}]}
                      for n in range(1, 201)],
            "native_pdf_tables": [
                {"page": n, "cells": [[("cell-%d-%d-" % (n, r)) + "x" * 180
                                       for _ in range(10)] for r in range(30)]}
                for n in range(2, 4)
            ],
            "layout_tables": [{"page": n, "cells": [["big"] * 10] * 30} for n in range(1, 4)],
            "native_table_scan": {"page_start": 1, "page_end": 100, "partial": True},
            "layout_tables_total": 3,
        },
    }
    before = deepcopy(row)
    compact = compact_row(row)
    assert row == before
    extraction = compact["extraction"]
    assert "native_pdf_tables" not in extraction
    assert "layout_tables" not in extraction
    assert extraction["native_pdf_table_count"] == 2
    assert extraction["layout_table_count"] == 3
    assert extraction["layout_tables_total"] == 3
    assert extraction["native_table_scan"] == before["extraction"]["native_table_scan"]
    assert extraction["presentation"]["omitted_table_metadata"] == {
        "native_pdf_tables": 2, "layout_tables": 3}
    assert extraction["presentation"]["detail_available_with"] == {
        "response_format": "detailed"}
    assert compact["content"] == before["content"]
    assert compact["document_id"] == "doc_large"
    assert compact["truncated"] is True
    assert compact["warnings"] == before["warnings"]
    assert len(__import__("json").dumps(compact)) < 20000
    assert compact_row(compact) == compact


def test_concise_mixed_batch_compacts_pdf_tables_and_keeps_plain_rows():
    from dethrottled.content import present_row

    pdf = {
        "content": "PDF excerpt",
        "extraction": {
            "pages": [{"page": 1, "method": "text"}],
            "native_pdf_tables": [{"page": 1, "cells": [["x" * 500] * 10] * 20}],
        },
    }
    plain = {"content": "Plain excerpt", "quality": "ok"}
    out = [present_row(row, "concise") for row in (pdf, plain)]
    assert "native_pdf_tables" not in out[0]["extraction"]
    assert out[0]["extraction"]["native_pdf_table_count"] == 1
    assert out[1] == plain
    assert len(__import__("json").dumps(out)) < 5000
