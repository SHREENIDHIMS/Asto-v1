"""Unit tests for self-service session management (/auth/sessions)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

STAFF_USER = {
    "id": 2,
    "email": "staff@asto.local",
    "full_name": "Dana Officer",
    "is_active": True,
    "audience": "staff",
    "role": "loan_officer",
    "department": "general",
    "allowed_departments": ["general"],
}

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


def _conn() -> MagicMock:
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cur = conn.cursor.return_value
    cur.__enter__.return_value = cur
    return conn


def _authorized(user: dict):
    from app.main import app
    from app.dependencies import require_auth

    app.dependency_overrides[require_auth] = lambda: user
    return TestClient(app)


def _cleanup() -> None:
    from app.main import app
    from app.dependencies import require_auth

    app.dependency_overrides.pop(require_auth, None)


class TestListMySessions:
    def test_requires_auth(self):
        from app.main import app

        response = TestClient(app).get("/api/v1/auth/sessions")
        assert response.status_code == 401

    def test_staff_scoped_by_user_id(self):
        conn = _conn()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [
            {"id": 1, "audience": "staff", "created_at": None, "expires_at": None}
        ]
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = _authorized(STAFF_USER).get("/api/v1/auth/sessions")
            assert response.status_code == 200
            data = response.json()
            assert data["active_sessions"] == 1
            sql, params = cur.execute.call_args.args
            assert "user_id = %s" in sql
            assert params[0] == 2
            assert "revoked_at IS NULL" in sql and "expires_at > now()" in sql
        finally:
            _cleanup()

    def test_client_scoped_by_client_id(self):
        conn = _conn()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = []
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = _authorized(CLIENT_USER).get("/api/v1/auth/sessions")
            assert response.status_code == 200
            sql, params = cur.execute.call_args.args
            assert "client_id = %s" in sql
            assert params[0] == 7
            assert "user_id = %s" not in sql.replace("client_id = %s", "")
        finally:
            _cleanup()


class TestRevokeMySession:
    def test_scoped_to_own_identity(self):
        conn = _conn()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.rowcount = 1
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = _authorized(CLIENT_USER).post(
                    "/api/v1/auth/sessions/5/revoke"
                )
            assert response.status_code == 200
            sql, params = cur.execute.call_args.args
            # Both the id and the client scoping must be in the WHERE clause.
            assert "id = %s" in sql and "client_id = %s" in sql
            assert params == (5, 7)
        finally:
            _cleanup()

    def test_foreign_session_is_404_not_leak(self):
        conn = _conn()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.rowcount = 0  # no own row matched → someone else's or gone
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = _authorized(STAFF_USER).post(
                    "/api/v1/auth/sessions/999/revoke"
                )
            assert response.status_code == 404
        finally:
            _cleanup()

    def test_requires_auth(self):
        from app.main import app

        response = TestClient(app).post("/api/v1/auth/sessions/5/revoke")
        assert response.status_code == 401
