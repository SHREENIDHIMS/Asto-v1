"""Unit tests for Phase H4: admin 2FA (TOTP).

Covers:
- setup returns an otpauth:// URI + secret (admin only; 403 for clients/non-admins)
- verify enables 2FA with a valid code, 401 with a wrong code
- disable requires the current password (401 on wrong password)
- the login flow: /auth/login returns requires_2fa + two_fa_token for an
  enabled account (and no credentials), /auth/2fa swaps it for a real JWT
- two_fa_token is single-use (a second /auth/2fa with the same token -> 401)
- a normal login without 2FA is unchanged

The DB is mocked per test (``app.db.postgres.session.acquire``), so no live
Postgres is needed. TOTP codes are generated against the same secret the
handler stored, using pyotp directly.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import pyotp
from fastapi.testclient import TestClient
from passlib.hash import bcrypt

ADMIN_USER = {
    "id": 1,
    "email": "admin@asto.local",
    "full_name": "Admin User",
    "is_active": True,
    "audience": "staff",
    "role": "admin",
    "department": "general",
    "allowed_departments": ["general"],
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

PASSWORD = "adminsecret123"


def _conn() -> MagicMock:
    """A connection whose cursor survives ``with`` blocks and yields mocks."""
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cur = conn.cursor.return_value
    cur.__enter__.return_value = cur
    return conn


def _secret_for(conn: MagicMock) -> str:
    """Recover the plaintext secret the setup handler encrypted, to mint codes."""
    from app.auth.totp import decrypt_secret

    calls = conn.cursor.return_value.execute.call_args_list
    update = next(c for c in calls if "UPDATE users SET totp_secret" in c.args[0])
    return decrypt_secret(update.args[1][0])


@pytest.fixture
def authorized_client():
    """TestClient factory with the given identity overriding require_auth."""
    from app.main import app
    from app.dependencies import require_auth

    def _factory(user: dict) -> TestClient:
        app.dependency_overrides[require_auth] = lambda: user
        return TestClient(app)

    yield _factory
    app.dependency_overrides.pop(require_auth, None)


class TestTwoFaSetup:
    def test_setup_returns_uri_and_secret(self, authorized_client):
        conn = _conn()
        conn.cursor.return_value.fetchone.return_value = {"totp_enabled": False}
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = authorized_client(ADMIN_USER).post("/api/v1/admin/2fa/setup")

        assert response.status_code == 200
        body = response.json()
        assert body["secret"]
        assert body["otpauth_uri"].startswith("otpauth://totp/")
        assert "admin%40asto.local" in body["otpauth_uri"]

        calls = [a.args[0] for a in conn.cursor.return_value.execute.call_args_list]
        assert any("UPDATE users SET totp_secret" in c for c in calls)

    def test_setup_conflict_when_already_enabled(self, authorized_client):
        conn = _conn()
        conn.cursor.return_value.fetchone.return_value = {"totp_enabled": True}
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = authorized_client(ADMIN_USER).post("/api/v1/admin/2fa/setup")
        assert response.status_code == 409

    def test_setup_rejects_non_admin(self, authorized_client):
        conn = _conn()
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = authorized_client(STAFF_USER).post("/api/v1/admin/2fa/setup")
        assert response.status_code == 403

    def test_setup_rejects_client(self, authorized_client):
        conn = _conn()
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = authorized_client(CLIENT_USER).post("/api/v1/admin/2fa/setup")
        assert response.status_code == 403

    def test_setup_requires_auth(self):
        from app.main import app
        response = TestClient(app).post("/api/v1/admin/2fa/setup")
        assert response.status_code == 401


class TestTwoFaVerify:
    def test_verify_enables_with_valid_code(self, authorized_client):
        conn = _conn()
        secret = pyotp.random_base32()
        from app.auth.totp import encrypt_secret

        conn.cursor.return_value.fetchone.return_value = {
            "totp_secret": encrypt_secret(secret),
            "totp_enabled": False,
        }
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = authorized_client(ADMIN_USER).post(
                "/api/v1/admin/2fa/verify",
                json={"code": pyotp.TOTP(secret).now()},
            )
        assert response.status_code == 200
        assert response.json() == {"enabled": True}
        calls = [a.args[0] for a in conn.cursor.return_value.execute.call_args_list]
        assert any("totp_enabled = true" in c for c in calls)

    def test_verify_wrong_code_401(self, authorized_client):
        conn = _conn()
        secret = pyotp.random_base32()
        from app.auth.totp import encrypt_secret

        conn.cursor.return_value.fetchone.return_value = {
            "totp_secret": encrypt_secret(secret),
            "totp_enabled": False,
        }
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = authorized_client(ADMIN_USER).post(
                "/api/v1/admin/2fa/verify",
                json={"code": "000000"},
            )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid 2FA code"

    def test_verify_without_pending_setup_400(self, authorized_client):
        conn = _conn()
        conn.cursor.return_value.fetchone.return_value = {
            "totp_secret": None,
            "totp_enabled": False,
        }
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = authorized_client(ADMIN_USER).post(
                "/api/v1/admin/2fa/verify",
                json={"code": "123456"},
            )
        assert response.status_code == 400


class TestTwoFaDisable:
    def test_disable_requires_correct_password(self, authorized_client):
        conn = _conn()
        conn.cursor.return_value.fetchone.return_value = {
            "password_hash": bcrypt.hash(PASSWORD),
        }
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = authorized_client(ADMIN_USER).post(
                "/api/v1/admin/2fa/disable",
                json={"current_password": PASSWORD},
            )
        assert response.status_code == 200
        assert response.json() == {"enabled": False}
        calls = [a.args[0] for a in conn.cursor.return_value.execute.call_args_list]
        assert any("totp_secret = NULL" in c for c in calls)

    def test_disable_wrong_password_401(self, authorized_client):
        conn = _conn()
        conn.cursor.return_value.fetchone.return_value = {
            "password_hash": bcrypt.hash(PASSWORD),
        }
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = authorized_client(ADMIN_USER).post(
                "/api/v1/admin/2fa/disable",
                json={"current_password": "wrong-password-1"},
            )
        assert response.status_code == 401


class TestTwoFaLoginFlow:
    def test_login_2fa_account_returns_token_not_credentials(self):
        from app.main import app
        from app.auth.totp import encrypt_secret

        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"email_fails": 0, "ip_fails": 0},                       # throttle row
            {
                "id": 2, "email": "admin@asto.local",
                "password_hash": bcrypt.hash(PASSWORD),
                "role": "admin", "department": "general",
                "full_name": "Admin User", "allowed_departments": ["general"],
                "totp_enabled": True, "totp_secret": encrypt_secret(pyotp.random_base32()),
            },
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = TestClient(app).post(
                "/api/v1/auth/login",
                json={"email": "admin@asto.local", "password": PASSWORD},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["requires_2fa"] is True
        assert body["two_fa_token"]
        assert body["access_token"] is None
        # No refresh cookie and no access JWT issued yet.
        assert "asto_refresh" not in response.headers.get("set-cookie", "")

    def test_login_without_2fa_is_unchanged(self):
        from app.main import app

        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"email_fails": 0, "ip_fails": 0},                       # throttle row
            {
                "id": 2, "email": "admin@asto.local",
                "password_hash": bcrypt.hash(PASSWORD),
                "role": "admin", "department": "general",
                "full_name": "Admin User", "allowed_departments": ["general"],
                "totp_enabled": False,
            },
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = TestClient(app).post(
                "/api/v1/auth/login",
                json={"email": "admin@asto.local", "password": PASSWORD},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["requires_2fa"] is False
        assert body["access_token"]
        assert "asto_refresh=" in response.headers["set-cookie"]

    def test_two_factor_login_swaps_token_for_jwt(self):
        from app.main import app
        from app.auth.totp import encrypt_secret

        secret = pyotp.random_base32()
        from app.auth.jwt_handler import create_2fa_token
        from app.config import settings

        two_fa_token = create_2fa_token("2", settings.two_fa_token_ttl_minutes)

        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            None,  # revoked_jtis check (not revoked)
            {
                "id": 2, "email": "admin@asto.local",
                "full_name": "Admin User", "role": "admin",
                "department": "general", "allowed_departments": ["general"],
                "totp_secret": encrypt_secret(secret),
                "totp_enabled": True,
            },
            {"email_fails": 0, "ip_fails": 0},  # 2FA throttle row (allowed)
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = TestClient(app).post(
                "/api/v1/auth/2fa",
                json={"two_fa_token": two_fa_token, "code": pyotp.TOTP(secret).now()},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["access_token"]
        assert "asto_refresh=" in response.headers["set-cookie"]

        calls = [a.args[0] for a in cur.execute.call_args_list]
        assert any("INSERT INTO revoked_jtis" in c for c in calls)  # single-use
        assert any("INSERT INTO refresh_tokens" in c for c in calls)

    def test_two_factor_login_wrong_code_401(self):
        from app.main import app
        from app.auth.jwt_handler import create_2fa_token
        from app.config import settings
        from app.auth.totp import encrypt_secret

        secret = pyotp.random_base32()
        two_fa_token = create_2fa_token("2", settings.two_fa_token_ttl_minutes)

        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            None,
            {
                "id": 2, "email": "admin@asto.local",
                "full_name": "Admin User", "role": "admin",
                "department": "general", "allowed_departments": ["general"],
                "totp_secret": encrypt_secret(secret),
                "totp_enabled": True,
            },
            {"email_fails": 0, "ip_fails": 0},  # 2FA throttle row (allowed)
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = TestClient(app).post(
                "/api/v1/auth/2fa",
                json={"two_fa_token": two_fa_token, "code": "999999"},
            )
        assert response.status_code == 401

    def test_two_fa_token_single_use(self):
        from app.main import app
        from app.auth.jwt_handler import create_2fa_token
        from app.config import settings
        from app.auth.totp import encrypt_secret

        secret = pyotp.random_base32()
        two_fa_token = create_2fa_token("2", settings.two_fa_token_ttl_minutes)

        # First use: revoked_jtis check returns None (clean), then the user row.
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            None,
            {
                "id": 2, "email": "admin@asto.local",
                "full_name": "Admin User", "role": "admin",
                "department": "general", "allowed_departments": ["general"],
                "totp_secret": encrypt_secret(secret),
                "totp_enabled": True,
            },
            {"email_fails": 0, "ip_fails": 0},  # 2FA throttle row (allowed)
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            first = TestClient(app).post(
                "/api/v1/auth/2fa",
                json={"two_fa_token": two_fa_token, "code": pyotp.TOTP(secret).now()},
            )
        assert first.status_code == 200

        # Second use: revoked_jtis check now finds the consumed jti.
        conn2 = _conn()
        conn2.cursor.return_value.fetchone.return_value = {"1": 1}
        with patch("app.db.postgres.session.acquire", return_value=conn2):
            second = TestClient(app).post(
                "/api/v1/auth/2fa",
                json={"two_fa_token": two_fa_token, "code": pyotp.TOTP(secret).now()},
            )
        assert second.status_code == 401
        assert second.json()["detail"] == "2FA token already used"

    def test_two_factor_login_rejects_access_jwt_as_2fa_token(self):
        from app.main import app
        from app.auth.jwt_handler import create_token

        access_token = create_token(subject="2", role="admin", audience="staff")
        response = TestClient(app).post(
            "/api/v1/auth/2fa",
            json={"two_fa_token": access_token, "code": "123456"},
        )
        assert response.status_code == 401


class TestTwoFaStatus:
    def test_status_enabled(self, authorized_client):
        conn = _conn()
        conn.cursor.return_value.fetchone.return_value = {"totp_enabled": True}
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = authorized_client(ADMIN_USER).get("/api/v1/admin/2fa/status")
        assert response.status_code == 200
        assert response.json() == {"enabled": True}

    def test_status_disabled(self, authorized_client):
        conn = _conn()
        conn.cursor.return_value.fetchone.return_value = {"totp_enabled": False}
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = authorized_client(ADMIN_USER).get("/api/v1/admin/2fa/status")
        assert response.status_code == 200
        assert response.json() == {"enabled": False}
