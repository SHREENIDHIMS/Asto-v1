"""Unit tests for auth throttling (H3 extensions).

Covers: the 2FA endpoint enforcing the login-attempt throttle (TOTP codes
are 6 digits and must not be brute-forceable) and the password-reset
endpoint being throttled per source IP without ever counting against a
real account's login lockout (lockout-DoS protection).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.auth.jwt_handler import create_2fa_token


def _conn() -> MagicMock:
    """A connection whose cursor survives ``with`` blocks and yields mocks."""
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cur = conn.cursor.return_value
    cur.__enter__.return_value = cur
    return conn


def _client() -> TestClient:
    from app.main import app
    return TestClient(app)


def _executed(conn) -> list[str]:
    return [a.args[0] for a in conn.cursor.return_value.execute.call_args_list]


class TestTwoFactorThrottle:
    def test_locked_out_email_gets_429(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            None,  # revoked-jti check: token not consumed yet
            {
                "id": 1, "email": "admin@asto.local", "full_name": "Admin",
                "role": "admin", "department": "general",
                "allowed_departments": ["general"],
                "totp_secret": "secret", "totp_enabled": True,
            },
            {"email_fails": 5, "ip_fails": 0},  # throttle count → locked out
        ]
        token = create_2fa_token("1", ttl_minutes=5)
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _client().post(
                "/api/v1/auth/2fa",
                json={"two_fa_token": token, "code": "000000"},
            )
        assert response.status_code == 429

    def test_within_limit_proceeds_to_code_check(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            None,  # revoked-jti check
            {
                "id": 1, "email": "admin@asto.local", "full_name": "Admin",
                "role": "admin", "department": "general",
                "allowed_departments": ["general"],
                "totp_secret": "secret", "totp_enabled": True,
            },
            {"email_fails": 0, "ip_fails": 0},  # throttle count → allowed
        ]
        token = create_2fa_token("1", ttl_minutes=5)
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _client().post(
                "/api/v1/auth/2fa",
                json={"two_fa_token": token, "code": "000000"},
            )
        # Wrong code must yield 401 (invalid), not 500/429.
        assert response.status_code == 401


class TestForgotPasswordThrottle:
    def test_flooding_ip_gets_429(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"ip_fails": 10}
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _client().post(
                "/api/v1/auth/forgot-password",
                json={"email": "admin@asto.local"},
            )
        assert response.status_code == 429

    def test_reset_records_sentinel_not_victim_email(self):
        from app.api.v1.auth import _RESET_SENTINEL_EMAIL

        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"ip_fails": 0},  # throttle count → allowed
            {"id": 1, "email": "admin@asto.local"},  # users row
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _client().post(
                "/api/v1/auth/forgot-password",
                json={"email": "admin@asto.local"},
            )
        assert response.status_code == 200
        assert _RESET_SENTINEL_EMAIL == "__password_reset__"
        inserts = [c.args for c in cur.execute.call_args_list if "INSERT INTO login_attempts" in c.args[0]]
        assert inserts and inserts[0][1][0] == _RESET_SENTINEL_EMAIL
        assert "admin@asto.local" not in inserts[0][1]


class TestResetPasswordThrottle:
    def test_flooding_ip_gets_429_before_token_processing(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"ip_fails": 10}
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _client().post(
                "/api/v1/auth/reset-password",
                json={"token": "guess", "new_password": "newpass1234"},
            )
        assert response.status_code == 429
        assert "Too many requests" in response.json()["detail"]
        # The token lookup must never run once the IP is over the cap.
        token_lookups = [
            c for c in _executed(conn)
            if "SELECT id, audience, identity_id, expires_at FROM password_resets" in c
        ]
        assert not token_lookups

    def test_invalid_token_still_commits_throttle_row(self):
        """Invalid-token guesses must count toward the per-IP cap, so the
        throttle row has to survive the 400 path (no rollback)."""
        from app.api.v1.auth import _RESET_SENTINEL_EMAIL

        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"ip_fails": 0},  # throttle count → allowed
            None,  # token lookup → invalid token
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _client().post(
                "/api/v1/auth/reset-password",
                json={"token": "guess", "new_password": "newpass1234"},
            )
        assert response.status_code == 400

        inserts = [
            c.args for c in cur.execute.call_args_list
            if "INSERT INTO login_attempts" in c.args[0]
        ]
        assert inserts and inserts[0][1][0] == _RESET_SENTINEL_EMAIL
        assert "guess" not in inserts[0][1]
        # Exactly one commit happened, before the 400: the throttle row must
        # be persisted even though the token path never reaches a commit.
        assert conn.commit.call_count == 1

    def test_within_limit_proceeds_to_token_lookup(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"ip_fails": 0},  # throttle count → allowed
            None,  # token lookup → invalid (not throttled)
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _client().post(
                "/api/v1/auth/reset-password",
                json={"token": "guess", "new_password": "newpass1234"},
            )
        # Reaches token validation -> 400 (invalid token), not 429.
        assert response.status_code == 400


class TestRevokedJtiEnforced:
    def _token(self) -> str:
        from app.auth.jwt_handler import create_token
        return create_token(
            subject="2", role="loan_officer", department="general",
            allowed_departments=["general"], audience="staff",
        )

    def _run(self, token_revoked: bool):
        import asyncio
        from types import SimpleNamespace

        from app.dependencies import get_current_user

        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {
            "id": 2, "email": "staff@asto.local", "full_name": "Dana Officer",
            "role": "loan_officer", "department": "general",
            "allowed_departments": ["general"], "is_active": True,
            "token_revoked": token_revoked,
        }
        creds = SimpleNamespace(credentials=self._token())
        with patch("app.db.postgres.session.acquire", return_value=conn):
            return asyncio.run(get_current_user(creds))

    def test_revoked_token_raises_401(self):
        from fastapi import HTTPException
        import pytest

        with pytest.raises(HTTPException) as exc:
            self._run(token_revoked=True)
        assert exc.value.status_code == 401
        assert exc.value.detail == "Token has been revoked"

    def test_active_token_returns_user(self):
        user = self._run(token_revoked=False)
        assert user["email"] == "staff@asto.local"
        assert user["audience"] == "staff"
        assert user["jti"]