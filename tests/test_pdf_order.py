"""PDF drawing order should not place the footer before the heading."""

import pytest

from dethrottled import fetch


def test_pdf_text_follows_visible_page_order():
    pymupdf = pytest.importorskip("pymupdf")
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((50, 700), "Footer: page one")
    page.insert_text((50, 130), "Denmark capacity was 5120 megawatts in 2025")
    page.insert_text((50, 70), "Official energy report")

    text = fetch._pdf_text(document.tobytes(), 20000)
    assert text.index("Official energy report") < text.index("Denmark capacity")
    assert text.index("Denmark capacity") < text.index("Footer: page one")
