"""Unit tests for the client-facing watermark module (Phase I5).

Verifies: PDF bytes are modified and contain the viewer identity text,
image bytes are modified, unsupported types pass through unchanged, and the
watermark string embeds viewer name and date.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.documents.pii_check import has_pii, scan_for_pii
from app.documents.watermark import watermark_bytes, watermark_text


def _tiny_pdf() -> bytes:
    """Minimal valid single-page PDF (reportlab-free so this test doesn't
    depend on reportlab/pypdf to *produce* the fixture)."""
    return b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>
endobj
xref
0 4
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
trailer
<< /Size 4 /Root 1 0 R >>
startxref
190
%%EOF
"""


def _tiny_png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=(255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


class TestWatermarkText:
    def test_embeds_viewer_and_date(self):
        text = watermark_text("Jane Doe", now=None)
        assert text.startswith("Viewed by Jane Doe on ")
        assert len(text.split("on ")[-1]) == 10  # YYYY-MM-DD


class TestWatermarkPdf:
    def test_pdf_bytes_differ_and_contain_viewer(self):
        raw = _tiny_pdf()
        out = watermark_bytes(raw, "doc.pdf", "Jane Doe")
        assert out != raw
        assert b"Viewed by Jane Doe" in out


class TestWatermarkImage:
    def test_image_bytes_differ(self):
        raw = _tiny_png()
        out = watermark_bytes(raw, "doc.png", "Jane Doe")
        assert out != raw


class TestWatermarkPassthrough:
    def test_unknown_extension_unchanged(self):
        raw = b"some plain text file"
        assert watermark_bytes(raw, "notes.txt", "Jane Doe") == raw

    def test_empty_extension_unchanged(self):
        raw = b"whatever"
        assert watermark_bytes(raw, "", "Jane Doe") == raw


class TestClientFileWatermarkEndpoint:
    """The client file endpoint must serve watermarked bytes; the admin
    endpoint must serve the raw file untouched."""

    def _make_pdf_on_disk(self) -> Path:
        from app.config import settings

        name = f"{uuid.uuid4().hex}.pdf"
        path = Path(settings.storage_pending_dir) / name
        path.write_bytes(_tiny_pdf())
        return path

    def _client_user(self) -> dict:
        return {
            "id": 7,
            "email": "client@asto.local",
            "full_name": "Jane Doe",
            "is_active": True,
            "audience": "client",
            "client_id": 7,
            "role": "client",
            "department": None,
            "allowed_departments": [],
        }

    def test_client_file_is_watermarked(self):
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        path = self._make_pdf_on_disk()
        try:
            conn = MagicMock()
            conn.__enter__.return_value = conn
            cur = conn.cursor.return_value
            cur.__enter__.return_value = cur
            cur.fetchone.return_value = {
                "source_path": str(path),
                "title": "Watermark Test",
            }

            app.dependency_overrides[require_auth] = lambda: self._client_user()
            try:
                with patch("app.db.postgres.session.acquire", return_value=conn):
                    client = TestClient(app)
                    response = client.get("/api/v1/client/documents/7/file")
            finally:
                app.dependency_overrides.clear()

            assert response.status_code == 200
            assert response.content != path.read_bytes()
            assert b"Viewed by Jane Doe" in response.content
        finally:
            path.unlink(missing_ok=True)

    def test_admin_file_is_not_watermarked(self):
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        path = self._make_pdf_on_disk()
        staff_user = {
            "id": 1,
            "email": "admin@asto.local",
            "full_name": "Admin User",
            "is_active": True,
            "audience": "staff",
            "role": "admin",
            "department": "general",
            "allowed_departments": ["general"],
        }
        try:
            conn = MagicMock()
            conn.__enter__.return_value = conn
            cur = conn.cursor.return_value
            cur.__enter__.return_value = cur
            cur.fetchone.return_value = {
                "source_path": str(path),
                "title": "Watermark Test",
            }

            app.dependency_overrides[require_auth] = lambda: staff_user
            try:
                with patch("app.db.postgres.session.acquire", return_value=conn):
                    client = TestClient(app)
                    response = client.get("/api/v1/documents/7/file")
            finally:
                app.dependency_overrides.clear()

            assert response.status_code == 200
            assert response.content == path.read_bytes()
        finally:
            path.unlink(missing_ok=True)


class TestPiiScanner:
    def test_finds_ssn(self):
        assert has_pii("My SSN is 123-45-6789 today")
        matches = scan_for_pii("SSN: 123-45-6789")
        assert any(m.kind == "ssn" for m in matches)

    def test_finds_email(self):
        assert has_pii("Reach me at jane@example.com")
        assert any(m.kind == "email" for m in scan_for_pii("jane@example.com"))

    def test_finds_dob(self):
        assert has_pii("DOB: 01/15/1985")
        assert any(m.kind == "dob" for m in scan_for_pii("01/15/1985"))

    def test_no_pii(self):
        assert not has_pii("This document is about loan policies and procedures.")
        assert scan_for_pii("just some words") == []
