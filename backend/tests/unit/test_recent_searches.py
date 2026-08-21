"""Unit tests for GET /staff/recent-searches (own query history from audit_log)."""

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


class TestRecentSearches:
    def test_requires_auth(self):
        from app.main import app

        client = TestClient(app)
        response = client.get("/api/v1/staff/recent-searches")
        assert response.status_code == 401

    def test_client_token_denied(self):
        try:
            response = _authorized(CLIENT_USER).get("/api/v1/staff/recent-searches")
            assert response.status_code == 403
        finally:
            _cleanup()

    def test_lists_own_history_scoped_by_user(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchall.return_value = [
            {"query": "what is an APR", "last_run": None, "times": 3},
            {"query": "escrow requirements", "last_run": None, "times": 1},
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).get(
                    "/api/v1/staff/recent-searches"
                )
            finally:
                _cleanup()
        assert response.status_code == 200
        data = response.json()
        assert [r["query"] for r in data["recent_searches"]] == [
            "what is an APR",
            "escrow requirements",
        ]
        assert data["recent_searches"][0]["times_run"] == 3
        # Scoping must be in the SQL WHERE clause (rule #1).
        sql = cur.execute.call_args.args[0]
        assert "user_id = %s" in sql
        assert "GROUP BY query" in sql

    def test_limit_param_forwarded(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchall.return_value = []
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).get(
                    "/api/v1/staff/recent-searches?limit=5"
                )
            finally:
                _cleanup()
        assert response.status_code == 200
        params = cur.execute.call_args.args[1]
        assert params[1] == 5

    def test_limit_rejected_above_max(self):
        try:
            response = _authorized(STAFF_USER).get(
                "/api/v1/staff/recent-searches?limit=500"
            )
            assert response.status_code == 422
        finally:
            _cleanup()
