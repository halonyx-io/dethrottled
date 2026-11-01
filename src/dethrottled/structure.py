"""Exact extracted-text selectors. Never infer source geometry from plain text."""

from __future__ import annotations

import hashlib
import re


def blocks(text, metadata=None):
    """Stable selectors into a retained version, with explicit coordinate space."""
    metadata = metadata or {}
    page, sheet, row = None, None, None
    table_metadata = metadata.get("extraction", {}).get("tables", [])
    known_sheets = {table.get("sheet") for table in table_metadata if table.get("sheet")}
    tables = iter(table_metadata)
    current_table = None
    for match in re.finditer(r"[^\n]+", text):
        value = match.group()
        if value.startswith("## Page ") and value[8:].strip().isdigit():
            page = int(value[8:])
        elif value.startswith("## ") and value[3:].strip() in known_sheets:
            sheet, row = value[3:].strip(), None
        kind = "heading" if value.startswith("#") else "paragraph"
        if value.startswith("| "):
            kind = "table_row"
            if current_table is None or (sheet and current_table.get("sheet") != sheet):
                current_table = next(tables, {})
                row = 0
            row = (row or 0) + 1
        digest = hashlib.sha256(value.encode()).hexdigest()
        yield {
            "block_id": f"b{match.start()}-{digest[:12]}", "kind": kind,
            "start": match.start(), "end": match.end(), "text": value,
            "text_sha256": digest, "page": page,
            "sheet": sheet if kind == "table_row" else None,
            # Empty physical spreadsheet rows may be omitted by the text parser.
            # Do not mislabel a returned-row ordinal as a source row number.
            "returned_row": row if kind == "table_row" else None,
            "coordinate_space": "retained_text_unicode_codepoints",
        }


def select(record, *, offset=0, limit=50, focus=""):
    terms = set(re.findall(r"\w+", focus.casefold()))
    selected, total = [], 0
    for block in blocks(record["text"], record.get("metadata")):
        if terms and not terms.intersection(re.findall(r"\w+", block["text"].casefold())):
            continue
        if total >= offset and len(selected) < limit:
            selected.append(block)
        total += 1
    for block in selected:
        block["citation"] = {
            "url": record["url"], "document_id": record["document_id"],
            "document_sha256": record["document_sha256"],
            "selector": {"type": "TextPositionSelector", "start": block["start"],
                         "end": block["end"], "exact": block["text"]},
        }
        timed = re.match(r"\[([\d.]+)-([\d.]+)\]", block["text"])
        if timed:
            block["kind"] = "timed_segment"
            block["citation"]["time_selector"] = {
                "start_seconds": float(timed[1]), "end_seconds": float(timed[2])}
    return {"document_id": record["document_id"],
            "document_sha256": record["document_sha256"],
            "blocks": selected, "matched_blocks": total,
            "next_offset": offset + len(selected) if offset + len(selected) < total else None,
            "layout": "Text blocks use retained-text offsets; PDF text-layer boxes "
                      "use source page points and are not an OCR alignment.",
            "page_layout": record.get("metadata", {}).get("extraction", {}).get("pages", [])[:5],
            "native_pdf_tables": record.get("metadata", {}).get("extraction", {}).get(
                "native_pdf_tables", []),
            "layout_tables": record.get("metadata", {}).get("extraction", {}).get(
                "layout_tables", []),
            "answer_verified": False}
