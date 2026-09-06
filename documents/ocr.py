"""Bounded local extraction. This module never performs network OCR calls."""

import os
import subprocess
import warnings
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError

MESSAGES = {
    "invalid_document": "The document is damaged, encrypted or cannot be decoded.",
    "page_limit": "The document exceeds the configured page limit.",
    "pixel_limit": "A page or image exceeds the configured pixel limit.",
    "text_limit": "The extracted text exceeds the configured character limit.",
    "ocr_timeout": "Text extraction exceeded its time limit.",
    "ocr_engine_unavailable": "The extraction engine or configured language is unavailable.",
    "storage_unavailable": "The original file is temporarily unavailable.",
    "integrity_error": "The stored file failed its integrity check.",
    "worker_lost": "The worker stopped before completing the job.",
    "unexpected_error": "Processing failed unexpectedly. Use the request ID for diagnostics.",
}


class OCRFailure(Exception):
    def __init__(self, code, retryable=False):
        self.code = code
        self.retryable = retryable
        super().__init__(MESSAGES[code])


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    info: dict


def _check_pixels(width, height):
    if width <= 0 or height <= 0 or width * height > settings.MAX_OCR_PIXELS:
        raise OCRFailure("pixel_limit")


def _ocr_image(image, workspace):
    _check_pixels(*image.size)
    path = Path(workspace) / "ocr-page.png"
    image.save(path, format="PNG")
    try:
        completed = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", settings.OCR_LANGUAGES, "--psm", "3"],
            check=True,
            capture_output=True,
            timeout=settings.OCR_PAGE_TIMEOUT,
            env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        raise OCRFailure("ocr_timeout", retryable=True) from exc
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise OCRFailure("ocr_engine_unavailable") from exc
    return completed.stdout.decode("utf-8", errors="replace").strip()


def _extract_pdf(path, workspace):
    texts, methods = [], []
    total = 0
    try:
        pdf = pdfium.PdfDocument(path)
        try:
            if not 0 < len(pdf) <= settings.MAX_OCR_PAGES:
                raise OCRFailure("page_limit")
            for page_index in range(len(pdf)):
                page = pdf[page_index]
                try:
                    text_page = page.get_textpage()
                    try:
                        remaining = settings.MAX_OCR_CHARS - total
                        if text_page.count_chars() > remaining:
                            raise OCRFailure("text_limit")
                        text = text_page.get_text_range().strip()
                    finally:
                        text_page.close()
                    if text:
                        method = "text_layer"
                    else:
                        scale = 2.5
                        _check_pixels(
                            int(page.get_width() * scale) + 1, int(page.get_height() * scale) + 1
                        )
                        bitmap = page.render(scale=scale)
                        try:
                            image = bitmap.to_pil()
                            try:
                                text = _ocr_image(image, workspace)
                            finally:
                                image.close()
                        finally:
                            bitmap.close()
                        method = "tesseract"
                    texts.append(text)
                    methods.append(method)
                    total += len(text) + 2
                    if total > settings.MAX_OCR_CHARS:
                        raise OCRFailure("text_limit")
                finally:
                    page.close()
        finally:
            pdf.close()
    except pdfium.PdfiumError as exc:
        raise OCRFailure("invalid_document") from exc
    return "\n\n".join(texts), methods


def extract(path, mime_type, workspace):
    if mime_type == "application/pdf":
        text, methods = _extract_pdf(path, workspace)
    else:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path) as source:
                    _check_pixels(*source.size)
                    if source.format not in {"JPEG", "PNG"}:
                        raise OCRFailure("invalid_document")
                    source.load()
                    image = ImageOps.exif_transpose(source).convert("RGB")
                    try:
                        text = _ocr_image(image, workspace)
                    finally:
                        image.close()
            methods = ["tesseract"]
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise OCRFailure("pixel_limit") from exc
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise OCRFailure("invalid_document") from exc
    if len(text) > settings.MAX_OCR_CHARS:
        raise OCRFailure("text_limit")
    # PostgreSQL text cannot contain NUL. Text is returned as plain JSON, never HTML.
    text = text.replace("\x00", "")
    return ExtractionResult(
        text,
        {
            "engine": "pdfium+tesseract",
            "languages": settings.OCR_LANGUAGES,
            "pages": len(methods),
            "page_methods": methods,
            "warnings": [] if text.strip() else ["No readable text was detected."],
        },
    )
