import io
import shutil
import subprocess
from unittest.mock import patch

import pytest
from PIL import Image
from reportlab.pdfgen.canvas import Canvas

from documents.ocr import OCRFailure, extract
from tests.conftest import png_bytes


@pytest.mark.ocr
@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract executable not installed")
def test_real_tesseract_recognizes_printed_image(tmp_path):
    path = tmp_path / "invoice.png"
    path.write_bytes(png_bytes())
    result = extract(str(path), "image/png", str(tmp_path))
    assert "INVOICE" in result.text.upper()
    assert result.info["page_methods"] == ["tesseract"]


def pdf_bytes(pages=1, text="Native PDF financial statement"):
    stream = io.BytesIO()
    canvas = Canvas(stream)
    for _ in range(pages):
        canvas.drawString(60, 750, text)
        canvas.showPage()
    canvas.save()
    return stream.getvalue()


def test_native_pdf_text_layer_avoids_unnecessary_ocr(tmp_path):
    path = tmp_path / "report.pdf"
    path.write_bytes(pdf_bytes())
    with patch("documents.ocr._ocr_image") as engine:
        result = extract(str(path), "application/pdf", str(tmp_path))
    assert "financial statement" in result.text
    assert result.info["page_methods"] == ["text_layer"]
    engine.assert_not_called()


def test_scanned_pdf_page_uses_ocr(tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(pdf_bytes(text=""))
    with patch("documents.ocr._ocr_image", return_value="scanned page text"):
        result = extract(str(path), "application/pdf", str(tmp_path))
    assert result.text == "scanned page text"
    assert result.info["page_methods"] == ["tesseract"]


@pytest.mark.parametrize(
    "mime,payload",
    [("application/pdf", b"%PDF-invalid"), ("image/png", b"\x89PNG\r\n\x1a\ninvalid")],
)
def test_corrupt_file_fails_safely(tmp_path, mime, payload):
    path = tmp_path / "broken"
    path.write_bytes(payload)
    with pytest.raises(OCRFailure) as failure:
        extract(str(path), mime, str(tmp_path))
    assert failure.value.code == "invalid_document"


def test_page_limit(tmp_path, settings):
    settings.MAX_OCR_PAGES = 1
    path = tmp_path / "large.pdf"
    path.write_bytes(pdf_bytes(pages=2))
    with pytest.raises(OCRFailure, match="page limit"):
        extract(str(path), "application/pdf", str(tmp_path))


def test_pixel_limit_before_decoding(tmp_path, settings):
    settings.MAX_OCR_PIXELS = 10
    path = tmp_path / "large.png"
    path.write_bytes(png_bytes())
    with pytest.raises(OCRFailure, match="pixel limit"):
        extract(str(path), "image/png", str(tmp_path))


def test_text_limit(tmp_path, settings):
    settings.MAX_OCR_CHARS = 5
    path = tmp_path / "large.pdf"
    path.write_bytes(pdf_bytes())
    with pytest.raises(OCRFailure, match="character limit"):
        extract(str(path), "application/pdf", str(tmp_path))


@pytest.mark.parametrize(
    "failure,code",
    [
        (FileNotFoundError(), "ocr_engine_unavailable"),
        (subprocess.TimeoutExpired("tesseract", 1), "ocr_timeout"),
        (subprocess.CalledProcessError(1, "tesseract"), "ocr_engine_unavailable"),
    ],
)
def test_engine_failures_are_classified(tmp_path, failure, code):
    path = tmp_path / "image.png"
    path.write_bytes(png_bytes())
    with (
        patch("documents.ocr.subprocess.run", side_effect=failure),
        pytest.raises(OCRFailure) as error,
    ):
        extract(str(path), "image/png", str(tmp_path))
    assert error.value.code == code


def test_blank_image_is_success_with_warning(tmp_path):
    path = tmp_path / "blank.png"
    Image.new("RGB", (200, 100), "white").save(path)
    with patch("documents.ocr._ocr_image", return_value=""):
        result = extract(str(path), "image/png", str(tmp_path))
    assert result.text == "" and result.info["warnings"]
