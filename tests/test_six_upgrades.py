"""Evidence selectors, discovery boundaries, timed sources and restart recovery."""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from dethrottled import formats, server, structure, timed
from dethrottled.evidence import Documents
from dethrottled.jobs import JobError, Jobs
from dethrottled.site import crawl, links


def test_quote_selectors_are_exact_unicode_positions_and_scoped(tmp_path, monkeypatch):
    store = Documents(tmp_path / "evidence.sqlite")
    text = "## Evidence\nZürich 中文 | 17 tonnes\n[2.000-4.500] train at noon"
    saved = store.put("alice", "https://example.org/report", text, {})
    monkeypatch.setattr(server, "documents", lambda: store)
    client = TestClient(server.app)
    args = {"document_id": saved["document_id"], "evidence_namespace": "alice"}
    result = client.post("/documents/structure", json=args).json()
    for block in result["blocks"]:
        assert text[block["start"]:block["end"]] == block["text"]
        assert block["citation"]["document_sha256"] == saved["document_sha256"]
    assert result["blocks"][-1]["citation"]["time_selector"]["end_seconds"] == 4.5
    assert client.post("/documents/structure", json=dict(
        args, evidence_namespace="bob")).status_code == 404
    focused = structure.select(store.get("alice", saved["document_id"]), focus="Zürich")
    assert len(focused["blocks"]) == 1


def test_crawl_counts_failures_cycles_and_outside_links():
    pages = {
        "https://example.org/": '<a href="/a">a</a><a href="/a#x">a</a>'
        '<a href="/bad">bad</a><a href="https://other.org/">other</a>',
        "https://example.org/a": '<a href="/">home</a><a href="/late">late</a>',
    }
    def read(url):
        return {"quality": "ok", "html": pages[url]} if url in pages else {"quality": "failed"}
    result = crawl(["https://example.org/"], read, max_pages=3)
    assert result["coverage"]["attempted"] == 3
    assert result["coverage"]["failed"] == 1
    assert result["coverage"]["duplicate_links"] == 2
    assert result["continuation_urls"] == ["https://example.org/late"]
    assert result["coverage"]["whole_site_complete"] is None


def test_sitemap_and_depth_limits_are_explicit():
    xml = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' \
          '<url><loc>https://example.org/one</loc></url></urlset>'
    result = crawl(["https://example.org/sitemap.xml"],
                   lambda u: {"quality": "ok", "content": xml}, max_depth=0)
    assert result["coverage"]["depth_or_discovery_limited"] == 1
    assert not result["coverage"]["frontier_exhausted"]


def test_discovery_does_not_expand_untrusted_xml_entities():
    source = '<!DOCTYPE html [<!ENTITY x "not evidence">]><html>' \
             '<a href="/report">report</a></html>'
    assert links(source, "https://example.org/") == ["https://example.org/report"]


def test_table_context_heading_cannot_replace_sheet_identity():
    text = "## Data\n## Source row 1 (context): | name | value |\n| later | 17 |"
    metadata = {"extraction": {"tables": [{"sheet": "Data", "row_start": 2500}]}}
    row = list(structure.blocks(text, metadata))[-1]
    assert row["sheet"] == "Data" and row["returned_row"] == 1


def test_site_rejects_mixed_origins_before_read():
    client = TestClient(server.app)
    for urls in [["https://example.org/", "https://other.org/"], ["file:///etc/passwd"]]:
        assert client.post("/site/crawl", json={"urls": urls}).status_code == 422


@pytest.mark.parametrize("data,extension", [
    (b"WEBVTT\n\n00:02.000 --> 00:04.500\nTrain &amp; bus\n", ".vtt"),
    (b"1\n00:00:02,000 --> 00:00:04,500\nTrain &amp; bus\n", ".srt"),
])
def test_caption_formats_preserve_verifiable_time_ranges(data, extension):
    kind = formats.kind_of(data, "https://example.org/captions" + extension)
    text, meta = formats.read_blob(data, kind, 1000)
    assert "Train & bus" in text
    assert meta["segments"][0]["start_seconds"] == 2
    assert meta["segments"][0]["end_seconds"] == 4.5
    assert not meta["partial"]


def test_caption_budget_never_returns_invented_partial_segment():
    text, meta = timed.captions(b"WEBVTT\n\n00:01.000 --> 00:02.000\nhello world", 3)
    assert not text and meta["partial"] and meta["total_segments"] == 1


def test_audio_requires_explicit_worker_configuration(monkeypatch):
    monkeypatch.delenv("DETHROTTLED_MEDIA_WORKER_URL", raising=False)
    assert formats.kind_of(b"RIFF0000WAVE", "x.wav") == "media"
    with pytest.raises(ValueError, match="speech_worker_not_configured"):
        formats.read_blob(b"RIFF0000WAVE", "media", 1000)


def test_pdf_layout_reports_actual_source_points_not_text_offsets():
    pdf = pytest.importorskip("pymupdf")
    doc = pdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Verified allocation is 17 tonnes.")
    blob = doc.tobytes()
    doc.close()
    text, metadata = formats.read_blob(blob, "pdf", 10000, allow_ocr=False)
    layout = metadata["pages"][0]
    assert layout["layout_coordinate_space"] == "PDF points, origin top-left"
    assert layout["text_layer_blocks"][0]["bbox"][0] == 72
    assert "17 tonnes" in layout["text_layer_blocks"][0]["text"]
    record = {"text": text, "metadata": {"extraction": metadata}, "url": "source.pdf",
              "document_id": "doc_test", "document_sha256": "version"}
    selected = structure.select(record)
    assert selected["page_layout"][0]["text_layer_blocks"] == layout["text_layer_blocks"]


def test_restart_resume_preserves_completed_rows_and_namespace(tmp_path):
    path = tmp_path / "jobs.sqlite"
    first = Jobs(path)
    # Model a crash between the first committed source and the next origin read.
    payload = {"urls": ["https://example.org/one", "https://example.org/two"]}
    first.db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)", (
        "job_test", "alice", None, "digest", "running", 2, time.time(),
        time.time() + 300))
    first.db.execute("INSERT INTO job_payloads VALUES(?,?)", ("job_test", json.dumps(payload)))
    first.db.execute("INSERT INTO results VALUES(?,?,?,?)", (
        "job_test", 0, 0, json.dumps({"url": payload["urls"][0], "content": "saved"})))
    first.db.commit()
    first.db.close()
    store = Jobs(path)
    assert store.get("alice", "job_test")["status"] == "interrupted"
    called = []
    def factory(saved):
        assert saved == payload
        def read(url):
            called.append(url)
            return {"url": url, "content": "new"}
        return read
    with ThreadPoolExecutor(2) as pool:
        with pytest.raises(JobError):
            store.resume("bob", "job_test", factory, pool)
        store.resume("alice", "job_test", factory, pool)
        for _ in range(100):
            result = store.get("alice", "job_test")
            if result["status"] == "completed":
                break
            time.sleep(.01)
    assert called == [payload["urls"][1]]
    assert result["completed"] == 2
    assert result["results"][0]["content"] == "saved"


def test_cancel_resume_fences_old_inflight_results(tmp_path):
    store = Jobs(tmp_path / "jobs.sqlite")
    entered, release = threading.Event(), threading.Event()
    def old(url):
        entered.set()
        release.wait(3)
        return {"content": "stale"}
    with ThreadPoolExecutor(2) as pool:
        identifier = store.submit("alice", {"urls": ["x"]}, "", old, pool)
        assert entered.wait(2)
        store.cancel("alice", identifier)
        store.resume("alice", identifier, lambda p: lambda u: {"content": "new"}, pool)
        release.set()
        for _ in range(100):
            result = store.get("alice", identifier)
            if result["status"] == "completed":
                break
            time.sleep(.01)
    assert result["completed"] == 1 and result["results"][0]["content"] == "new"
