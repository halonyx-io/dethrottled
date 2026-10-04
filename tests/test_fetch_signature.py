"""The HTTP path must use bytes, not a server's MIME label, to route files."""

import io

import pytest

from dethrottled import fetch

openpyxl = pytest.importorskip("openpyxl")
pymupdf = pytest.importorskip("pymupdf")


class Response:
    status_code = 200
    encoding = "utf-8"

    def __init__(self, data, content_type, url):
        self.data = data
        self.headers = {"Content-Type": content_type}
        self.url = url

    def iter_content(self, size):
        for at in range(0, len(self.data), size):
            yield self.data[at:at + size]


def direct(monkeypatch, data, content_type, url):
    monkeypatch.setattr(fetch, "_throttle", lambda domain: None)
    monkeypatch.setattr(fetch.requests, "get", lambda *a, **k: Response(data, content_type, url))
    return fetch._tier_direct(url, 20)


def test_xlsx_with_html_header_is_read_as_spreadsheet(monkeypatch):
    book = openpyxl.Workbook()
    book.active.append(["country", "megawatts"])
    book.active.append(["Denmark", 5120])
    stream = io.BytesIO()
    book.save(stream)
    result, reason, _ = direct(monkeypatch, stream.getvalue(), "text/html",
                               "https://example.com/download")
    assert reason == ""
    assert result["content_type"] == "xlsx"
    assert "Denmark | 5120" in result["text"]


def test_pdf_with_html_header_is_read_as_pdf(monkeypatch):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 80), "Signature routed PDF content")
    result, reason, _ = direct(monkeypatch, doc.tobytes(), "text/html",
                               "https://example.com/download")
    assert reason == ""
    assert result["content_type"] == "pdf"
    assert "Signature routed PDF" in result["text"]


def test_html_mislabeled_as_xls_remains_html(monkeypatch):
    html = b"<!doctype html><html><body>" + b"Useful page text. " * 100 + b"</body></html>"
    result, reason, _ = direct(monkeypatch, html, "application/vnd.ms-excel",
                               "https://example.com/report.xls")
    assert reason == ""
    assert "html" in result
    assert "Useful page text" in result["html"]
