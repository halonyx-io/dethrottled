"""OpenDocument prose and tables should follow their source order."""

import io

import pytest

from dethrottled import documents


def test_odt_heading_paragraph_and_table_order():
    pytest.importorskip("odf")
    from odf.opendocument import OpenDocumentText
    from odf.table import Table, TableCell, TableRow
    from odf.text import H, P

    document = OpenDocumentText()
    document.text.addElement(H(outlinelevel=1, text="Capacity report"))
    document.text.addElement(P(text="Fiscal year 2025"))
    table = Table(name="Data")
    for values in (("Country", "Megawatts"), ("Denmark", "5120")):
        row = TableRow()
        for value in values:
            cell = TableCell()
            cell.addElement(P(text=value))
            row.addElement(cell)
        table.addElement(row)
    document.text.addElement(table)
    document.text.addElement(P(text="Excludes offshore capacity"))
    buffer = io.BytesIO()
    document.save(buffer)

    text, reason = documents.to_text(buffer.getvalue(), "odt", 20000)
    assert reason == ""
    assert text.splitlines() == [
        "Capacity report", "Fiscal year 2025", "Country | Megawatts",
        "Denmark | 5120", "Excludes offshore capacity"]
