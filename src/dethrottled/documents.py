"""Spreadsheets, Word and PowerPoint, read as text.

Fetching HTML and text-layer PDFs and nothing else is a hole rather than a
limitation, because the citable numbers are so often the ones nobody published
as a web page. Statistical agencies, trade databases and procurement portals
put their actual figures in XLSX and their actual terms in DOCX, and a stack
that cannot read those cannot read its own primary sources.

Format is decided by SIGNATURE first when one exists. CSV has no reliable magic
and needs a Content-Type or URL hint; OLE2 needs a hint to distinguish XLS,
DOC and PPT. Servers mislabel these constantly -- an HTML error page served as
application/vnd.ms-excel is common, and handing that to a parser produces
either a crash or, worse, nonsense that looks like data. OOXML files are zips
and legacy Office files are OLE2 compound documents, so the bytes settle it.

Legacy .doc and .ppt use optional antiword/catppt converters when installed.
The container includes them; absent tools produce explicit unsupported reasons.
Binary Office stream names take precedence over misleading MIME/filename hints.
"""

import csv
import io
import os
from contextvars import ContextVar

# OOXML (xlsx/docx/pptx) is a zip; legacy Office is an OLE2 compound file. Both
# are unambiguous, which is why they are checked before anything the server
# claims about the bytes.
ZIP_MAGIC = b"PK\x03\x04"
OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# A national statistics export can run to six figures of rows. Nothing
# downstream reads that far and the extract cache would not hold it anyway.
MAX_ROWS = int(os.environ.get("DETHROTTLED_DOC_MAX_ROWS", "2000"))
MAX_CELL = int(os.environ.get("DETHROTTLED_DOC_MAX_CELL", "32767"))
csv.field_size_limit(32 * 1024 * 1024)
_DOC_CONTEXT = ContextVar("document_read_options", default=None)


def _options():
    return (_DOC_CONTEXT.get() or {}).get("options", {})


LEGACY = {"doc", "ppt"}

# The member whose presence identifies each OOXML format.
OOXML_MEMBERS = {
    "xl/workbook.xml": "xlsx",
    "word/document.xml": "docx",
    "ppt/presentation.xml": "pptx",
}

# What a zip's `mimetype` member declares. OpenDocument, EPUB and OOXML are all
# zips sharing the same four magic bytes, so the signature says "a zip" and
# nothing more -- but ODF and EPUB both put a `mimetype` member first and
# uncompressed, precisely so it can be read like this.
#
# ODF matters because it is what most European public bodies publish in, and
# an EPUB is a zip of XHTML. Both are ordinary things to be handed by a link.
MIMETYPE_MEMBERS = {
    "application/vnd.oasis.opendocument.text": "odt",
    "application/vnd.oasis.opendocument.spreadsheet": "ods",
    "application/vnd.oasis.opendocument.presentation": "odp",
    "application/epub+zip": "epub",
}

EXTENSIONS = {
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".xls": "xls",
    ".csv": "csv",
    ".tsv": "csv",
    ".docx": "docx",
    ".pptx": "pptx",
    ".doc": "doc",
    ".ppt": "ppt",
    ".odt": "odt",
    ".ods": "ods",
    ".odp": "odp",
    ".epub": "epub",
    ".rtf": "rtf",
}

CONTENT_TYPES = {
    "spreadsheetml.sheet": "xlsx",
    "wordprocessingml.document": "docx",
    "presentationml.presentation": "pptx",
    "vnd.ms-excel": "xls",
    "msword": "doc",
    "vnd.ms-powerpoint": "ppt",
    "text/csv": "csv",
    "opendocument.text": "odt",
    "opendocument.spreadsheet": "ods",
    "opendocument.presentation": "odp",
    "epub+zip": "epub",
    "application/rtf": "rtf",
    "text/rtf": "rtf",
}


def _ooxml_kind(data: bytes) -> str:
    """Which zip-based document this is, from the members it contains.

    Reading the directory is cheap: it lives at the end of the file and needs
    no decompression.
    """
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            for member, kind in OOXML_MEMBERS.items():
                if member in names:
                    return kind
            if "mimetype" in names:
                declared = archive.read("mimetype").decode("ascii", "replace").strip()
                return MIMETYPE_MEMBERS.get(declared, "")
    except Exception:
        # A truncated or encrypted zip is not a document we can read, and
        # saying so beats raising out of a type probe.
        return ""
    return ""


def kind_of(data: bytes, url: str = "", content_type: str = "") -> str:
    """The format of these bytes, or "" if it is not a document we read.

    Signature first, deliberately. CSV needs a header or extension hint because
    it has no magic; OLE2 needs one to distinguish its legacy subtypes.
    """
    if not data:
        return ""

    claimed = (content_type or "").lower()
    suffix = os.path.splitext((url or "").split("?")[0].lower())[1]

    if data[:4] == ZIP_MAGIC:
        # A zip that is not OOXML is some other archive, which we do not read.
        return _ooxml_kind(data)

    if data[:8] == OLE2_MAGIC:
        try:
            import olefile

            with olefile.OleFileIO(io.BytesIO(data)) as compound:
                for stream, kind in (
                    ("WordDocument", "doc"),
                    ("PowerPoint Document", "ppt"),
                    ("Workbook", "xls"),
                    ("Book", "xls"),
                ):
                    if compound.exists(stream):
                        return kind
        except (ImportError, OSError):
            pass
        # Legacy Office. Telling xls from doc from ppt needs the OLE2 directory,
        # so the claimed type decides. Being wrong is cheap here: a wrong guess
        # fails to parse rather than inventing data.
        for marker, kind in CONTENT_TYPES.items():
            if marker in claimed and kind in ("xls", "doc", "ppt"):
                return kind
        return EXTENSIONS.get(suffix, "xls")

    # RTF is plain text with a fixed opening token.
    if data[:5] == b"{\\rtf":
        return "rtf"

    # No signature, so only CSV qualifies -- and only when something says so,
    # because otherwise every HTML page looks like a one-column CSV.
    if "text/csv" in claimed or suffix in (".csv", ".tsv"):
        head = data[:2048].lstrip().lower()
        if head.startswith((b"<!doctype", b"<html")):
            return ""  # mislabelled HTML
        return "csv"
    return ""


def tidy_structured(value, limit: int = 0) -> str:
    """Normalise whitespace WITHOUT losing line breaks.

    fetch._tidy_text collapses every run of whitespace to one space, which is
    right for prose and destructive here. In a table the row boundary carries
    meaning: run two rows together and "Denmark | 2024 | 5120 Denmark | 2023 |
    4560" no longer says which number belongs to which year. Spreadsheets, OCR
    pages and slide decks all come through this instead.
    """
    lines = []
    for line in str(value or "").splitlines():
        line = " ".join(line.split())
        if line or (lines and lines[-1]):
            lines.append(line)
    out = "\n".join(lines).strip()
    if limit and len(out) > limit:
        out = out[:limit].rsplit(" ", 1)[0].strip()
    return out


def _cell(value) -> str:
    if value is None:
        return ""
    raw = str(value).replace("\n", " ").strip()
    cap = _options().get("max_cell_chars") or MAX_CELL
    context = _DOC_CONTEXT.get()
    if len(raw) > cap and context is not None:
        metadata = context["metadata"]
        metadata["partial"] = True
        metadata["truncated_cells"] = metadata.get("truncated_cells", 0) + 1
    return raw[:cap].replace("&", "&amp;").replace("|", "&#124;")


def _rows_to_text(title: str, rows, limit: int, total_rows=None) -> list:
    """Preserve empty cells, physical row positions and explicit row windows."""
    options = _options()
    start = options.get("row_start", 1)
    stop = min(options.get("row_end") or (start + MAX_ROWS - 1), start + MAX_ROWS - 1)
    out, size, returned, last, counted = [], 0, 0, start - 1, 0
    if title:
        out.append("## " + title)
        size += len(out[-1])
    for count, row in enumerate(rows, 1):
        counted = count
        if count == 1 and start > 1:
            context = "## Source row 1 (context): | " + " | ".join(_cell(v) for v in row) + " |"
            out.append(context)
            size += len(context)
        if count < start:
            continue
        if count > stop or size >= limit:
            if total_rows is not None:
                break
            continue
        cells = [_cell(value) for value in row]
        last = count
        if not any(cells):
            continue
        line = "| " + " | ".join(cells) + " |"
        out.append(line)
        size += len(line) + 1
        returned += 1
    total = counted if total_rows is None else total_rows
    context = _DOC_CONTEXT.get()
    if context is not None:
        metadata = context["metadata"]
        partial = start > 1 or last < total or size > limit
        metadata["partial"] = metadata.get("partial", False) or partial
        metadata.setdefault("tables", []).append(
            {
                "sheet": title,
                "total_rows": total,
                "row_start": start,
                "last_row": last,
                "returned_rows": returned,
                "next_row": last + 1 if last < total else None,
                "cell_encoding": "HTML entities for ampersands and pipe separators",
            }
        )
    return out if returned else []


def _from_xlsx(data: bytes, limit: int) -> str:
    import openpyxl

    book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    formula_book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=False)
    try:
        parts, size = [], 0
        context = _DOC_CONTEXT.get()
        if context is not None:
            context["metadata"]["available_sheets"] = book.sheetnames
        for sheet in book.worksheets:
            if _options().get("sheet") and sheet.title != _options()["sheet"]:
                if context is not None:
                    context["metadata"]["partial"] = True
                continue
            if size >= limit:
                break

            def resolved_rows(sheet=sheet):
                stop = min(
                    _options().get("row_end") or (_options().get("row_start", 1) + MAX_ROWS - 1),
                    1048576,
                )
                cached = sheet.iter_rows(values_only=True, max_row=min(stop, sheet.max_row or stop))
                formulas = formula_book[sheet.title].iter_rows(
                    values_only=True, max_row=min(stop, sheet.max_row or stop)
                )
                for values, originals in zip(cached, formulas):
                    yield [
                        original + " [formula; cached value unavailable]"
                        if value is None and isinstance(original, str) and original.startswith("=")
                        else value
                        for value, original in zip(values, originals)
                    ]

            lines = _rows_to_text(sheet.title, resolved_rows(), limit - size, sheet.max_row)
            if len(lines) > 1:
                parts.extend(lines)
                size += sum(len(x) + 1 for x in lines)
        return "\n".join(parts)
    finally:
        book.close()
        formula_book.close()


def _from_xls(data: bytes, limit: int) -> str:
    import xlrd

    book = xlrd.open_workbook(file_contents=data)
    parts, size = [], 0
    if _DOC_CONTEXT.get() is not None:
        _DOC_CONTEXT.get()["metadata"]["available_sheets"] = book.sheet_names()
    for sheet in book.sheets():
        if _options().get("sheet") and sheet.name != _options()["sheet"]:
            if _DOC_CONTEXT.get() is not None:
                _DOC_CONTEXT.get()["metadata"]["partial"] = True
            continue
        if size >= limit:
            break
        rows = (sheet.row_values(i) for i in range(sheet.nrows))
        lines = _rows_to_text(sheet.name, rows, limit - size, sheet.nrows)
        if len(lines) > 1:
            parts.extend(lines)
            size += sum(len(x) + 1 for x in lines)
    return "\n".join(parts)


def _from_csv(data: bytes, limit: int) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16", errors="replace")
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            # Older public datasets often export Windows-1252 CSV. Replacing
            # every accented letter with U+FFFD loses names and citations.
            text = data.decode("cp1252", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096])
    except csv.Error:
        dialect = csv.excel
    rows = csv.reader(io.StringIO(text), dialect)
    return "\n".join(_rows_to_text("", rows, limit))


def _from_docx(data: bytes, limit: int) -> str:
    import docx
    from docx.table import Table

    document = docx.Document(io.BytesIO(data))
    parts, size = [], 0
    # A report's prose often explains the table immediately before or after
    # it. Walking paragraphs and tables separately moves every table to the
    # end and can attach a number to the wrong explanation. python-docx 1.1+
    # exposes both kinds of block in their original document order.
    for block in document.iter_inner_content():
        if size >= limit:
            break
        if isinstance(block, Table):
            rows = ([c.text for c in r.cells] for r in block.rows)
            lines = _rows_to_text("", rows, limit - size)
            parts.extend(lines)
            size += sum(len(x) + 1 for x in lines)
        else:
            text = block.text.strip()
            if text:
                parts.append(text)
                size += len(text) + 1
    return "\n".join(parts)


def _from_pptx(data: bytes, limit: int) -> str:
    import pptx

    deck = pptx.Presentation(io.BytesIO(data))
    parts, size = [], 0
    for number, slide in enumerate(deck.slides, 1):
        if size >= limit:
            break
        said = []
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                said.append(shape.text_frame.text.strip())
            if shape.has_table:
                said.extend(
                    "| " + " | ".join(_cell(cell.text) for cell in row.cells) + " |"
                    for row in shape.table.rows
                )
        if said:
            block = "## Slide %d\n%s" % (number, "\n".join(said))
            parts.append(block)
            size += len(block) + 1
    return "\n".join(parts)


def _from_odf(data: bytes, limit: int) -> str:
    """OpenDocument text, spreadsheet or presentation.

    One reader for all three, because odfpy exposes them the same way: the
    document is XML and its text lives in <text:p> and <text:h> elements
    wherever they appear, table cells included.
    """
    from odf import teletype
    from odf import text as odftext
    from odf.opendocument import load
    from odf.table import TableRow

    document = load(io.BytesIO(data))
    lines, rows, size = [], 0, 0
    row_qname = TableRow().qname
    prose_qnames = {odftext.H(outlinelevel=1).qname, odftext.P().qname}

    def visit(element):
        nonlocal rows, size
        if size >= limit:
            return
        kind = getattr(element, "qname", None)
        if kind == row_qname:
            if rows >= MAX_ROWS:
                if _DOC_CONTEXT.get() is not None:
                    _DOC_CONTEXT.get()["metadata"]["partial"] = True
                return
            cells = []
            for cell in element.childNodes:
                if getattr(cell, "qname", (None, None))[1] not in {
                    "table-cell",
                    "covered-table-cell",
                }:
                    continue
                repeat = int(cell.getAttribute("numbercolumnsrepeated") or 1)
                value = _cell(teletype.extractText(cell))
                cap = min(4096, max(1, (limit - size) // max(1, len(value) + 3)))
                if repeat > cap:
                    if _DOC_CONTEXT.get() is not None:
                        _DOC_CONTEXT.get()["metadata"]["partial"] = True
                    repeat = cap
                cells.extend([value] * repeat)
            if any(cells):
                line = "| " + " | ".join(cells) + " |"
                repeat = int(element.getAttribute("numberrowsrepeated") or 1)
                cap = min(MAX_ROWS - rows, max(1, (limit - size) // max(1, len(line) + 1)))
                if repeat > cap:
                    if _DOC_CONTEXT.get() is not None:
                        _DOC_CONTEXT.get()["metadata"]["partial"] = True
                    repeat = cap
                lines.extend([line] * repeat)
                rows += repeat
                size += (len(line) + 1) * repeat
            return  # cell paragraphs are already in the row
        if kind in prose_qnames:
            line = teletype.extractText(element).strip()
            if line:
                lines.append(line)
                size += len(line) + 1
            return
        for child in getattr(element, "childNodes", ()):
            visit(child)

    # Traversal keeps headings, prose and tables in the order the document
    # author placed them. Collecting each kind separately had moved headings
    # ahead of paragraphs and every table behind the prose.
    visit(document.topnode)
    return "\n".join(lines)


def _from_epub(data: bytes, limit: int) -> str:
    """An EPUB is a zip of XHTML, so it goes through the same extractor as a
    web page -- which is what those documents are."""
    import ebooklib
    from ebooklib import epub

    from . import extract as _fx

    book = epub.read_epub(io.BytesIO(data), options={"ignore_ncx": True})
    parts = []
    ordered = [
        book.get_item_with_id(identifier) for identifier, linear in book.spine if linear != "no"
    ]
    for item in ordered or book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        if item is None:
            continue
        got = _fx.extract(item.get_content().decode("utf-8", "replace"), max_chars=limit)
        if got["ok"]:
            parts.append(got["text"])
        else:
            from .content import short_text

            recovered = short_text(item.get_content().decode("utf-8", "replace"))
            if recovered:
                parts.append(recovered)
        if sum(len(x) for x in parts) > limit:
            break
    return "\n\n".join(parts)


def _from_rtf(data: bytes, limit: int) -> str:
    """RTF via a pure-Python stripper. Not a rich conversion and does not need
    to be: the job is the words, not the formatting."""
    # Checked here as well as in kind_of(), because to_text() is public and a
    # caller naming the wrong kind would otherwise get its own bytes back as
    # "text" -- the stripper passes non-RTF through untouched.
    if not data[:5].startswith(b"{"):
        raise ValueError("not rtf")
    from striprtf.striprtf import rtf_to_text

    return rtf_to_text(data.decode("utf-8", "replace"), errors="ignore")


READERS = {
    "xlsx": _from_xlsx,
    "xls": _from_xls,
    "csv": _from_csv,
    "docx": _from_docx,
    "pptx": _from_pptx,
    "odt": _from_odf,
    "ods": _from_odf,
    "odp": _from_odf,
    "epub": _from_epub,
    "rtf": _from_rtf,
}


def to_text(data: bytes, kind: str, limit: int, *, options=None, metadata=None) -> tuple:
    """(text, reason). Empty text always arrives with a reason why."""
    if kind in LEGACY:
        import shutil
        import subprocess
        import tempfile

        binary = "antiword" if kind == "doc" else "catppt"
        if not shutil.which(binary):
            return "", "legacy_binary_format:%s" % kind
        try:
            with tempfile.TemporaryDirectory(prefix="dethrottled-office-") as directory:
                from pathlib import Path

                path = Path(directory) / ("source." + kind)
                path.write_bytes(data)
                done = subprocess.run([binary, str(path)], capture_output=True, timeout=30)
            if done.returncode:
                return "", "legacy_conversion_failed:" + kind
            text = done.stdout.decode("utf-8", errors="replace")
            return (text[:limit], "") if text.strip() else ("", "document_empty:" + kind)
        except (OSError, subprocess.TimeoutExpired):
            return "", "legacy_conversion_failed:" + kind
    reader = READERS.get(kind)
    if reader is None:
        return "", "unsupported_document:%s" % (kind or "unknown")
    token = _DOC_CONTEXT.set(
        {"options": options or {}, "metadata": metadata if metadata is not None else {}}
    )
    try:
        text = reader(data, limit)
    except Exception as exc:
        return "", "document_parse_failed:%s" % type(exc).__name__
    finally:
        _DOC_CONTEXT.reset(token)
    if not text.strip():
        return "", "document_empty:%s" % kind
    return text[:limit], ""
