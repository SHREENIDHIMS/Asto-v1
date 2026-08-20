"""Unit tests for Phase H1: HttpOnly refresh-cookie sessions.

The access JWT stays in the client's memory only; a long-lived refresh
token travels in an HttpOnly ``asto_refresh`` cookie (SameSite=Lax) and is
stored hashed in ``refresh_tokens``. These tests verify:

- login sets the HttpOnly cookie + stores only the hash + still returns the
  access JWT in the JSON body,
- /auth/refresh requires the X-Asto-CSRF header and rotates the token,
- revoked/expired/unknown refresh tokens are rejected,
- /auth/logout revokes the presented token and clears the cookie,
- /auth/logout-all revokes every row for the current identity (H5 hook).

All DB access is mocked (unit); the real-DB integration suite
(``test_unified_login.py``) still covers the live login path.
"""

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


def _conn() -> MagicMock:
    """A connection whose cursor survives ``with`` blocks and yields mocks."""
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


class TestRefreshCookie:
    def test_login_sets_httponly_cookie_and_hashes_token(self):
        from passlib.hash import bcrypt
        from app.auth.jwt_handler import hash_refresh_token

        conn = _conn()
        cur = conn.cursor.return_value
        # H3 throttle COUNT runs before the user lookup, so fetchone must
        # yield a throttle row (zero failures) first, then the staff user.
        cur.fetchone.side_effect = [
            {"email_fails": 0, "ip_fails": 0},
            {
                "id": 2, "email": "staff@asto.local",
                "password_hash": bcrypt.hash("whatever123"),
                "role": "loan_officer", "department": "general",
                "full_name": "Dana Officer", "allowed_departments": ["general"],
                "totp_enabled": False,
            },
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            from app.main import app
            response = TestClient(app).post(
                "/api/v1/auth/login",
                json={"email": "staff@asto.local", "password": "whatever123"},
            )

        assert response.status_code == 200
        assert response.json()["access_token"]
        set_cookie = response.headers["set-cookie"]
        assert "asto_refresh=" in set_cookie
        assert "HttpOnly" in set_cookie

        calls = [a.args[0] for a in cur.execute.call_args_list]
        insert = next(
            c for c in calls if "INSERT INTO refresh_tokens" in c
        )
        # Only the hash must be stored, never the raw token value.
        raw = next(c for c in set_cookie.split(";") if "asto_refresh=" in c).split("=", 1)[1]
        refresh_args = [
            a.args[1] for a in cur.execute.call_args_list
            if "INSERT INTO refresh_tokens" in a.args[0]
        ][0]
        assert refresh_args[0] == hash_refresh_token(raw)
        assert raw not in refresh_args

    def test_login_invalid_credentials_sets_no_cookie(self):
        conn = _conn()
        conn.cursor.return_value.fetchone.return_value = None
        with patch("app.db.postgres.session.acquire", return_value=conn):
            from app.main import app
            response = TestClient(app).post(
                "/api/v1/auth/login",
                json={"email": "nobody@x.test", "password": "nope"},
            )
        assert response.status_code == 401
        assert "set-cookie" not in response.headers or "asto_refresh" not in response.headers.get("set-cookie", "")

    def test_refresh_requires_csrf_header(self):
        from app.main import app
        response = TestClient(app).post("/api/v1/auth/refresh")
        assert response.status_code == 403

    def test_refresh_with_valid_cookie_rotates_token(self):
        from datetime import datetime, timedelta, timezone
        from app.auth.jwt_handler import verify_token

        conn = _conn()
        cur = conn.cursor.return_value
        cur.rowcount = 1  # rotation UPDATE matched the unrevoked row
        cur.fetchone.side_effect = [
            {"id": 10, "user_id": 2, "client_id": None, "audience": "staff",
             "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
             "revoked_at": None},                                           # refresh row
            {"id": 2, "email": "staff@asto.local", "full_name": "Dana Officer",
             "role": "loan_officer", "department": "general",
             "allowed_departments": ["general"]},                          # users row
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            from app.main import app
            client = TestClient(app)
            client.cookies.set("asto_refresh", "raw-refresh-token-xxx")
            response = client.post("/api/v1/auth/refresh", headers={"X-Asto-CSRF": "1"})

        assert response.status_code == 200
        payload = verify_token(response.json()["access_token"])
        assert payload is not None
        assert payload["audience"] == "staff"
        assert payload["role"] == "loan_officer"

        calls = [a.args[0] for a in cur.execute.call_args_list]
        # The old token must be revoked and a new one inserted (rotation).
        assert any("UPDATE refresh_tokens SET revoked_at" in c for c in calls)
        assert sum("INSERT INTO refresh_tokens" in c for c in calls) == 1

    def test_refresh_rejects_revoked_token(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {
            "id": 10, "user_id": 2, "client_id": None, "audience": "staff",
            "expires_at": 9999999999, "revoked_at": "2026-01-01",
        }
        with patch("app.db.postgres.session.acquire", return_value=conn):
            from app.main import app
            client = TestClient(app)
            client.cookies.set("asto_refresh", "revoked-refresh-token")
            response = client.post("/api/v1/auth/refresh", headers={"X-Asto-CSRF": "1"})
        assert response.status_code == 401

    def test_refresh_rejects_replay_when_rotation_lost(self):
        """Two concurrent uses of one token: the loser's rotation UPDATE
        matches 0 rows (rowcount guard) and must be rejected, so a stolen
        token cannot be replayed to mint more than one new token."""
        from datetime import datetime, timedelta, timezone

        conn = _conn()
        cur = conn.cursor.return_value
        cur.rowcount = 0  # another request already rotated this token
        cur.fetchone.return_value = {
            "id": 10, "user_id": 2, "client_id": None, "audience": "staff",
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
            "revoked_at": None,
        }
        with patch("app.db.postgres.session.acquire", return_value=conn):
            from app.main import app
            client = TestClient(app)
            client.cookies.set("asto_refresh", "replayed-token-xxx")
            response = client.post("/api/v1/auth/refresh", headers={"X-Asto-CSRF": "1"})
        assert response.status_code == 401
        calls = [a.args[0] for a in cur.execute.call_args_list]
        assert any("revoked_at IS NULL" in c for c in calls)

    def test_logout_revokes_and_clears_cookie(self):
        conn = _conn()
        with patch("app.db.postgres.session.acquire", return_value=conn):
            from app.main import app
            client = TestClient(app)
            client.cookies.set("asto_refresh", "logout-token-xxx")
            response = client.post("/api/v1/auth/logout", headers={"X-Asto-CSRF": "1"})

        assert response.status_code == 200
        assert response.json()["ok"] is True
        set_cookie = response.headers.get("set-cookie", "")
        assert "asto_refresh=" in set_cookie  # clearing cookie
        calls = [a.args[0] for a in conn.cursor.return_value.execute.call_args_list]
        assert any(
            "revoked_at = now()" in c and "token_hash = %s" in c for c in calls
        )

    def test_logout_csrf_required(self):
        from app.main import app
        response = TestClient(app).post("/api/v1/auth/logout")
        assert response.status_code == 403


class TestLogoutAll:
    def test_logout_all_revokes_all_staff_tokens(self):
        conn = _conn()
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).post("/api/v1/auth/logout-all")
            finally:
                _cleanup()
        assert response.status_code == 200
        assert response.json()["revoked"] is True
        calls = [a.args[0] for a in conn.cursor.return_value.execute.call_args_list]
        assert any(
            "UPDATE refresh_tokens SET revoked_at = now() " in c and "user_id = %s" in c
            for c in calls
        )

    def test_logout_all_requires_auth(self):
        from app.main import app
        response = TestClient(app).post("/api/v1/auth/logout-all")
        assert response.status_code == 401


class TestRefreshTokenHelpers:
    def test_new_refresh_token_is_opaque_and_unique(self):
        from app.auth.jwt_handler import new_refresh_token

        a = new_refresh_token()
        b = new_refresh_token()
        assert a != b
        assert len(a) >= 40
        # Must not start with a JWT header (never a bearer token).
        assert not a.startswith("eyJ")

    def test_hash_is_sha256_digest(self):
        from app.auth.jwt_handler import hash_refresh_token

        assert len(hash_refresh_token("abc")) == 64
        assert hash_refresh_token("abc") == hash_refresh_token("abc")
        assert hash_refresh_token("abc") != hash_refresh_token("abd")