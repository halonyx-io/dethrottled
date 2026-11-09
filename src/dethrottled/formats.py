"""Signature-led coverage for structured text, images, archives and mixed PDFs."""

from __future__ import annotations

import csv
import gzip
import io
import json
import re
import subprocess
import tarfile
import zipfile
from collections import defaultdict
from email import policy
from email.parser import BytesParser
from pathlib import PurePosixPath

from .content import decode_html, short_text

EXPANDED_LIMIT = 64 * 1024 * 1024
MEMBER_LIMIT = 50
# Native text is cheap compared with OCR/layout inference. Keep an independent
# work bound for sparse/malicious PDFs, without truncating ordinary long RFCs.
PDF_PAGE_CAP = 1000
# Tesseract needs enough pixels per glyph. Small screenshots and low-resolution
# scans otherwise lose digits and hyphenated tokens; a bounded 2x Lanczos pass
# recovered "hotel-905" from a low-resolution fixture that read "hote-005" at
# native size. Larger images already carry the detail, and upscaling them would
# only add work and memory.
OCR_UPSCALE_MAX_PIXELS = 2_500_000


def _flatten_for_ocr(page):
    """Composite transparency onto a background with contrast for the text."""
    from PIL import Image

    transparent = page.mode in ("RGBA", "LA") or (
        page.mode == "P" and "transparency" in page.info
    )
    if not transparent:
        return page.convert("RGB")
    rgba = page.convert("RGBA")
    if rgba.getchannel("A").getextrema()[0] == 255:
        return rgba.convert("RGB")
    # Transparent PNGs commonly store RGB 0,0,0 behind alpha 0. Converting that
    # straight to RGB paints black text on black. Pick a background with
    # contrast against the opaque pixels instead of assuming white.
    sample = rgba.copy()
    sample.thumbnail((64, 64))
    pixels = getattr(sample, "get_flattened_data", None) or sample.getdata
    visible = [pixel for pixel in pixels() if pixel[3] > 0]
    if visible:
        luminance = sum(
            0.299 * red + 0.587 * green + 0.114 * blue
            for red, green, blue, _alpha in visible
        ) / len(visible)
        background = (255, 255, 255, 255) if luminance < 128 else (0, 0, 0, 255)
    else:
        background = (255, 255, 255, 255)
    canvas = Image.new("RGBA", rgba.size, background)
    return Image.alpha_composite(canvas, rgba).convert("RGB")


def _ocr_png(page, upscale=True):
    """PNG bytes for Tesseract, with a bounded upscale for small images."""
    from PIL import Image

    if upscale and page.width * page.height <= OCR_UPSCALE_MAX_PIXELS:
        page = page.resize((page.width * 2, page.height * 2), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    page.save(buffer, format="PNG")
    return buffer.getvalue()


def kind_of(data, url="", content_type=""):
    from . import documents

    head = data[:2048].lstrip()
    lower = head.lower()
    if lower.startswith((b"<!doctype html", b"<html")):
        return ""
    if head.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(
        (b"\x89PNG", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"BM", b"II*\x00", b"MM\x00*")
    ) or (data.startswith(b"RIFF") and data[8:12] == b"WEBP"):
        return "image"
    if data.startswith(b"\x1f\x8b"):
        return "gzip"
    from .fallback import kind as fallback_kind
    extra = fallback_kind(data, url)
    if extra:
        return extra
    if data.startswith(documents.ZIP_MAGIC):
        return documents.kind_of(data, url, content_type) or "zip"
    if len(data) > 262 and data[257:262] == b"ustar":
        return "tar"
    native = documents.kind_of(data, url, content_type)
    if native:
        return native
    suffix = PurePosixPath(url.split("?")[0].lower()).suffix
    ctype = content_type.split(";")[0].strip().lower()
    if head.startswith(b"WEBVTT") or suffix in {".vtt", ".srt"} or ctype == "text/vtt":
        return "captions"
    if (ctype.startswith(("audio/", "video/")) or suffix in {
        ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".mp4", ".webm", ".mov"
    } or data.startswith((b"ID3", b"fLaC", b"OggS"))
        or (data.startswith(b"RIFF") and data[8:12] == b"WAVE")):
        return "media"
    if (
        head.startswith((b"{", b"["))
        and ctype in {"application/octet-stream", ""}
        and suffix not in {".jsonl", ".ndjson"}
    ):
        return "json"
    if suffix == ".eml" or ctype == "message/rfc822":
        return "eml"
    if suffix in {".jsonl", ".ndjson"} or ctype in {"application/x-ndjson", "application/jsonl"}:
        return "jsonl"
    if ctype in {"application/json", "application/ld+json"} or suffix in {".json", ".jsonld"}:
        return "json"
    if suffix in {".xml", ".svg", ".rss", ".atom"} or ctype in {
        "application/xml",
        "text/xml",
        "image/svg+xml",
        "application/rss+xml",
        "application/atom+xml",
    }:
        return "xml"
    if (ctype.startswith("text/") and "html" not in ctype) or suffix in {
        ".txt",
        ".md",
        ".markdown",
        ".log",
        ".yaml",
        ".yml",
        ".ics",
    }:
        return "text"
    return ""


def image_text(data, limit, language="", *, upscale=True):
    from PIL import Image, ImageOps

    from . import ocr

    parts, confidences, pages = [], [], []
    with Image.open(io.BytesIO(data)) as image:
        frames = getattr(image, "n_frames", 1)
        for number in range(min(frames, 8)):
            image.seek(number)
            if image.width * image.height > 40_000_000:
                raise ValueError("image_pixel_limit")
            page = _flatten_for_ocr(ImageOps.exif_transpose(image))
            png = _ocr_png(page, upscale=upscale)
            lang = language or ocr._choose(png, ocr.installed())[0]
            if not re.fullmatch(r"[a-z_]+(?:\+[a-z_]+)*", lang):
                raise ValueError("invalid_ocr_language")
            done = subprocess.run(
                ["tesseract", "stdin", "stdout", "-l", lang, "tsv"],
                input=png,
                capture_output=True,
                timeout=ocr.PAGE_TIMEOUT,
                env=ocr._environment(),
            )
            if done.returncode:
                raise ValueError("ocr_language_unavailable_or_failed")
            lines = defaultdict(list)
            for row in csv.DictReader(io.StringIO(done.stdout.decode()), delimiter="\t"):
                word = (row.get("text") or "").strip()
                if word:
                    lines[(row["block_num"], row["par_num"], row["line_num"])].append(word)
                    confidence = float(row.get("conf", -1))
                    if confidence >= 0:
                        confidences.append(confidence)
            text = "\n".join(" ".join(words) for words in lines.values())
            parts.append(text)
            pages.append({"page": number + 1, "method": "ocr", "language": lang})
            if sum(map(len, parts)) >= limit:
                break
    joined = "\n\n".join(parts)
    return joined[:limit], {
        "pages": pages,
        "total_pages": frames,
        "partial": len(pages) < frames or len(joined) > limit,
        "ocr_word_confidence": round(sum(confidences) / len(confidences), 2)
        if confidences
        else None,
        "warnings": [
            "OCR can misread numbers, layout and tables; verify against the source image. "
            "Word confidence is not an accuracy probability."
        ],
    }


def pdf_text(data, limit, allow_ocr, options):
    import pymupdf

    from . import ocr

    parts, pages, warnings = [], [], []
    size, truncated_page = 0, None
    ocr_count = 0
    start = options.get("page_start", 1) - 1
    requested_end = options.get("page_end")
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        if doc.needs_pass:
            raise ValueError("pdf_password_required")
        if start >= len(doc):
            raise ValueError("pdf_page_out_of_range")
        stop = min(len(doc), requested_end if requested_end is not None else start + PDF_PAGE_CAP)
        for number in range(start, stop):
            page = doc[number]
            text = page.get_text(sort=True)
            method = "text"
            # Sparse text often coexists with a scanned body; don't let a footer hide it.
            force_ocr = options.get("ocr_mode") == "always"
            if allow_ocr and (force_ocr or (len(text.strip()) < 100 and page.get_images())):
                if ocr_count < ocr.PAGE_CAP:
                    try:
                        ocr_count += 1
                        png = page.get_pixmap(dpi=ocr.DPI).tobytes("png")
                        # The page was already rendered at OCR DPI; upscaling it
                        # again changed table row recognition, so keep its pixels.
                        recovered, meta = image_text(
                            png, limit, options.get("ocr_language", ""), upscale=False
                        )
                        if recovered.strip():
                            if force_ocr and text.strip():
                                text, method = text + "\n[OCR reading]\n" + recovered, "text+ocr"
                            else:
                                text, method = recovered, "ocr"
                            warnings.extend(meta["warnings"])
                    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
                        warnings.append(f"Page {number + 1}: OCR failed: {exc}")
                else:
                    warnings.append(
                        f"Page {number + 1}: OCR page cap reached; select this page next."
                    )
                    # Do not mark unread scanned pages as consumed. The next
                    # range gets a fresh bounded OCR budget for this exact page.
                    break
            elif not text.strip():
                warnings.append(f"Page {number + 1} has no text layer; OCR was not performed.")
            part = f"## Page {number + 1}\n{text}"
            added = len(part) + (2 if parts else 0)
            # Do not consume a page and then discard its tail: a page-based
            # continuation must begin at the first page not retained in full.
            if parts and size + added > limit:
                break
            parts.append(part)
            size += added
            if size > limit:
                truncated_page = number + 1
                warnings.append(f"Page {number + 1}: page_text_truncated; "
                                "this page exceeds the character budget; inspect source pixels.")
            layout = [{"bbox": list(block[:4]), "text": block[4][:500],
                       "text_truncated": len(block[4]) > 500}
                      for block in page.get_text("blocks", sort=True)[:30] if block[6] == 0]
            pages.append({"page": number + 1, "method": method, "text_chars": len(text),
                          "text_layer_blocks": layout,
                          "layout_coordinate_space": "PDF points, origin top-left",
                          "layout_may_be_incomplete": True})
            if size >= limit:
                break
        joined = "\n\n".join(parts)
        if not any(page["text_chars"] for page in pages):
            raise ValueError("pdf_no_text_layer_or_ocr_output")
        incomplete = any(
            any(term in warning for term in ("no text layer", "failed", "cap reached"))
            for warning in warnings
        )
        partial = start > 0 or len(pages) < len(doc) or len(joined) > limit or incomplete
        if start + len(pages) < len(doc):
            warnings.append("PDF text window is partial; continue at next_page.")
        return joined[:limit], {
            "pages": pages,
            "total_pages": len(doc),
            "next_page": start + len(pages) + 1 if start + len(pages) < len(doc) else None,
            "partial": partial,
            "truncated_page": truncated_page,
            "warnings": sorted(set(warnings)),
        }


def read_blob(data, kind, limit, *, allow_ocr=True, options=None, depth=0):
    """Return parser text and provenance. Unsupported content never becomes HTML."""
    from . import documents

    options = options or {}
    if kind in {"captions", "media"}:
        from . import timed
        return timed.captions(data, limit) if kind == "captions" else timed.transcribe(data, limit)
    if kind in {"msg", "xlsb"}:
        from .fallback import read
        return read(data, kind, limit)
    metadata = {"warnings": [], "partial": False}
    if kind == "pdf":
        from .layout import read_pdf
        text, meta = pdf_text(data, limit, allow_ocr, options)
        return read_pdf(data, text, meta, limit, dict(options, allow_ocr=allow_ocr))
    if kind == "image":
        if not allow_ocr:
            raise ValueError("image_requires_ocr")
        return image_text(data, limit, options.get("ocr_language", ""))
    if data.startswith(documents.ZIP_MAGIC):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(item.file_size for item in archive.infolist()) > EXPANDED_LIMIT:
                raise ValueError("archive_expanded_limit")
    if kind in documents.READERS or kind in documents.LEGACY:
        if kind not in {"csv", "xlsx", "xls"} and (
            options.get("row_start", 1) != 1 or options.get("row_end") is not None
            or options.get("sheet")):
            raise ValueError("row_or_sheet_selection_requires_csv_xlsx_or_xls")
        text, reason = documents.to_text(data, kind, limit, options=options, metadata=metadata)
        if data.startswith(documents.ZIP_MAGIC) and allow_ocr:
            images = []
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for member in archive.infolist():
                    if member.filename.lower().endswith((".png", ".jpg", ".jpeg", ".tif", ".webp")):
                        images.append(member)
                metadata["embedded_images"] = [member.filename for member in images]
                for member in images[:8]:
                    if len(text) >= limit:
                        metadata["partial"] = True
                        break
                    try:
                        recovered, details = image_text(
                            archive.read(member), limit - len(text), options.get("ocr_language", "")
                        )
                        if recovered.strip():
                            text += "\n\n## Embedded image: " + member.filename + "\n" + recovered
                        metadata["warnings"].extend(details["warnings"])
                    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
                        metadata["partial"] = True
                        metadata["warnings"].append(
                            "Embedded image unreadable: " + member.filename + ": " + str(exc)[:100]
                        )
                if len(images) > 8:
                    metadata["partial"] = True
                    metadata["warnings"].append("Embedded image OCR capped at eight images.")
        if not text:
            raise ValueError(reason)
        metadata["partial"] = metadata["partial"] or len(text) >= limit
        if "[formula; cached value unavailable]" in text:
            metadata["warnings"].append(
                "Some formulas have no cached result; formula text is preserved."
            )
        if kind in documents.LEGACY:
            metadata["warnings"].append(
                "Legacy conversion does not preserve embedded images or exact layout."
            )
        return text[:limit], metadata
    if kind in {"zip", "tar", "gzip"}:
        if depth >= 2:
            raise ValueError("archive_nesting_limit")
        parts, members, skipped = [], [], []
        total = 0
        if kind == "gzip":
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
                blob = stream.read(EXPANDED_LIMIT + 1)
            if len(blob) > EXPANDED_LIMIT:
                raise ValueError("archive_expanded_limit")
            name = options.get("filename", "data.txt").removesuffix(".gz")
            entries = [(name, blob)]
        elif kind == "zip":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                files = [item for item in archive.infolist() if not item.is_dir()]
                if len(files) > MEMBER_LIMIT:
                    skipped.append("member limit reached")
                entries = [(item.filename, archive.read(item)) for item in files[:MEMBER_LIMIT]]
        else:
            entries = []
            with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                for item in archive:
                    if not item.isfile():
                        continue
                    if len(entries) >= MEMBER_LIMIT or total + item.size > EXPANDED_LIMIT:
                        skipped.append("member or expansion limit reached")
                        break
                    total += item.size
                    entries.append((item.name, archive.extractfile(item).read()))
        for name, blob in entries:
            if sum(map(len, parts)) >= limit:
                skipped.append(name + ": output limit")
                continue
            subtype = kind_of(blob, name)
            if not subtype and blob.lstrip().lower().startswith((b"<html", b"<!doctype html")):
                subtype = "html"
            if not subtype:
                skipped.append(name + ": unsupported format")
                continue
            try:
                text, meta = read_blob(
                    blob,
                    subtype,
                    limit - sum(map(len, parts)),
                    allow_ocr=allow_ocr,
                    options=options,
                    depth=depth + 1,
                )
                parts.append("## Archive member: " + name + "\n" + text)
                members.append({"name": name, "format": subtype, "partial": meta["partial"]})
                metadata["warnings"].extend(meta["warnings"])
            except (ValueError, OSError, ImportError) as exc:
                skipped.append(name + ": " + str(exc)[:120])
        metadata.update(
            members=members,
            skipped_members=skipped,
            partial=bool(skipped) or any(m["partial"] for m in members),
        )
        if not parts:
            raise ValueError("archive_no_readable_members")
        joined = "\n\n".join(parts)
        metadata["partial"] = metadata["partial"] or len(joined) > limit
        return joined[:limit], metadata
    text = decode_html(data)
    if "\x00" in text:
        raise ValueError("binary_not_text")
    if kind == "html":
        text = short_text(text)
    elif kind == "json":
        text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    elif kind == "jsonl":
        text = "\n".join(
            json.dumps(json.loads(line), ensure_ascii=False)
            for line in text.splitlines()
            if line.strip()
        )
    elif kind == "xml":
        from defusedxml import ElementTree

        root = ElementTree.fromstring(text)
        # Preserve attributes and data relationships, not just flattened text.
        text = ElementTree.tostring(root, encoding="unicode")
        if root.tag.endswith("svg"):
            metadata["warnings"].append(
                "SVG XML is preserved; shapes or bitmap text may require "
                "rendered-image inspection.")
    elif kind == "eml":
        mail = BytesParser(policy=policy.default).parsebytes(data)
        body = mail.get_body(preferencelist=("plain", "html"))
        text = body.get_content() if body else ""
        if body and body.get_content_type() == "text/html":
            text = short_text(text)
        text = (
            "\n".join(f"{key}: {mail.get(key, '')}" for key in ("From", "To", "Date", "Subject"))
            + "\n\n"
            + text
        )
        metadata["warnings"] = ["Attachments are not included in the email body extraction."]
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        text = text.encode("utf-8", errors="backslashreplace").decode()
        metadata["warnings"].append("Invalid Unicode codepoints are preserved as escape sequences.")
    metadata["partial"] = len(text) > limit
    return text[:limit], metadata
