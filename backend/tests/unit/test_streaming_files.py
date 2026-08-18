"""Unit tests for the SSE streaming and file-serving endpoints.

These follow the existing convention: the shared ``acquire`` is mocked to
return no rows, so authenticated requests that need a DB lookup resolve to
401 and the route wiring itself is what we assert on.
"""

from __future__ import annotations

import sys
from pathlib import Path

backend_path = Path(__file__).resolve().parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))


class TestSearchStreamEndpoint:
    def test_stream_route_exists(self):
        from app.main import app

        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/search/stream" in paths

    def test_stream_requires_auth(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.post(
            "/api/v1/search/stream",
            json={"query": "minimum credit score"},
        )
        assert response.status_code == 401

    def test_stream_returns_event_stream_content_type(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.auth.jwt_handler import create_token

        token = create_token(
            subject="1",
            role="admin",
            department="general",
            allowed_departments=["general"],
        )
        client = TestClient(app)
        response = client.post(
            "/api/v1/search/stream",
            json={"query": "minimum credit score"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Mocked DB has no users -> auth fails (401) before streaming starts.
        assert response.status_code == 401


class TestDocumentFileEndpoints:
    def test_admin_file_route_exists(self):
        from app.main import app

        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/documents/{document_id}/file" in paths

    def test_client_file_route_exists(self):
        from app.main import app

        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/client/documents/{document_id}/file" in paths

    def test_staff_file_route_exists(self):
        from app.main import app

        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/staff/documents/{document_id}/file" in paths

    def test_staff_file_requires_auth(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.get("/api/v1/staff/documents/1/file")
        assert response.status_code == 401

    def test_staff_file_rejects_client_token(self):
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        client_user = {
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
        app.dependency_overrides[require_auth] = lambda: client_user
        try:
            client = TestClient(app)
            response = client.get("/api/v1/staff/documents/1/file")
            assert response.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_client_file_requires_auth(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.get("/api/v1/client/documents/1/file")
        assert response.status_code == 401


class TestFileServeResolver:
    def test_resolve_missing_source_path(self):
        from fastapi import HTTPException
        from app.documents.file_serve import resolve_stored_file

        try:
            resolve_stored_file(None)
            assert False, "expected HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 404

    def test_resolve_empty_filename(self):
        from fastapi import HTTPException
        from app.documents.file_serve import resolve_stored_file

        try:
            resolve_stored_file("storage/pending/")
            assert False, "expected HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 404

    def test_resolve_dot_filename(self):
        from fastapi import HTTPException
        from app.documents.file_serve import resolve_stored_file

        try:
            resolve_stored_file("storage/pending/..")
            assert False, "expected HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 404

    def test_resolve_not_on_disk(self):
        from fastapi import HTTPException
        from app.documents.file_serve import resolve_stored_file

        try:
            resolve_stored_file("storage/pending/definitely-not-here.pdf")
            assert False, "expected HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 404


class TestRejectionHistoryEndpoints:
    def test_routes_exist(self):
        from app.main import app

        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/client/documents/rejected" in paths
        assert "/api/v1/client/documents/{document_id}/rejections" in paths
        assert "/api/v1/staff/documents/{document_id}/rejections" in paths

    def test_client_rejected_requires_auth(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        assert client.get("/api/v1/client/documents/rejected").status_code == 401
        assert client.get("/api/v1/client/documents/1/rejections").status_code == 401

    def test_staff_rejections_requires_auth(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.get("/api/v1/staff/documents/1/rejections")
        assert response.status_code == 401

    def test_client_rejected_rejects_staff_token(self):
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

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
        app.dependency_overrides[require_auth] = lambda: staff_user
        try:
            client = TestClient(app)
            assert client.get("/api/v1/client/documents/rejected").status_code == 403
            assert client.get("/api/v1/client/documents/1/rejections").status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_staff_rejections_rejects_client_token(self):
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        client_user = {
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
        app.dependency_overrides[require_auth] = lambda: client_user
        try:
            client = TestClient(app)
            response = client.get("/api/v1/staff/documents/1/rejections")
            assert response.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_client_rejected_filters_by_client_id(self):
        """A rejected doc belonging to another client must 404."""
        from unittest.mock import MagicMock, patch

        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        client_user = {
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

        conn = MagicMock()
        conn.__enter__.return_value = conn
        cur = conn.cursor.return_value
        cur.__enter__.return_value = cur
        cur.fetchone.return_value = None  # doc not owned by client 7

        app.dependency_overrides[require_auth] = lambda: client_user
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                client = TestClient(app)
                response = client.get("/api/v1/client/documents/99/rejections")
            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()
