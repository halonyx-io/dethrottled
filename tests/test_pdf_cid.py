"""CID-corrupted PDF text layers must not look like a successful read."""

import pytest

pymupdf = pytest.importorskip("pymupdf")

from dethrottled import formats  # noqa: E402


def _pdf(text):
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def test_cid_garbage_thresholds():
    assert formats._cid_garbage("(cid:1)(cid:2)(cid:3)(cid:4)(cid:5)")
    assert formats._cid_garbage("(cid:1)(cid:2)(cid:3)" + "x" * 20)
    assert not formats._cid_garbage("ordinary text with one (cid:1) mention")
    assert not formats._cid_garbage("a" * 10_000 + "(cid:1)(cid:2)")


def test_cid_page_forces_ocr_and_records_provenance(monkeypatch):
    calls = []

    def fake_image_text(data, limit, language="", *, upscale=True):
        calls.append((len(data), language, upscale))
        return "Recovered page text", {"warnings": ["OCR warning"]}

    monkeypatch.setattr(formats, "image_text", fake_image_text)
    text, meta = formats.pdf_text(
        _pdf("(cid:100)(cid:200)(cid:300)"), 10000, True, {}
    )
    assert "Recovered page text" in text
    assert "cid:" not in text
    assert meta["pages"][0]["method"] == "ocr"
    assert meta["pages"][0]["cid_garbage"] is True
    assert any("cid_garbage_recovered" in warning for warning in meta["warnings"])
    assert calls and calls[0][2] is False


def test_cid_page_without_ocr_keeps_a_warning(monkeypatch):
    monkeypatch.setattr(
        formats, "image_text", lambda *a, **k: pytest.fail("OCR must stay disabled")
    )
    text, meta = formats.pdf_text(_pdf("(cid:100)(cid:200)(cid:300)"), 10000, False, {})
    assert "cid:" in text
    assert any("ocr disabled" in warning.lower() for warning in meta["warnings"])


def test_normal_page_does_not_trigger_ocr(monkeypatch):
    monkeypatch.setattr(
        formats, "image_text", lambda *a, **k: pytest.fail("normal text must not OCR")
    )
    text, meta = formats.pdf_text(
        _pdf("A normal text layer with enough readable words to stay on the native path."),
        10000,
        True,
        {},
    )
    assert "normal text layer" in text
    assert meta["pages"][0]["cid_garbage"] is False
