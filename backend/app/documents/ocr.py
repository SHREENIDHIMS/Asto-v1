"""OCR for scanned PDFs using Tesseract.

Optional dependency — only used when pdfplumber cannot extract
text (e.g. scanned image PDFs). Falls back gracefully if
Tesseract is not installed.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import pytesseract
    from PIL import Image

    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False
    logger.warning("pytesseract/Pillow not installed; OCR disabled")


def extract_text_from_image(image_path: str | Path) -> str:
    """Run OCR on a single image file and return the extracted text."""
    if not HAS_TESSERACT:
        raise RuntimeError("pytesseract and Pillow are required for OCR")
    img = Image.open(str(image_path))
    text = pytesseract.image_to_string(img)
    return text


def ocr_pdf_pages(pdf_path: str | Path) -> list[str]:
    """Extract text from each page of a PDF using OCR.

    Returns one string per page. Use this when pdfplumber returns
    empty or low-quality text (scanned PDFs).
    """
    if not HAS_TESSERACT:
        raise RuntimeError("pytesseract and Pillow are required for OCR")

    import pdf2image  # type: ignore

    pages = pdf2image.convert_from_path(str(pdf_path))
    texts: list[str] = []
    for page in pages:
        text = pytesseract.image_to_string(page)
        texts.append(text)
    return texts