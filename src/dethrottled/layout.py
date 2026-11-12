"""Local PDF layout recovery; native text remains available if inference fails."""
import os
import re

from . import netfilter as requests
from .workers import endpoint

# Share of native numeric tokens the layout model must retain before its output
# replaces the native parse. Headers, footers and page furniture are dropped by
# design, so a perfect score is not achievable on real documents; 0.85 keeps
# documents where the model lost track of the content (the IRS 1040 managed
# 0.39) while accepting the ones where it only dropped page furniture.
RETAINED_NUMBER_FLOOR = 0.85


def read_pdf(data, text, metadata, limit, options):
    mode = options.get("document_mode", "auto")
    if mode == "native":
        return text, metadata
    import pymupdf

    native_text_length = len(text)
    # Prose numbers, captured before native table markdown is appended. The
    # recall floor below compares prose against prose: docling re-expresses
    # table cells (and legitimately reorders them), so numbering every cell and
    # then demanding the model echo it compares two different renderings. On the
    # arXiv paper that inflated the check from 220 numbers to 279 and pushed
    # recall from 0.986 to 0.778, rejecting a conversion that was correct.
    # Table survival is checked separately by the table-count gate.
    prose_numbers = set(re.findall(r"\b\d+(?:[.,]\d+)*\b", text))
    native_tables, table_text, complex_layout = [], [], False
    start = options.get("page_start", 1)
    # How many pages were parsed natively. This is driven by max_chars, which is
    # an OUTPUT size limit -- not a statement about how much of the document is
    # worth analysing. Using it as the layout window meant a table on page 8 was
    # invisible to a 12,000-char fetch that only parsed three pages: measured on
    # the arXiv paper, tables live on pages 6-10 and layout_tables came back
    # empty no matter how large max_chars got, because the page range was capped
    # at the parse boundary. Layout gets its own page budget below.
    parsed_end = metadata["pages"][-1]["page"]
    end = parsed_end
    # Expanding native text must not multiply the expensive table-analysis
    # budget. Explicit ranges can target any later pages (API maximum: 100).
    scan_end = min(end, start + 99)
    metadata["native_table_scan"] = {"page_start": start, "page_end": scan_end,
                                     "partial": scan_end < end}
    if scan_end < end:
        metadata["warnings"].append(
            "native_table_scan_partial; select a later page range for table analysis")
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        for number in range(start - 1, scan_end):
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
    worker = endpoint("layout")
    if not worker:
        if mode == "layout":
            metadata["warnings"].append("layout_worker_not_configured; native_parser_used")
        return text, metadata
    # The layout model reads its own window, bounded independently of max_chars.
    # Table detection needs pages the native parse never touched; without this
    # "table on page 8" is unreachable on any request short enough to stop at
    # page 3. Total pages come from the PDF itself, capped by the budget so one
    # request cannot ask the worker for an unbounded scan.
    total_pages = int(metadata.get("total_pages") or parsed_end or end)
    budget = max(1, int(os.getenv("DETHROTTLED_LAYOUT_PAGE_BUDGET", "10")))
    layout_end = min(total_pages, start + budget - 1)
    layout_end = max(layout_end, parsed_end)
    end = layout_end
    scan = any("ocr" in page.get("method", "") for page in metadata.get("pages", []))
    if mode == "auto" and ((not complex_layout and not scan) or native_tables or end - start >= 10):
        return text, metadata
    if end - start >= 100:
        metadata["warnings"].append("layout_page_range_required; native_parser_used")
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
        # The number check is a RECALL floor, not a subset test. An exact
        # issubset rejected every real document that has a running header or
        # footer, because docling drops those on purpose: measured 2026-11-11,
        # the arXiv paper kept 36 of 39 numbers (92%) and the three missing ones
        # were the arXiv id "1706" and the dates "2017"/"2023" from the page
        # footer. That is correct extraction being thrown away. A document that
        # genuinely loses content still fails: the IRS 1040 retained only 39%
        # of its numbers and is rejected on both this and the length floor.
        numbers = prose_numbers
        kept = set(re.findall(r"\b\d+(?:[.,]\d+)*\b", candidate))
        number_recall = (len(numbers & kept) / len(numbers)) if numbers else 1.0
        if (result.get("status") != "success" or not candidate.strip()
                or len(candidate) < native_text_length * .7
                or number_recall < RETAINED_NUMBER_FLOOR
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
