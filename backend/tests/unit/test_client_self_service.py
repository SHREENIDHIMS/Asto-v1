"""Unit tests for client self-service endpoints (Phase 6.5 extension).

Covers: client upload route wiring, staff-token denial, sidecar creation
with client_id/property_id, property ownership checks, and the
ingest_batch sidecar reader.
"""

from __future__ import annotations

import json
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


class TestClientUploadRouteWiring:
    def test_routes_exist(self):
        from app.main import app
        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/client/documents/upload" in paths
        assert "/api/v1/client/properties/{property_id}/documents" in paths

    def test_upload_requires_auth(self):
        from app.main import app
        client = TestClient(app)
        response = client.post("/api/v1/client/documents/upload")
        assert response.status_code == 401

    def test_upload_denies_staff_tokens(self):
        from app.main import app
        from app.dependencies import require_auth
        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            client = TestClient(app)
            response = client.post(
                "/api/v1/client/documents/upload",
                files={"file": ("policy.txt", b"hello", "text/plain")},
            )
            assert response.status_code == 403
        finally:
            app.dependency_overrides.pop(require_auth, None)

    def test_property_documents_denies_staff_tokens(self):
        from app.main import app
        from app.dependencies import require_auth
        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            client = TestClient(app)
            response = client.get("/api/v1/client/properties/1/documents")
            assert response.status_code == 403
        finally:
            app.dependency_overrides.pop(require_auth, None)


class TestClientUploadBehavior:
    @pytest.fixture
    def pending_dir(self, tmp_path):
        from app.config import settings
        original = settings.storage_pending_dir
        settings.storage_pending_dir = str(tmp_path)
        yield tmp_path
        settings.storage_pending_dir = original

    def _post_upload(self, client_id=7, property_id=None, filename="policy.txt"):
        from app.main import app
        from app.dependencies import require_auth
        app.dependency_overrides[require_auth] = lambda: {
            **CLIENT_USER, "client_id": client_id,
        }
        try:
            client = TestClient(app)
            files = {"file": (filename, b"client policy content", "text/plain")}
            params = {}
            if property_id is not None:
                params["property_id"] = str(property_id)
            return client.post(
                "/api/v1/client/documents/upload",
                files=files,
                params=params,
            )
        finally:
            app.dependency_overrides.pop(require_auth, None)

    def test_upload_writes_file_and_sidecar(self, pending_dir):
        response = self._post_upload(filename="statement.pdf")
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "statement.pdf"
        assert data["property_id"] is None

        files = list(pending_dir.iterdir())
        assert len(files) == 2
        meta = [f for f in files if f.name.endswith(".meta.json")]
        assert len(meta) == 1
        payload = json.loads(meta[0].read_text(encoding="utf-8"))
        assert payload == {"client_id": 7, "property_id": None}

    def test_upload_rejects_missing_filename(self, pending_dir):
        from app.main import app
        from app.dependencies import require_auth
        app.dependency_overrides[require_auth] = lambda: CLIENT_USER
        try:
            client = TestClient(app)
            response = client.post(
                "/api/v1/client/documents/upload",
                files={"file": ("", b"", "text/plain")},
            )
            # Framework may reject the empty filename at parse time (422)
            # or our endpoint rejects it (400) — either is correct.
            assert response.status_code in (400, 422)
        finally:
            app.dependency_overrides.pop(require_auth, None)

    def test_upload_property_ownership_enforced(self, pending_dir):
        # The client does NOT own property 999 → 404, nothing written.
        cur = MagicMock()
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        cur.fetchone.return_value = None
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur
        with patch("app.api.v1.client.acquire", return_value=conn):
            response = self._post_upload(property_id=999)
        assert response.status_code == 404
        assert list(pending_dir.iterdir()) == []

    def test_upload_property_owned_writes_sidecar(self, pending_dir):
        cur = MagicMock()
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        cur.fetchone.return_value = {"id": 3}
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur
        with patch("app.api.v1.client.acquire", return_value=conn):
            response = self._post_upload(property_id=3)
        assert response.status_code == 200
        assert response.json()["property_id"] == 3
        meta = [f for f in pending_dir.iterdir() if f.name.endswith(".meta.json")]
        payload = json.loads(meta[0].read_text(encoding="utf-8"))
        assert payload == {"client_id": 7, "property_id": 3}


class TestIngestBatchSidecar:
    def test_load_sidecar_returns_metadata(self, tmp_path):
        from app.documents.ingest_batch import _load_sidecar
        token = "abcd1234"
        (tmp_path / f"{token}.meta.json").write_text(
            json.dumps({"client_id": 7, "property_id": 3}), encoding="utf-8"
        )
        file_path = tmp_path / f"{token}_statement.pdf"
        file_path.write_text("x")
        assert _load_sidecar(file_path) == {"client_id": 7, "property_id": 3}

    def test_load_sidecar_missing_returns_empty(self, tmp_path):
        from app.documents.ingest_batch import _load_sidecar
        file_path = tmp_path / "no_sidecar.pdf"
        file_path.write_text("x")
        assert _load_sidecar(file_path) == {}

    def test_load_sidecar_bad_json_returns_empty(self, tmp_path):
        from app.documents.ingest_batch import _load_sidecar
        token = "token1"
        (tmp_path / f"{token}.meta.json").write_text("{not json", encoding="utf-8")
        file_path = tmp_path / f"{token}_doc.pdf"
        file_path.write_text("x")
        assert _load_sidecar(file_path) == {}
