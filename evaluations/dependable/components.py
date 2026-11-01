"""Recorded parser/regression tasks; fixtures are controlled, not web-accuracy evidence.

Run separately in baseline and candidate images with /evidence mounted writable.
"""

import gzip
import io
import json
import tarfile
import time
import zipfile
from pathlib import Path

import pymupdf
from docx import Document
from ebooklib import epub
from odf.opendocument import OpenDocumentText
from odf.text import P
from openpyxl import Workbook
from pptx import Presentation

from dethrottled import __version__, formats

root = Path("/evidence")
root.mkdir(exist_ok=True)
cases = []


def case(name, blob, kind, expected, options=None, checks=None):
    cases.append((name, blob, kind, expected, options or {}, checks or {}))


fact = "ALPHA allocation is 7341 tonnes."
case("unicode-text", ("Zürich 中文\n" + fact).encode(), "text", ["Zürich", "中文", "7341"])
case(
    "json-nested",
    json.dumps({"regions": [{"ALPHA": 7341}], "unit": "tonnes"}).encode(),
    "json",
    ["ALPHA", "7341", "tonnes"],
)
case(
    "jsonl-records",
    b'{"region":"ALPHA","value":7341}\n{"region":"BETA","value":291}',
    "jsonl",
    ["ALPHA", "7341", "BETA", "291"],
)
case("xml-namespace", b'<r xmlns="urn:test"><ALPHA unit="tonnes">7341</ALPHA></r>', "xml", ["7341"])
case(
    "email",
    ("From: test@example.org\nSubject: Allocation\nContent-Type: text/plain\n\n" + fact).encode(),
    "eml",
    ["7341", "tonnes"],
)
case(
    "csv-quotes",
    b'region,allocation,unit\n"ALPHA, NORTH",7341,tonnes\n',
    "csv",
    ["ALPHA, NORTH", "7341", "tonnes"],
)
rows = "id,value\n" + "".join(f"R{i},{i * 17}\n" for i in range(1, 2601))
case(
    "csv-late-range", rows.encode(), "csv", ["R2537", "43129"], {"row_start": 2538, "row_end": 2538}
)
case(
    "captions-vtt",
    b"WEBVTT\n\n00:05.000 --> 00:07.500\nALPHA 7341 tonnes\n",
    "captions",
    ["7341", "5.000", "7.500"],
)
case(
    "captions-srt",
    b"1\n00:00:05,000 --> 00:00:07,500\nALPHA 7341 tonnes\n",
    "captions",
    ["7341", "5.000", "7.500"],
)
case("gzip-text", gzip.compress(fact.encode()), "gzip", ["7341"])
for kind in ["zip", "tar"]:
    buf = io.BytesIO()
    if kind == "zip":
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("report.txt", fact)
            archive.writestr("second.json", '{"BETA":291}')
    else:
        with tarfile.open(fileobj=buf, mode="w") as archive:
            item = tarfile.TarInfo("report.txt")
            item.size = len(fact)
            archive.addfile(item, io.BytesIO(fact.encode()))
    case("archive-" + kind, buf.getvalue(), kind, ["7341"])
word = Document()
word.add_paragraph(fact)
table = word.add_table(rows=2, cols=2)
table.cell(0, 0).text, table.cell(0, 1).text = "Region", "tonnes"
table.cell(1, 0).text, table.cell(1, 1).text = "BETA", "291"
buf = io.BytesIO()
word.save(buf)
case("docx-table", buf.getvalue(), "docx", ["7341", "BETA", "291"])
book = Workbook()
book.active.title = "Summary"
book.active.append(["ALPHA", 7341])
book.create_sheet("Detail").append(["BETA", 291])
buf = io.BytesIO()
book.save(buf)
case("xlsx-all-sheets", buf.getvalue(), "xlsx", ["ALPHA", "7341", "BETA", "291"])
case("xlsx-sheet-selection", buf.getvalue(), "xlsx", ["BETA", "291"], {"sheet": "Detail"})
slides = Presentation()
slide = slides.slides.add_slide(slides.slide_layouts[1])
slide.shapes.title.text = "Allocation"
slide.placeholders[1].text = fact
buf = io.BytesIO()
slides.save(buf)
case("pptx", buf.getvalue(), "pptx", ["7341", "tonnes"])
case("rtf", b"{\\rtf1\\ansi ALPHA allocation is 7341 tonnes.}", "rtf", ["7341", "tonnes"])
odt = OpenDocumentText()
odt.text.addElement(P(text=fact))
buf = io.BytesIO()
odt.save(buf)
case("odt", buf.getvalue(), "odt", ["7341", "tonnes"])
book = epub.EpubBook()
book.set_identifier("allocation")
book.set_title("Allocation")
book.set_language("en")
chapter = epub.EpubHtml(title="Report", file_name="report.xhtml")
chapter.content = ("<h1>Report</h1><p>" + fact + "</p>").encode()
book.add_item(chapter)
book.spine = [chapter]
book.toc = [chapter]
book.add_item(epub.EpubNcx())
book.add_item(epub.EpubNav())
buf = io.BytesIO()
epub.write_epub(buf, book)
case("epub", buf.getvalue(), "epub", ["7341", "tonnes"])
pdf = pymupdf.open()
for number in range(1, 109):
    page = pdf.new_page()
    page.insert_text(
        (60, 60), f"Appendix page {number}. " + (fact if number == 107 else "Routine source notes.")
    )
case(
    "pdf-late-page",
    pdf.tobytes(),
    "pdf",
    ["7341", "tonnes"],
    {"page_start": 107, "page_end": 107, "document_mode": "native"},
)
case(
    "pdf-table",
    (Path(__file__).parent / "fixtures/table.pdf").read_bytes(),
    "pdf",
    ["ALPHA", "7341", "BETA"],
    {"document_mode": "auto"},
    {"table_cells": True},
)
pdf = pymupdf.open()
page = pdf.new_page()
page.insert_textbox(
    pymupdf.Rect(50, 60, 270, 700),
    "Northern district report.\n"
    + ("Alpha shipments use rail routes. " * 12)
    + "\nNORTH reserve is 9317 tonnes.",
    fontsize=12,
)
page.insert_textbox(
    pymupdf.Rect(315, 60, 550, 700),
    "Southern district report.\n"
    + ("Beta shipments use sea routes. " * 12)
    + "\nSOUTH reserve is 287 tonnes.",
    fontsize=12,
)
(root / "fixtures/columns.pdf").write_bytes(pdf.tobytes())
case("pdf-columns", pdf.tobytes(), "pdf", ["9317", "287", "tonnes"], {"document_mode": "auto"})
# Preregister before executing any parser. Variants/ranges are reported as such.
manifest = [
    {"id": n, "kind": k, "expected": e, "options": o, "checks": c} for n, _, k, e, o, c in cases
]
(root / "components-manifest.json").write_text(json.dumps(manifest, indent=2))
results = []
for name, blob, kind, expected, options, checks in cases:
    started = time.monotonic()
    try:
        text, metadata = formats.read_blob(blob, kind, 120000, options=options)
        matched = [value for value in expected if value in text]
        table_ok = not checks.get("table_cells") or bool(metadata.get("native_pdf_tables"))
        result = {
            "pass": len(matched) == len(expected) and table_ok,
            "matched": matched,
            "text": text,
            "metadata": metadata,
        }
    except Exception as exc:
        result = {"pass": False, "error": type(exc).__name__ + ": " + str(exc)[:200]}
    results.append(
        {
            "id": name,
            "version": __version__,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            **result,
        }
    )
    (root / ("components-" + __version__ + ".json")).write_text(json.dumps(results, indent=2))
print(
    json.dumps(
        {
            "version": __version__,
            "passed": sum(r["pass"] for r in results),
            "total": len(results),
            "failed": [r["id"] for r in results if not r["pass"]],
        }
    )
)
