"""Unit tests for Phase F3 admin governance endpoints.

Covers: Knowledge Base chunk browse, admin read-all SOPs, and the
config-driven roles/departments governance view. Includes route wiring,
auth requirements, client denial, and payload shapes.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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

ADMIN_USER = {
    "id": 1,
    "email": "admin@asto.local",
    "full_name": "Admin User",
    "is_active": True,
    "audience": "staff",
    "role": "admin",
    "department": "general",
    "allowed_departments": ["general", "compliance"],
}


def _authorized(user: dict):
    from app.main import app
    from app.dependencies import require_auth
    app.dependency_overrides[require_auth] = lambda: user
    return TestClient(app)


def _conn() -> MagicMock:
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cur = conn.cursor.return_value
    cur.__enter__.return_value = cur
    return conn


def _teardown():
    from app.main import app
    from app.dependencies import require_auth
    app.dependency_overrides.pop(require_auth, None)


class TestAdminGovernanceRoutes:
    def test_routes_exist(self):
        from app.main import app
        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/admin/documents/{document_id}/chunks" in paths
        assert "/api/v1/admin/sops" in paths
        assert "/api/v1/admin/governance" in paths

    def test_chunks_requires_auth(self):
        from app.main import app
        assert TestClient(app).get("/api/v1/admin/documents/1/chunks").status_code == 401

    def test_sops_requires_auth(self):
        from app.main import app
        assert TestClient(app).get("/api/v1/admin/sops").status_code == 401

    def test_governance_requires_auth(self):
        from app.main import app
        assert TestClient(app).get("/api/v1/admin/governance").status_code == 401

    def test_chunks_denies_client(self):
        try:
            assert (
                _authorized(CLIENT_USER).get("/api/v1/admin/documents/1/chunks").status_code
                == 403
            )
        finally:
            _teardown()


class TestDocumentChunks:
    def test_chunks_returns_document_chunks(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [{"id": 5}]  # doc exists
        cur.fetchall.return_value = [
            {
                "id": 11,
                "section": "credit score requirements",
                "chunk_type": "paragraph",
                "department": "general",
                "content": "A minimum score of 620.",
                "approval_status": "approved",
                "is_approved": True,
                "created_at": None,
            }
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get(
                    "/api/v1/admin/documents/5/chunks"
                )
            finally:
                _teardown()

        assert response.status_code == 200
        data = response.json()
        assert data["document_id"] == 5
        assert data["chunks"][0]["content"] == "A minimum score of 620."
        assert data["chunks"][0]["is_approved"] is True

    def test_chunks_404_when_document_missing(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = None
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get(
                    "/api/v1/admin/documents/999/chunks"
                )
            finally:
                _teardown()

        assert response.status_code == 404


class TestAdminSops:
    def test_sops_returns_all(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchall.return_value = [
            {
                "id": 1,
                "title": "Intake SOP",
                "department": "general",
                "body": "Steps",
                "version": 1,
                "created_by": 1,
                "updated_at": None,
                "is_active": True,
            }
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get("/api/v1/admin/sops")
            finally:
                _teardown()

        assert response.status_code == 200
        data = response.json()
        assert data["sops"][0]["title"] == "Intake SOP"
        assert data["sops"][0]["department"] == "general"
        sql = cur.execute.call_args.args[0]
        assert "is_active = true" in sql


class TestGovernance:
    def test_governance_returns_config(self):
        with patch("app.db.postgres.session.acquire") as _mock:
            try:
                response = _authorized(ADMIN_USER).get("/api/v1/admin/governance")
            finally:
                _teardown()

        assert response.status_code == 200
        data = response.json()
        assert data["roles"]
        assert data["departments"]
        assert data["role_hierarchy"]
        names = {r["name"] for r in data["roles"]}
        assert "admin" in names
        assert "loan_officer" in names
