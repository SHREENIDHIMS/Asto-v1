"""Unit tests for audit fix 2.7 — OCR renders one page at a time.

``ocr_pdf_pages`` previously called ``pdf2image.convert_from_path`` once,
materialising every page image in RAM at once (OOM under the ~200MB batch
worker cap). After the fix it asks pdfinfo for the page count and renders
a single page per convert call, OCR-ing it immediately.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import sys

import pytest

from app.documents.ocr import ocr_pdf_pages


@pytest.fixture
def fake_pdf2image():
    mod = MagicMock()
    mod.pdfinfo_from_path.return_value = {"Pages": 3}
    mod.convert_from_path.return_value = [MagicMock()]
    with patch.dict(sys.modules, {"pdf2image": mod}):
        yield mod


class TestOcrPageAtATime:
    def test_renders_and_ocrs_one_page_per_convert(self, fake_pdf2image):
        ocr = patch(
            "app.documents.ocr.pytesseract.image_to_string",
            side_effect=["page one", "page two", "page three"],
        )
        with ocr as image_to_string:
            texts = ocr_pdf_pages("scan.pdf")

        assert texts == ["page one", "page two", "page three"]
        calls = fake_pdf2image.convert_from_path.call_args_list
        assert len(calls) == 3
        for i, call in enumerate(calls, start=1):
            assert call.kwargs["first_page"] == i
            assert call.kwargs["last_page"] == i
        assert image_to_string.call_count == 3

    def test_page_count_comes_from_pdfinfo(self, fake_pdf2image):
        fake_pdf2image.pdfinfo_from_path.return_value = {"Pages": 1}
        with patch(
            "app.documents.ocr.pytesseract.image_to_string",
            return_value="single page",
        ):
            texts = ocr_pdf_pages("one.pdf")
        assert texts == ["single page"]
        fake_pdf2image.pdfinfo_from_path.assert_called_once_with("one.pdf")
        assert fake_pdf2image.convert_from_path.call_count == 1

    def test_zero_pages_returns_empty_without_rendering(self, fake_pdf2image):
        fake_pdf2image.pdfinfo_from_path.return_value = {"Pages": 0}
        with patch("app.documents.ocr.pytesseract.image_to_string"):
            assert ocr_pdf_pages("empty.pdf") == []
        fake_pdf2image.convert_from_path.assert_not_called()