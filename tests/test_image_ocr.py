"""Image OCR resolution handling.

Small screenshots and low-resolution scans are common evidence inputs. Tesseract
can lose digits in them at native size, so the image path makes one bounded 2x
pass. These tests pin both the bound and the recovered token.
"""

import io
import os
import shutil

import pytest

Image = pytest.importorskip("PIL.Image")
ImageDraw = pytest.importorskip("PIL.ImageDraw")
ImageFont = pytest.importorskip("PIL.ImageFont")

from dethrottled import formats  # noqa: E402

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
)


def _font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    pytest.skip("a TrueType font is not installed")


def _image(text, size=10, width=420, height=90):
    image = Image.new("RGB", (width, height), "white")
    ImageDraw.Draw(image).text((20, 25), text, fill="black", font=_font(size))
    return image


def _transparent_image(text, fill, size=18):
    image = Image.new("RGBA", (520, 100), (0, 0, 0, 0))
    ImageDraw.Draw(image).text((20, 30), text, fill=fill, font=_font(size))
    return image


def test_small_images_are_upscaled_for_ocr():
    png = formats._ocr_png(_image("invoice AB-1234"))
    with Image.open(io.BytesIO(png)) as result:
        assert result.size == (840, 180)


def test_large_images_are_left_at_native_resolution():
    image = Image.new("RGB", (2000, 1500), "white")
    png = formats._ocr_png(image)
    with Image.open(io.BytesIO(png)) as result:
        assert result.size == (2000, 1500)


def test_pdf_pages_keep_their_existing_render_resolution():
    png = formats._ocr_png(_image("invoice AB-1234"), upscale=False)
    with Image.open(io.BytesIO(png)) as result:
        assert result.size == (420, 90)


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
def test_low_resolution_digits_survive_the_ocr_path():
    image = _image("invoice AB-1234 total 90.50")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    text, meta = formats.image_text(buffer.getvalue(), 1000)
    assert "AB-1234" in text
    assert meta["pages"][0]["method"] == "ocr"
    assert meta["warnings"]


def test_transparent_dark_text_is_composited_on_white():
    flattened = formats._flatten_for_ocr(_transparent_image("dark", (0, 0, 0, 255)))
    assert flattened.mode == "RGB"
    assert flattened.getpixel((0, 0)) == (255, 255, 255)


def test_transparent_light_text_is_composited_on_black():
    flattened = formats._flatten_for_ocr(
        _transparent_image("light", (255, 255, 255, 255))
    )
    assert flattened.mode == "RGB"
    assert flattened.getpixel((0, 0)) == (0, 0, 0)


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
def test_transparent_pngs_are_readable():
    for fill, fact in (((0, 0, 0, 255), "alpha-717"), ((255, 255, 255, 255), "bravo-718")):
        image = _transparent_image("transparent fact " + fact, fill)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        text, _meta = formats.image_text(buffer.getvalue(), 1000)
        assert fact in text
