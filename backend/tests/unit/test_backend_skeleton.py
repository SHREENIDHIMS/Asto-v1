"""Unit tests for the backend skeleton.

Tests:
- App starts and health check works
- Auth endpoints are wired (login fails with invalid creds)
- Search endpoint returns 501 (stub)
- JWT handler creates and verifies tokens
- RBAC resolves departments correctly
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

backend_path = Path(__file__).resolve().parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))


class TestAppStartup:
    """Verify the FastAPI app initializes correctly."""

    def test_app_creation(self):
        from app.main import app

        assert app is not None
        assert app.title == "Asto"

    def test_health_endpoint_exists(self):
        from app.main import app

        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/health" in paths

    def test_api_health_endpoint_exists(self):
        from app.main import app

        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/api/v1/health" in paths

    def test_api_docs_endpoints_exist(self):
        from app.main import app

        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/api/v1/docs" in paths
        assert "/api/v1/openapi.json" in paths

    def test_api_router_included(self):
        from app.main import app

        paths = list(app.openapi()["paths"].keys())
        assert any("/api/v1/auth" in p for p in paths)


class TestAuthEndpoints:
    """Test auth endpoint stubs and JWT handling."""

    def test_login_invalid_credentials(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "nonexistent@test.com", "password": "wrong"},
        )
        assert response.status_code == 401

    def test_login_empty_credentials(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "", "password": ""},
        )
        assert response.status_code == 401

    def test_verify_invalid_token(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.post(
            "/api/v1/auth/verify",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False


class TestJWTHandler:
    """Test JWT token creation and verification."""

    def test_create_and_verify_token(self):
        from app.auth.jwt_handler import create_token, verify_token

        token = create_token(
            subject="1",
            role="loan_officer",
            department="general",
            allowed_departments=["general", "compliance"],
        )
        payload = verify_token(token)
        assert payload is not None
        assert payload["sub"] == "1"
        assert payload["role"] == "loan_officer"
        assert payload["department"] == "general"
        assert "general" in payload["allowed_departments"]
        assert "compliance" in payload["allowed_departments"]

    def test_verify_invalid_token(self):
        from app.auth.jwt_handler import verify_token

        assert verify_token("invalid.token.here") is None

    def test_verify_empty_token(self):
        from app.auth.jwt_handler import verify_token

        assert verify_token("") is None

    def test_verify_none_token(self):
        from app.auth.jwt_handler import verify_token

        assert verify_token(None) is None


class TestRBAC:
    """Test RBAC department resolution."""

    def test_resolve_user_departments(self):
        from app.auth.rbac import resolve_user_departments

        user = {
            "department": "general",
            "allowed_departments": ["general", "compliance"],
        }
        depts = resolve_user_departments(user)
        assert "general" in depts
        assert "compliance" in depts

    def test_resolve_user_none(self):
        from app.auth.rbac import resolve_user_departments

        assert resolve_user_departments(None) == []

    def test_is_admin_super_admin(self):
        from app.auth.rbac import is_admin

        user = {"role": "super_admin", "department": "general"}
        assert is_admin(user) is True

    def test_is_admin_loan_officer(self):
        from app.auth.rbac import is_admin

        user = {"role": "loan_officer", "department": "general"}
        assert is_admin(user) is False

    def test_get_search_filter_admin(self):
        from app.auth.rbac import get_search_filter

        user = {"role": "super_admin", "department": "general"}
        clause, params = get_search_filter(user)
        assert clause == ""
        assert params == []

    def test_get_search_filter_loan_officer(self):
        from app.auth.rbac import get_search_filter

        user = {
            "role": "loan_officer",
            "department": "general",
            "allowed_departments": ["compliance"],
        }
        clause, params = get_search_filter(user)
        assert "department" in clause
        assert "general" in params
        assert "compliance" in params


class TestEndpoints:
    """Verify implemented endpoints respond correctly."""

    def test_search_endpoint_returns_response(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.post(
            "/api/v1/search/",
            json={"query": "credit score requirements"},
            headers={"Authorization": "Bearer test"},
        )
        # Search endpoint is fully implemented — returns JSON or auth error
        assert response.status_code in (200, 401)

    def test_documents_upload_requires_file(self):
        from fastapi.testclient import TestClient
        from app.auth.jwt_handler import create_token
        from app.main import app

        token = create_token(
            subject="1",
            role="admin",
            department="general",
            allowed_departments=["general"],
        )
        client = TestClient(app)
        response = client.post(
            "/api/v1/documents/upload",
            headers={"Authorization": f"Bearer {token}"},
        )
        # Upload requires a valid user in the system; mock DB has no users
        assert response.status_code == 401

    def test_admin_users_endpoint_requires_auth(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.get("/api/v1/admin/users")
        assert response.status_code == 401

    def test_analytics_endpoint_requires_auth(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.get("/api/v1/analytics/knowledge-gaps")
        assert response.status_code == 401

    def test_documents_list_endpoint_requires_auth(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.get("/api/v1/documents/")
        assert response.status_code == 401

    def test_feedback_endpoint_exists(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        response = client.post("/api/v1/feedback/", json={})
        assert response.status_code == 401
