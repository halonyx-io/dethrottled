"""Local PDF layout recovery; native text remains available if inference fails."""
import os
import re

import requests


def read_pdf(data, text, metadata, limit, options):
    mode = options.get("document_mode", "auto")
    if mode == "native":
        return text, metadata
    import pymupdf

    native_tables, table_text, complex_layout = [], [], False
    start = options.get("page_start", 1)
    end = metadata["pages"][-1]["page"]
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        for number in range(start - 1, end):
            page = pdf[number]
            blocks = page.get_text("blocks")
            left = [b for b in blocks if b[2] < page.rect.width * .6]
            right = [b for b in blocks if b[0] > page.rect.width * .4]
            complex_layout |= bool(left and right)
            try:
                tables = page.find_tables().tables
                for table in tables:
                    if len(native_tables) >= 20:
                        break
                    cells, table_chars = [], 0
                    for source_row in table.extract()[:100]:
                        values = [str(value or "")[:1000] for value in source_row[:30]]
                        if table_chars + sum(map(len, values)) > 20000:
                            break
                        cells.append(values)
                        table_chars += sum(map(len, values))
                    native_tables.append({"page": number + 1, "bbox": list(table.bbox),
                        "coordinate_space": "PDF points, origin top-left", "cells": cells,
                        "rows_total": table.row_count, "columns_total": table.col_count,
                        "partial": table.row_count > len(cells) or table.col_count > 30})
                    table_text.append(f"## Page {number + 1} — detected table\n" + "\n".join(
                        "| " + " | ".join(value.replace("|", "\\|").replace("\n", " ")
                                          for value in row) + " |" for row in cells))
            except (ValueError, RuntimeError):
                metadata["warnings"].append(f"Page {number + 1}: native_table_detection_failed")
    if native_tables:
        metadata["native_pdf_tables"] = native_tables
        combined = text + "\n\n" + "\n\n".join(table_text)
        if len(combined) > limit or any(t["partial"] for t in native_tables):
            metadata["partial"] = True
            metadata["warnings"].append("native_table_output_partial; select_fewer_pages")
        text = combined[:limit]
        metadata["warnings"].append(
            "table_structure_is_inferred; verify_critical_cells_against_source")
    worker = os.getenv("DETHROTTLED_LAYOUT_WORKER_URL", "").rstrip("/")
    if not worker:
        if mode == "layout":
            metadata["warnings"].append("layout_worker_not_configured; native_parser_used")
        return text, metadata
    scan = any("ocr" in page.get("method", "") for page in metadata.get("pages", []))
    if mode == "auto" and ((not complex_layout and not scan) or native_tables or end - start >= 10):
        return text, metadata
    try:
        response = requests.post(worker + "/convert", data=data,
            params={"page_start": start, "page_end": end,
                    "ocr": options.get("allow_ocr", True) and options.get("ocr_mode") != "never",
                    "ocr_language": options.get("ocr_language") or "eng"},
            headers={"Content-Type": "application/pdf"}, timeout=(5, 190), allow_redirects=False)
        response.raise_for_status()
        result = response.json()
        candidate = result["text"]
        # Do not trust model success when it loses native text/numbers/tables.
        numbers = set(re.findall(r"\b\d+(?:[.,]\d+)*\b", text))
        if (result.get("status") != "success" or not candidate.strip()
                or len(candidate) < len(text) * .7
                or not numbers.issubset(set(re.findall(r"\b\d+(?:[.,]\d+)*\b", candidate)))
                or (native_tables and len(result.get("tables", [])) < len(native_tables))):
            raise ValueError("layout_incomplete")
        metadata.update(parser="docling", ocr_layout=scan, layout_tables=result.get("tables", []),
                        layout_tables_total=result.get("tables_total", 0))
        if len(candidate) > limit:
            metadata["partial"] = True
            metadata["warnings"].append("layout_text_truncated")
        metadata["warnings"].append(
            "layout_is_model_inferred; verify_critical_cells_against_source")
        return candidate[:limit], metadata
    except (requests.RequestException, ValueError, KeyError, TypeError):
        metadata["warnings"].append("layout_unavailable_or_incomplete; native_parser_used")
        return text, metadata
