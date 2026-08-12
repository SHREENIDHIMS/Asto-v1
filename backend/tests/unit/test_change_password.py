"""Unit tests for POST /api/v1/auth/change-password.

Covers: auth requirement, staff vs client identity-table resolution,
current-password verification, account-not-found handling, password
strength validation, and the no-write guarantee on failed verification.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from passlib.hash import bcrypt

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

CURRENT_PW = "old-secret-123"
NEW_PW = "new-secret-456"


def _conn_with_hash(password_hash: str | None) -> MagicMock:
    """Return a magic connection whose first cursor yields the given hash."""
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cur = conn.cursor.return_value
    cur.__enter__.return_value = cur
    cur.fetchone.return_value = (
        {"password_hash": password_hash} if password_hash is not None else None
    )
    return conn


def _call(client: TestClient, body: dict | None = None) -> object:
    return client.post(
        "/api/v1/auth/change-password",
        json=body if body is not None else {
            "current_password": CURRENT_PW,
            "new_password": NEW_PW,
        },
    )


class TestChangePasswordRoute:
    def test_route_exists(self):
        from app.main import app
        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/auth/change-password" in paths

    def test_requires_auth(self):
        from app.main import app
        client = TestClient(app)
        response = _call(client)
        assert response.status_code == 401


@pytest.fixture
def authorized_client():
    """Yield a factory returning a TestClient with the given identity.

    Always removes the ``require_auth`` override on teardown so it cannot
    leak into other test modules (which would silently weaken their auth
    assertions).
    """
    from app.main import app
    from app.dependencies import require_auth

    def _factory(user: dict) -> TestClient:
        app.dependency_overrides[require_auth] = lambda: user
        return TestClient(app)

    yield _factory
    app.dependency_overrides.pop(require_auth, None)


class TestChangePasswordBehavior:
    def test_staff_changes_password(self, authorized_client):
        conn = _conn_with_hash(bcrypt.hash(CURRENT_PW))
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _call(authorized_client(STAFF_USER))
        assert response.status_code == 200
        assert response.json() == {"updated": True}
        calls = conn.cursor.return_value.execute.call_args_list
        assert "FROM users" in calls[0].args[0]
        assert "UPDATE users SET password_hash" in calls[1].args[0]
        new_hash = calls[1].args[1][0]
        assert bcrypt.verify(NEW_PW, new_hash)
        assert calls[1].args[1][1] == STAFF_USER["id"]
        assert "UPDATE refresh_tokens" in calls[2].args[0]
        assert "user_id" in calls[2].args[0]
        assert calls[2].args[1][0] == STAFF_USER["id"]
        conn.commit.assert_called_once()
        conn.cursor.return_value.close.assert_called_once()

    def test_client_resolves_clients_table(self, authorized_client):
        conn = _conn_with_hash(bcrypt.hash(CURRENT_PW))
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _call(authorized_client(CLIENT_USER))
        assert response.status_code == 200
        calls = conn.cursor.return_value.execute.call_args_list
        assert "FROM clients" in calls[0].args[0]
        assert "UPDATE clients SET password_hash" in calls[1].args[0]
        assert "UPDATE refresh_tokens" in calls[2].args[0]
        assert "client_id" in calls[2].args[0]
        assert "'client'" in calls[2].args[0]
        assert calls[2].args[1][0] == CLIENT_USER["id"]
        conn.commit.assert_called_once()

    def test_unknown_audience_defaults_to_users(self, authorized_client):
        user = {**STAFF_USER, "audience": "mystery"}
        conn = _conn_with_hash(bcrypt.hash(CURRENT_PW))
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _call(authorized_client(user))
        assert response.status_code == 200
        assert "FROM users" in conn.cursor.return_value.execute.call_args_list[0].args[0]

    def test_wrong_current_password_returns_401_and_no_write(self, authorized_client):
        conn = _conn_with_hash(bcrypt.hash("different-pass-999"))
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _call(authorized_client(STAFF_USER))
        assert response.status_code == 401
        assert response.json()["detail"] == "Current password is incorrect"
        conn.commit.assert_not_called()

    def test_account_not_found_returns_404(self, authorized_client):
        conn = _conn_with_hash(None)
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _call(authorized_client(STAFF_USER))
        assert response.status_code == 404
        assert response.json()["detail"] == "Account not found"
        conn.commit.assert_not_called()

    def test_short_new_password_rejected(self, authorized_client):
        response = _call(
            authorized_client(STAFF_USER),
            body={"current_password": CURRENT_PW, "new_password": "short"},
        )
        assert response.status_code == 422
