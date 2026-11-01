"""Evidence-led recovery and exact follow-up arguments for uncoached agents."""

from dethrottled import server
from dethrottled.workflow import guidance


def test_partial_table_uses_refetch_without_retained_bytes():
    row = {
        "url": "https://example.org/table.csv",
        "document_id": "doc_a",
        "quality": "ok",
        "source_partial": True,
        "extraction": {"tables": [{"next_row": 2001, "sheet": "Data"}]},
    }
    result = guidance(row)
    action = result["next_actions"][0]
    assert action["tool"] == "fetch"
    assert action["arguments"] == {
        "urls": [row["url"]],
        "row_start": 2001,
        "row_end": 4000,
        "sheet": "Data",
    }
    assert not result["source_complete"] and not result["answer_verified"]


def test_retained_pdf_continuation_and_pixel_inspection():
    row = {
        "url": "https://example.org/report.pdf",
        "document_id": "doc_a",
        "artifact_id": "file_a",
        "quality": "ok",
        "content_type": "pdf",
        "source_partial": True,
        "extraction": {
            "next_page": 101,
            "total_pages": 109,
            "pages": [{"page": 103, "method": "ocr"}],
        },
    }
    actions = guidance(row)["next_actions"]
    assert actions[0]["tool"] == "read_document"
    assert actions[0]["arguments"]["page_end"] == 109
    assert actions[1]["tool"] == "view_document_image"
    assert actions[1]["arguments"]["page"] == 103


def test_prefix_continuation_accounts_for_current_offset():
    row = {"document_id": "doc_a", "quality": "ok", "content": "abcd", "document_chars": 100}
    assert guidance(row, offset=20)["next_actions"][0]["arguments"]["offset"] == 24
    assert not guidance(row, focused=True)["next_actions"]


def test_no_term_matches_is_not_a_verified_answer():
    row = {"document_id": "doc_a", "quality": "ok", "focus_status": "no_term_matches"}
    result = guidance(row, focused=True)
    assert result["state"] == "needs_inspection" and not result["answer_verified"]
    assert result["next_actions"][0]["tool"] == "read_document"


def test_failed_or_unknown_source_is_not_complete():
    for row in [{"quality": "failed"}, {"quality": "ok", "content_status": "unknown"}]:
        assert not guidance(row)["source_complete"]


def test_unretained_ocr_never_suggests_impossible_image_tool():
    row = {
        "url": "https://example.org/image.png",
        "document_id": "doc_a",
        "quality": "ok",
        "warnings": ["OCR can misread numbers"],
        "extraction": {},
    }
    assert {a["tool"] for a in guidance(row)["next_actions"]} == {"drive"}


def test_recovery_reads_image_asset_and_keeps_provenance(monkeypatch):
    calls = []

    def read(url, budget, **options):
        calls.append((url, options))
        if url.endswith("/page"):
            return {
                "url": url,
                "quality": "ok",
                "content_status": "image_content",
                "document_id": "parent",
                "assets": [{"url": "https://example.org/schedule.png", "kind": "image"}],
            }
        return {"url": url, "quality": "ok", "content": "Train departs at 17:43"}

    monkeypatch.setattr(server, "_extract_once", read)
    row = server._extract_row("https://example.org/page", 1000)
    assert "17:43" in row["content"] and row["parent_document_id"] == "parent"
    assert row["recovery_attempts"][0]["action"] == "read_asset" and len(calls) == 2


def test_manual_recovery_and_explicit_never_are_respected(monkeypatch):
    calls = []

    def read(url, budget, **options):
        calls.append(options)
        return {"url": url, "quality": "ok", "content_status": "navigation_only", "content": "nav"}

    monkeypatch.setattr(server, "_extract_once", read)
    server._extract_row("https://example.org/page", 1000, recovery="manual")
    server._extract_row("https://example.org/page", 1000, allow_render=False)
    assert len(calls) == 2


def test_render_recovery_is_bounded_and_preserves_failed_recovery_evidence(monkeypatch):
    calls = []

    def read(url, budget, **options):
        calls.append(options)
        return {"url": url, "quality": "ok", "content_status": "navigation_only", "content": "nav"}

    monkeypatch.setattr(server, "_extract_once", read)
    row = server._extract_row("https://example.org/page", 1000)
    assert len(calls) == 2 and calls[1]["render_first"]
    assert row["content"] == "nav" and row["workflow"]["state"] == "needs_inspection"


def test_missing_source_bytes_reacquired_only_with_matching_hash(monkeypatch, tmp_path):
    import hashlib

    from dethrottled.evidence import Documents

    store = Documents(tmp_path / "evidence.sqlite")
    monkeypatch.setattr(server, "_documents", store)
    blob = b"quantity,unit\n47,crates\n"
    metadata = {"source_sha256": hashlib.sha256(blob).hexdigest()}
    handle = store.put("owner", "https://example.org/data.csv", "47 crates", metadata)
    record = store.get("owner", handle["document_id"])
    calls = []

    def read(url, **kwargs):
        calls.append(kwargs)
        kwargs["source_sink"](blob, "data.csv")
        return {"ok": True}

    monkeypatch.setattr(server.fetcher, "fetch_and_extract", read)
    artifact = server._source_artifact(record, "owner", True)
    assert artifact["data"] == blob and calls[0]["public_only"] is True
    assert calls[0]["allow_render"] is False and calls[0]["allow_ocr"] is False
    assert store.get("owner", handle["document_id"])["metadata"]["artifact_id"]
    record = store.get("owner", handle["document_id"])
    server._source_artifact(record, "owner", True)
    assert len(calls) == 1
    assert store.get("other", handle["document_id"]) is None


def test_changed_source_never_substitutes_new_pixels(monkeypatch, tmp_path):
    import hashlib

    import pytest
    from fastapi import HTTPException

    from dethrottled.evidence import Documents

    store = Documents(tmp_path / "evidence.sqlite")
    monkeypatch.setattr(server, "_documents", store)
    metadata = {"source_sha256": hashlib.sha256(b"original").hexdigest()}
    doc = store.put("owner", "https://example.org/source.pdf", "original", metadata)
    record = store.get("owner", doc["document_id"])

    def read(url, **kwargs):
        kwargs["source_sink"](b"changed", "source.pdf")
        return {"ok": True}

    monkeypatch.setattr(server.fetcher, "fetch_and_extract", read)
    with pytest.raises(HTTPException) as caught:
        server._source_artifact(record, "owner", True)
    assert caught.value.status_code == 409
    assert not store.get("owner", doc["document_id"])["metadata"].get("artifact_id")


def test_binary_source_sink_is_request_local_and_does_not_enter_cache(monkeypatch, tmp_path):
    from dethrottled import fetch
    from dethrottled.cache import Cache

    store = Cache(tmp_path / "cache.sqlite")
    monkeypatch.setattr(fetch, "ENABLE_TLS", False)

    def direct(url, timeout, allow_ocr):
        return fetch._binary_payload(b'{"count":47}', url, "application/json", allow_ocr)

    monkeypatch.setattr(fetch, "_tier_direct", direct)
    captured = []
    result = fetch.fetch_and_extract(
        "https://example.org/data.json",
        cache=store,
        source_sink=lambda data, name: captured.append(data),
    )
    assert result["ok"] and captured == [b'{"count":47}']
    cached = store.get("extract", "https://example.org/data.json")
    assert "source_sink" not in str(cached) and "artifact_id" not in str(cached)
