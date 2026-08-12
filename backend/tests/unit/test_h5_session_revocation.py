"""Unit tests for Phase H5: session revocation (admin kill + emergency jti).

- Admin can list a staff user's / client's active refresh sessions.
- Admin can revoke all of a user's/client's refresh sessions (kills
  re-auth; already-issued access JWTs stay valid until expiry — the
  documented H5 trade-off).
- ``POST /auth/logout-all`` also records the caller's access-token ``jti``
  in ``revoked_jtis`` so that exact token dies immediately.
- ``POST /auth/verify`` refuses a token whose jti is in ``revoked_jtis``.

All DB access is mocked (unit).
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
    "jti": None,
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
    "jti": None,
}

STAFF_USER = {
    "id": 2,
    "email": "staff@asto.local",
    "full_name": "Dana Officer",
    "is_active": True,
    "audience": "staff",
    "role": "loan_officer",
    "department": "general",
    "allowed_departments": ["general"],
    "jti": "tok-jti-abc",
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


def _executed(conn) -> list[str]:
    return [a.args[0] for a in conn.cursor.return_value.execute.call_args_list]


class TestAdminSessionsRoutes:
    def test_routes_exist(self):
        from app.main import app
        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/admin/users/{user_id}/sessions" in paths
        assert "/api/v1/admin/users/{user_id}/sessions/revoke" in paths
        assert "/api/v1/admin/clients/{client_id}/sessions" in paths
        assert "/api/v1/admin/clients/{client_id}/sessions/revoke" in paths

    def test_user_sessions_requires_auth(self):
        from app.main import app
        assert TestClient(app).get("/api/v1/admin/users/2/sessions").status_code == 401
        assert TestClient(app).post("/api/v1/admin/users/2/sessions/revoke").status_code == 401

    def test_user_sessions_denies_client(self):
        try:
            response = _authorized(CLIENT_USER).get("/api/v1/admin/users/2/sessions")
            assert response.status_code == 403
        finally:
            _teardown()

    def test_revoke_user_sessions_denies_client(self):
        try:
            response = _authorized(CLIENT_USER).post("/api/v1/admin/users/2/sessions/revoke")
            assert response.status_code == 403
        finally:
            _teardown()

    def test_client_sessions_denies_client(self):
        try:
            response = _authorized(CLIENT_USER).get("/api/v1/admin/clients/7/sessions")
            assert response.status_code == 403
        finally:
            _teardown()


class TestUserSessionList:
    def test_lists_active_user_sessions(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"id": 2},  # users existence check
            None,       # no sessions
        ]
        cur.fetchall.return_value = [
            {"id": 11, "audience": "staff", "expires_at": "2026-09-01", "created_at": "2026-08-12"},
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get("/api/v1/admin/users/2/sessions")
            finally:
                _teardown()

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == 2
        assert data["active_sessions"] == 1
        assert data["sessions"][0]["id"] == 11
        calls = _executed(conn)
        select = next(c for c in calls if "FROM refresh_tokens" in c)
        assert "user_id = %s" in select
        assert "revoked_at IS NULL" in select
        assert "expires_at > now()" in select

    def test_user_sessions_404_for_unknown_user(self):
        conn = _conn()
        conn.cursor.return_value.fetchone.return_value = None
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get("/api/v1/admin/users/999/sessions")
            finally:
                _teardown()
        assert response.status_code == 404


class TestUserSessionRevoke:
    def test_revokes_all_user_refresh_rows(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"id": 2},
            {"id": 11},
        ]
        cur.rowcount = 3
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).post("/api/v1/admin/users/2/sessions/revoke")
            finally:
                _teardown()

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == 2
        assert data["revoked_sessions"] == 3
        calls = _executed(conn)
        update = next(c for c in calls if c.startswith("UPDATE refresh_tokens"))
        assert "revoked_at = now()" in update
        assert "user_id = %s" in update
        assert "revoked_at IS NULL" in update

    def test_revoke_user_sessions_404_for_unknown_user(self):
        conn = _conn()
        conn.cursor.return_value.fetchone.return_value = None
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).post("/api/v1/admin/users/999/sessions/revoke")
            finally:
                _teardown()
        assert response.status_code == 404


class TestClientSessionRevoke:
    def test_lists_client_sessions(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [{"id": 7}, None]
        cur.fetchall.return_value = []
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get("/api/v1/admin/clients/7/sessions")
            finally:
                _teardown()
        assert response.status_code == 200
        assert response.json()["client_id"] == 7
        assert response.json()["active_sessions"] == 0
        calls = _executed(conn)
        assert any("client_id = %s" in c and "FROM refresh_tokens" in c for c in calls)

    def test_revokes_client_refresh_rows(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [{"id": 7}, {"id": 12}]
        cur.rowcount = 2
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).post("/api/v1/admin/clients/7/sessions/revoke")
            finally:
                _teardown()
        assert response.status_code == 200
        assert response.json()["revoked_sessions"] == 2
        calls = _executed(conn)
        assert any(
            "client_id = %s" in c and "UPDATE refresh_tokens" in c for c in calls
        )

    def test_revoke_client_sessions_404_for_unknown_client(self):
        conn = _conn()
        conn.cursor.return_value.fetchone.return_value = None
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).post("/api/v1/admin/clients/999/sessions/revoke")
            finally:
                _teardown()
        assert response.status_code == 404


class TestEmergencyJtiRevocation:
    def test_logout_all_records_caller_jti(self):
        conn = _conn()
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).post("/api/v1/auth/logout-all")
            finally:
                _teardown()
        assert response.status_code == 200
        calls = _executed(conn)
        insert = next(c for c in calls if "INSERT INTO revoked_jtis" in c)
        assert "ON CONFLICT (jti) DO NOTHING" in insert
        args = [
            a.args[1] for a in conn.cursor.return_value.execute.call_args_list
            if "INSERT INTO revoked_jtis" in a.args[0]
        ][0]
        assert args[0] == "tok-jti-abc"
        # Refresh rows for the identity are still revoked too.
        assert any("UPDATE refresh_tokens" in c and "user_id = %s" in c for c in calls)

    def test_logout_all_skips_jti_when_absent(self):
        conn = _conn()
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(CLIENT_USER).post("/api/v1/auth/logout-all")
            finally:
                _teardown()
        assert response.status_code == 200
        calls = _executed(conn)
        assert not any("INSERT INTO revoked_jtis" in c for c in calls)
        assert any("client_id = %s" in c and "UPDATE refresh_tokens" in c for c in calls)

    def test_verify_refuses_revoked_jti(self):
        from app.auth.jwt_handler import create_token
        from app.config import settings

        token = create_token(
            subject="2", role="loan_officer", audience="staff",
        )
        conn = _conn()
        conn.cursor.return_value.fetchone.return_value = {"1": 1}  # found in revoked_jtis
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = TestClient(
                __import__("app.main", fromlist=["app"]).app
            ).post("/api/v1/auth/verify", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["valid"] is False
        calls = [a.args[0] for a in conn.cursor.return_value.execute.call_args_list]
        assert any("SELECT 1 FROM revoked_jtis" in c for c in calls)

    def test_verify_allows_unrevoked_jti(self):
        from app.auth.jwt_handler import create_token

        token = create_token(
            subject="2", role="loan_officer", audience="staff",
        )
        conn = _conn()
        conn.cursor.return_value.fetchone.return_value = None
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = TestClient(
                __import__("app.main", fromlist=["app"]).app
            ).post("/api/v1/auth/verify", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["valid"] is True
