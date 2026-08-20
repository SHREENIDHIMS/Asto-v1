"""Unit tests for Phase H2: forgot-password / reset flow.

- /auth/forgot-password returns the same generic 200 for known and unknown
  emails (no account enumeration), writes only a hashed one-time token row
  for known accounts, and a weak-password write is impossible.
- /auth/reset-password requires an unused, unexpired token; consuming it
  rotates the account credentials, marks the token used, and revokes all of
  the identity's refresh sessions (password change = logout everywhere).

All DB access is mocked (unit); the live-DB integration suite
(``test_h2_password_reset.py``) covers the real reset flow.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.auth.jwt_handler import hash_token


def _conn() -> MagicMock:
    """A connection whose cursor survives ``with`` blocks and yields mocks."""
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cur = conn.cursor.return_value
    cur.__enter__.return_value = cur
    return conn


def _client():
    from app.main import app
    return TestClient(app)


def _executed(conn) -> list[str]:
    return [a.args[0] for a in conn.cursor.return_value.execute.call_args_list]


class TestForgotPassword:
    def test_known_staff_email_writes_hashed_token_and_returns_generic_ok(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"ip_fails": 0},                          # reset throttle row
            {"id": 2, "email": "staff@asto.local"},  # users lookup hit
            None,                                    # clients lookup miss
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _client().post(
                "/api/v1/auth/forgot-password",
                json={"email": "staff@asto.local"},
            )

        assert response.status_code == 200
        assert response.json()["ok"] is True
        calls = _executed(conn)
        insert = next(c for c in calls if "INSERT INTO password_resets" in c)
        assert insert == (
            "INSERT INTO password_resets "
            "(email, audience, identity_id, token_hash, expires_at) "
            "VALUES (%s, %s, %s, %s, %s)"
        )
        args = [
            a.args[1] for a in conn.cursor.return_value.execute.call_args_list
            if "INSERT INTO password_resets" in a.args[0]
        ][0]
        assert args[0] == "staff@asto.local"
        assert args[1] == "staff"
        assert args[2] == 2
        # Only a SHA-256 hash is stored, never a raw token string.
        assert len(args[3]) == 64

    def test_known_client_email_writes_client_row(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"ip_fails": 0},                          # reset throttle row
            None,                                    # users lookup miss
            {"id": 7, "email": "client@asto.local"}, # clients lookup hit
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _client().post(
                "/api/v1/auth/forgot-password",
                json={"email": "client@asto.local"},
            )

        assert response.status_code == 200
        args = [
            a.args[1] for a in conn.cursor.return_value.execute.call_args_list
            if "INSERT INTO password_resets" in a.args[0]
        ][0]
        assert args[1] == "client"
        assert args[2] == 7

    def test_unknown_email_returns_generic_ok_with_no_insert(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = None
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _client().post(
                "/api/v1/auth/forgot-password",
                json={"email": "nobody@asto.test"},
            )
        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert not any(
            "INSERT INTO password_resets" in c for c in _executed(conn)
        )

    def test_email_is_normalized_but_response_is_identical(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"ip_fails": 0},                          # reset throttle row
            {"id": 2, "email": "Staff@Asto.Local"},
            None,
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            r1 = _client().post(
                "/api/v1/auth/forgot-password", json={"email": "  STAFF@asto.local "}
            )
        assert r1.status_code == 200
        args = [
            a.args[1] for a in conn.cursor.return_value.execute.call_args_list
            if "INSERT INTO password_resets" in a.args[0]
        ][0]
        assert args[0] == "staff@asto.local"


class TestResetPassword:
    def test_valid_token_updates_hash_marks_used_and_revokes_sessions(self):
        from passlib.hash import bcrypt

        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {
            "id": 5,
            "audience": "staff",
            "identity_id": 2,
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _client().post(
                "/api/v1/auth/reset-password",
                json={"token": "newpasswordtoken", "new_password": "brandnewpass99"},
            )

        assert response.status_code == 200
        assert response.json()["ok"] is True

        calls = _executed(conn)
        update_users = next(c for c in calls if "UPDATE users SET password_hash" in c)
        assert update_users == "UPDATE users SET password_hash = %s WHERE id = %s"
        update_users_args = [
            a.args[1] for a in conn.cursor.return_value.execute.call_args_list
            if "UPDATE users SET password_hash" in a.args[0]
        ][0]
        assert update_users_args[1] == 2
        assert bcrypt.verify("brandnewpass99", update_users_args[0]) is True

        # The consumed token must be marked used (single-use guarantee).
        assert any(
            "UPDATE password_resets SET used_at = now() WHERE id = %s" in c
            for c in calls
        )
        # All of the identity's sessions are killed on password change.
        assert any(
            "UPDATE refresh_tokens SET revoked_at = now() " in c
            and "user_id = %s" in c and "revoked_at IS NULL" in c
            for c in calls
        )

    def test_client_audience_targets_clients_table(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {
            "id": 5,
            "audience": "client",
            "identity_id": 7,
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _client().post(
                "/api/v1/auth/reset-password",
                json={"token": "clienttoken", "new_password": "newclientpass99"},
            )
        assert response.status_code == 200
        calls = _executed(conn)
        assert any("UPDATE clients SET password_hash" in c for c in calls)
        assert any(
            "client_id = %s" in c and "UPDATE refresh_tokens SET revoked_at" in c
            for c in calls
        )

    def test_unknown_or_consumed_token_rejected(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = None
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _client().post(
                "/api/v1/auth/reset-password",
                json={"token": "deadbeef", "new_password": "newpass1234"},
            )
        assert response.status_code == 400
        assert "Invalid or already-used" in response.json()["detail"]

    def test_expired_token_rejected(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {
            "id": 5,
            "audience": "staff",
            "identity_id": 2,
            "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1),
        }
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _client().post(
                "/api/v1/auth/reset-password",
                json={"token": "stale", "new_password": "newpass1234"},
            )
        assert response.status_code == 400
        assert "expired" in response.json()["detail"]

    def test_too_short_password_rejected_by_validation(self):
        with patch("app.db.postgres.session.acquire"):
            response = _client().post(
                "/api/v1/auth/reset-password",
                json={"token": "whatever", "new_password": "short"},
            )
        assert response.status_code == 422


class TestHashTokenShared:
    def test_hash_token_is_sha256_and_stable(self):
        assert len(hash_token("abc")) == 64
        assert hash_token("abc") == hash_token("abc")
        assert hash_token("abc") != hash_token("abd")


class TestResetLinkDelivery:
    def test_delivery_logs_link_with_token(self):
        from app.auth import password_reset_email

        with patch.object(password_reset_email.logger, "info") as mock_info:
            password_reset_email.deliver_reset_link(
                "staff@asto.local", "http://localhost:3011/login?reset=thetoken123"
            )
        mock_info.assert_called_once()
        args, _ = mock_info.call_args
        assert args[0] == "PASSWORD_RESET for %s: %s"
        assert args[1] == "staff@asto.local"
        assert "reset=thetoken123" in args[2]