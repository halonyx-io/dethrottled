"""Long native PDFs and bounded continuation must retain late-page evidence."""

import pytest

from dethrottled import formats
from dethrottled.readplan import run


def pdf_bytes(labels):
    pymupdf = pytest.importorskip("pymupdf")
    with pymupdf.open() as doc:
        for label in labels:
            doc.new_page().insert_text((50, 70), label)
        return doc.tobytes()


def test_implicit_range_keeps_late_native_facts():
    blob = pdf_bytes([f"PAGE {n} evidence marker" for n in range(1, 195)])
    text, meta = formats.pdf_text(blob, 1000000, False, {})
    assert "PAGE 194 evidence marker" in text
    assert len(meta["pages"]) == 194
    assert meta["next_page"] is None and not meta["partial"]


def test_explicit_range_stays_explicit():
    blob = pdf_bytes([f"PAGE {n} evidence marker" for n in range(1, 105)])
    text, meta = formats.pdf_text(blob, 1000000, False, {"page_start": 2, "page_end": 3})
    assert [p["page"] for p in meta["pages"]] == [2, 3]
    assert "PAGE 4 evidence marker" not in text
    assert meta["next_page"] == 4 and meta["partial"]


def test_character_window_stops_before_clipping_a_later_page():
    labels = ["FIRST fact 47", "SECOND fact 89", "THIRD fact 123"]
    blob = pdf_bytes(labels)
    first, _ = formats.pdf_text(blob, 10000, False, {"page_end": 1})
    text, meta = formats.pdf_text(blob, len(first) + 10, False, {})
    assert text == first
    assert meta["next_page"] == 2
    remaining, _ = formats.pdf_text(blob, 10000, False, {"page_start": meta["next_page"]})
    assert all(label in text + remaining for label in labels)


def test_single_oversize_page_is_explicitly_incomplete():
    blob = pdf_bytes(["Beginning of page; IMPORTANT END FACT 47"])
    _, meta = formats.pdf_text(blob, 30, False, {})
    assert meta["partial"]
    assert meta["truncated_page"] == 1
    assert any("page_text_truncated" in warning for warning in meta["warnings"])


def test_partial_pdf_does_not_drive_html_browser():
    def forbidden(*args, **kwargs):
        pytest.fail("A PDF range needs PDF continuation, not HTML browser recovery")

    initial = {
        "url": "https://example.org/report.pdf",
        "quality": "ok",
        "content_type": "application/pdf",
        "content_status": "partial",
        "source_partial": True,
        "content": "Readable PDF evidence",
        "extraction": {"next_page": 101, "total_pages": 194},
    }
    row = run(
        initial["url"], initial, read=forbidden, drive=forbidden, options={}, browser_available=True
    )
    assert row["read_plan"]["decisions"] == []
    assert row["read_plan"]["stop_reason"] == "document_continuation_required"


def test_reparse_refreshes_status_and_retains_original_version(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from dethrottled import server
    from dethrottled.evidence import Documents

    store = Documents(tmp_path / "documents.sqlite")
    monkeypatch.setattr(server, "_documents", store)
    artifact = store.put_artifact("test", "report.pdf", pdf_bytes(["COMPLETE FACT 47"]))
    original = store.put(
        "test",
        "https://example.org/report.pdf",
        "old partial read",
        {
            "artifact_id": artifact,
            "quality": "ok",
            "content_type": "application/pdf",
            "content_status": "partial",
            "source_partial": True,
            "content_chars": 16,
            "read_plan": {"final_gap": "partial_capture"},
            "extraction": {"partial": True, "next_page": 1},
        },
    )
    result = (
        TestClient(server.app)
        .post(
            "/documents/read",
            json={
                "document_id": original["document_id"],
                "evidence_namespace": "test",
                "reparse": True,
                "document_mode": "native",
            },
        )
        .json()
    )
    assert result["content_status"] == "complete"
    assert not result["source_partial"] and not result["extraction"]["partial"]
    assert "COMPLETE FACT 47" in result["content"]
    assert result["content_chars"] == result["document_chars"] == len(result["content"])
    assert result["workflow"]["state"] == "evidence_available"
    assert store.get("test", original["document_id"])["metadata"]["content_status"] == "partial"


def test_table_scan_budget_does_not_cut_native_text():
    blob = pdf_bytes([f"PAGE {n} evidence marker" for n in range(1, 103)])
    text, meta = formats.read_blob(blob, "pdf", 1000000, allow_ocr=False)
    assert "PAGE 102 evidence marker" in text
    assert meta["native_table_scan"] == {"page_start": 1, "page_end": 100, "partial": True}
    assert any("native_table_scan_partial" in warning for warning in meta["warnings"])


def test_native_page_work_remains_bounded(monkeypatch):
    monkeypatch.setattr(formats, "PDF_PAGE_CAP", 2)
    blob = pdf_bytes(["FIRST fact", "SECOND fact", "THIRD fact"])
    _, meta = formats.pdf_text(blob, 1000000, False, {})
    assert len(meta["pages"]) == 2 and meta["next_page"] == 3 and meta["partial"]


def test_late_clipped_page_inspection_targets_the_actual_page():
    from dethrottled.workflow import guidance

    row = {
        "quality": "ok",
        "document_id": "doc_late",
        "artifact_id": "file_pdf",
        "content_type": "application/pdf",
        "source_partial": True,
        "extraction": {"truncated_page": 105, "pages": [{"page": 105, "method": "text"}]},
    }
    actions = guidance(row)["next_actions"]
    assert (
        next(a for a in actions if a["tool"] == "view_document_image")["arguments"]["page"] == 105
    )


def test_ocr_budget_continuation_starts_at_first_unread_scan(monkeypatch):
    import io

    pymupdf = pytest.importorskip("pymupdf")
    image = pytest.importorskip("PIL.Image")
    from dethrottled import ocr

    monkeypatch.setattr(ocr, "PAGE_CAP", 1)
    monkeypatch.setattr(formats, "image_text", lambda *args: ("SCANNED FACT 47", {"warnings": []}))
    png = io.BytesIO()
    image.new("RGB", (50, 50), "white").save(png, format="PNG")
    with pymupdf.open() as doc:
        for _ in range(3):
            page = doc.new_page()
            page.insert_image(page.rect, stream=png.getvalue())
        blob = doc.tobytes()
    _, meta = formats.pdf_text(blob, 1000000, True, {})
    assert [p["page"] for p in meta["pages"]] == [1]
    assert meta["next_page"] == 2 and meta["partial"]
    _, continued = formats.pdf_text(blob, 1000000, True, {"page_start": 2})
    assert [p["page"] for p in continued["pages"]] == [2]
    assert continued["next_page"] == 3
