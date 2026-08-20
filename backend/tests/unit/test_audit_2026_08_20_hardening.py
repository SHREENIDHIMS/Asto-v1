"""Unit tests for the 2026-08-20 security hardening batch (audit S1-S7).

Covers:
- S1: config rejects weak/empty JWT secrets in every environment; TOTP Fernet
      key has no public fallback constant.
- S2: auth._client_ip trusts X-Real-IP over the spoofable X-Forwarded-For
      first hop and falls back to the last XFF hop.
- S3: mailer redacts one-time credentials (reset/token/code) in logged text.
- S4: /suggest and document file-serving are audit-logged.
- S5: an unwatermarked client document is served as an attachment and the
      bypass is audit-logged, not silently served inline.
- S6: upload magic-byte validation rejects content that contradicts the
      declared extension.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

CLIENT_USER = {
    "id": 7,
    "email": "client@asto.local",
    "full_name": "Client User",
    "is_active": True,
    "audience": "client",
    "client_id": 7,
    "role": "client",
    "department": None,
    "allowed_departments": [],
}

STAFF_USER = {
    "id": 1,
    "email": "admin@asto.local",
    "full_name": "Admin User",
    "is_active": True,
    "audience": "staff",
    "role": "admin",
    "department": "general",
    "allowed_departments": ["general"],
}


# --- S1: config + TOTP ------------------------------------------------


class TestJwtSecretEnforcement:
    def test_short_secret_rejected_even_in_development(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="ASTO_JWT_SECRET"):
            Settings(_env_file=None, jwt_secret="short", environment="development")

    def test_short_secret_rejected_in_production(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="ASTO_JWT_SECRET"):
            Settings(_env_file=None, jwt_secret="", environment="production")

    def test_strong_secret_accepted_in_any_environment(self):
        from app.config import Settings

        s = Settings(_env_file=None, jwt_secret="x" * 40, environment="production")
        assert len(s.jwt_secret) == 40


class TestTotpNoFallback:
    def test_fernet_key_derived_from_secret_not_a_public_constant(self):
        from app.auth import totp

        with patch.object(totp.settings, "jwt_secret", "s" * 40):
            key = totp._fernet_key()
        assert key != b"a" * 32
        # The historical public fallback must never be used.
        assert "asto-dev-2fa-key" not in totp._fernet_key().decode()


# --- S2: client IP trust ----------------------------------------------


def _request(headers: dict) -> "Request":
    from starlette.requests import Request

    scope = {
        "type": "http",
        "headers": [
            (k.lower().encode("utf-8"), v.encode("utf-8"))
            for k, v in headers.items()
        ],
        "client": ("1.2.3.4", 1234),
    }
    return Request(scope)


class TestClientIpTrust:
    def test_x_real_ip_wins_over_spoofed_xff(self):
        from app.api.v1.auth import _client_ip

        ip = _client_ip(_request({
            "X-Real-IP": "203.0.113.9",
            "X-Forwarded-For": "198.51.100.1, 203.0.113.9",
        }))
        assert ip == "203.0.113.9"

    def test_xff_uses_last_hop_not_spoofable_first(self):
        from app.api.v1.auth import _client_ip

        ip = _client_ip(_request({
            "X-Forwarded-For": "198.51.100.1, 203.0.113.9",
        }))
        assert ip == "203.0.113.9"

    def test_falls_back_to_direct_peer(self):
        from app.api.v1.auth import _client_ip

        assert _client_ip(_request({})) == "1.2.3.4"


# --- S3: reset-token redaction ----------------------------------------


class TestMailerRedaction:
    def test_reset_param_value_is_masked(self):
        from app.email.mailer import _redact_text

        out = _redact_text(
            "Use http://localhost:3011/login?reset=ABC123tokenXYZ to reset."
        )
        assert "ABC123tokenXYZ" not in out
        assert "reset=[redacted:" in out

    def test_other_credential_params_are_masked(self):
        from app.email.mailer import _redact_text

        out = _redact_text("code=000000&token=abc&secret=def")
        assert "000000" not in out
        assert "abc" not in out
        assert "def" not in out

    def test_plain_text_is_unchanged(self):
        from app.email.mailer import _redact_text

        assert _redact_text("hello world, no secrets here") == (
            "hello world, no secrets here"
        )


# --- S6: upload magic-byte validation ---------------------------------


class TestContentMagic:
    def test_pdf_header_ok(self):
        from app.documents.validation import validate_content_magic

        assert validate_content_magic("doc.pdf", b"%PDF-1.7 ...") is None

    def test_pdf_mismatch_rejected(self):
        from app.documents.validation import validate_content_magic

        assert validate_content_magic(
            "evil.pdf", b"<html><script>alert(1)</script>"
        ) is not None

    def test_zip_office_ok(self):
        from app.documents.validation import validate_content_magic

        assert validate_content_magic("doc.docx", b"PK\x03\x04rest") is None

    def test_zip_office_mismatch_rejected(self):
        from app.documents.validation import validate_content_magic

        assert validate_content_magic(
            "notes.docx", b"plain text pretending to be docx"
        ) is not None

    def test_plain_text_types_skipped(self):
        from app.documents.validation import validate_content_magic

        assert validate_content_magic("notes.txt", b"anything") is None
        assert validate_content_magic("page.html", b"anything") is None


# --- S4/S5: audit logging on suggest + document serving ---------------


def _conn() -> MagicMock:
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cur = conn.cursor.return_value
    cur.__enter__.return_value = cur
    return conn


class TestSuggestAuditLogged:
    def test_suggest_records_audit_entry(self):
        from app.api.v1 import search
        from app.dependencies import require_auth
        from app.main import app

        conn = _conn()
        with (
            patch("app.api.v1.search.session.acquire", return_value=conn),
            patch("app.api.v1.search.suggest_queries", return_value=["what is apr?"]),
            patch("app.api.v1.search.log_query") as log,
        ):
            app.dependency_overrides[require_auth] = lambda: STAFF_USER
            try:
                response = TestClient(app).get(
                    "/api/v1/search/suggest", params={"q": "what"}
                )
            finally:
                app.dependency_overrides.pop(require_auth, None)

        assert response.status_code == 200
        log.assert_called_once()
        entry = log.call_args.args[0]
        assert entry.outcome == "suggest"
        assert entry.query == "what"
        assert entry.audience == "staff"


class TestDocumentFileAuditLogged:
    def _client(self, tmp_path: Path, content: bytes) -> Path:
        f = tmp_path / "statement.txt"
        f.write_bytes(content)
        return f

    def test_unwatermarked_served_as_attachment_and_logged(self, tmp_path):
        from app.api.v1 import client as client_mod
        from app.dependencies import require_auth
        from app.main import app

        file_path = self._client(tmp_path, b"plain content")
        conn = _conn()
        conn.cursor.return_value.fetchone.return_value = {
            "source_path": "whatever.txt",
            "title": "Statement",
        }
        with (
            patch("app.db.postgres.session.acquire", return_value=conn),
            patch.object(client_mod, "resolve_stored_file", return_value=file_path),
            patch.object(client_mod, "watermark_bytes", side_effect=lambda d, n, v: d),
            patch("app.audit.audit_logger.log_query") as log,
        ):
            app.dependency_overrides[require_auth] = lambda: CLIENT_USER
            try:
                response = TestClient(app).get("/api/v1/client/documents/42/file")
            finally:
                app.dependency_overrides.pop(require_auth, None)

        assert response.status_code == 200
        assert response.headers["content-disposition"].startswith("attachment")
        entry = log.call_args.args[0]
        assert entry.outcome == "document_view_unwatermarked"
        assert entry.retrieved_ids == [42]
        assert entry.audience == "client"

    def test_watermarked_served_inline_and_logged(self, tmp_path):
        from app.api.v1 import client as client_mod
        from app.dependencies import require_auth
        from app.main import app

        file_path = self._client(tmp_path, b"%PDF-1.7 fake")
        conn = _conn()
        conn.cursor.return_value.fetchone.return_value = {
            "source_path": "whatever.pdf",
            "title": "Statement",
        }
        with (
            patch("app.db.postgres.session.acquire", return_value=conn),
            patch.object(client_mod, "resolve_stored_file", return_value=file_path),
            patch.object(
                client_mod,
                "watermark_bytes",
                side_effect=lambda d, n, v: b"WATERMARKED-BYTES",
            ),
            patch("app.audit.audit_logger.log_query") as log,
        ):
            app.dependency_overrides[require_auth] = lambda: CLIENT_USER
            try:
                response = TestClient(app).get("/api/v1/client/documents/42/file")
            finally:
                app.dependency_overrides.pop(require_auth, None)

        assert response.status_code == 200
        assert response.headers["content-disposition"].startswith("inline")
        entry = log.call_args.args[0]
        assert entry.outcome == "document_view"