"""Unit tests for the admin dashboard summary endpoint (Phase F2).

Covers: route wiring, auth requirement, admin-only gating (client tokens
denied), and the aggregate counts returned by ``/admin/summary``.
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


class TestAdminSummaryRoutes:
    def test_route_exists(self):
        from app.main import app
        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/admin/summary" in paths

    def test_summary_requires_auth(self):
        from app.main import app
        response = TestClient(app).get("/api/v1/admin/summary")
        assert response.status_code == 401

    def test_summary_denies_client(self):
        try:
            response = _authorized(CLIENT_USER).get("/api/v1/admin/summary")
            assert response.status_code == 403
        finally:
            _teardown()


class TestAdminSummaryPayload:
    def test_summary_returns_all_counts(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"n": 3},  # pending approvals
            {"n": 1},  # stale pending approvals
            {"n": 10},  # documents
            {"n": 4},  # users
            {"n": 2},  # clients
            {"n": 5},  # active cases
            {"n": 7},  # knowledge gaps
            {"n": 1},  # pending sop requests
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get("/api/v1/admin/summary")
            finally:
                _teardown()

        assert response.status_code == 200
        data = response.json()
        assert data["pending_approvals"] == 3
        assert data["stale_pending_approvals"] == 1
        assert data["total_documents"] == 10
        assert data["total_users"] == 4
        assert data["total_clients"] == 2
        assert data["active_cases"] == 5
        assert data["total_gaps"] == 7
        assert data["pending_sop_requests"] == 1

    def test_summary_defaults_zero_on_null_counts(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"n": None}
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get("/api/v1/admin/summary")
            finally:
                _teardown()

        assert response.status_code == 200
        data = response.json()
        for key in (
            "pending_approvals",
            "stale_pending_approvals",
            "total_documents",
            "total_users",
            "total_clients",
            "active_cases",
            "total_gaps",
            "pending_sop_requests",
        ):
            assert data[key] == 0
