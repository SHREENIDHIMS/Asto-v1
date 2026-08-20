"""Unit tests for audit fix #15 — login timing equalization.

``POST /auth/login`` and ``POST /auth/client-login`` previously short-
circuited ``bcrypt.verify`` when the email had no account, so the response
time revealed whether an email exists (account enumeration). The fix burns
one bcrypt verify against a fixed dummy hash in the no-account path, so
wrong-password-on-real-account and unknown-email take the same time.

These tests mock the DB + bcrypt and assert *which hash* verify is called
with on each path — not wall-clock timing, which is flaky in CI.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.v1.auth import _DUMMY_BCRYPT_HASH

STAFF_USER = {
    "id": 2,
    "email": "staff@asto.local",
    "password_hash": "$2b$12$3SLjUJ0DcXjdS7nEro3ZbuUPYP8rAWpXyMce67IoH7FM35etPiAy6",
    "role": "loan_officer",
    "department": "general",
    "full_name": "Dana Officer",
    "allowed_departments": ["general"],
    "totp_enabled": False,
}


def _conn(fetchone_returns=None, side_effect=None) -> MagicMock:
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cur = conn.cursor.return_value
    cur.__enter__.return_value = cur
    if side_effect is not None:
        cur.fetchone.side_effect = side_effect
    else:
        cur.fetchone.return_value = fetchone_returns
    return conn


def _login(email="nobody@asto.local", password="whatever123", path="/api/v1/auth/login"):
    from app.main import app
    return TestClient(app).post(path, json={"email": email, "password": password})


class TestLoginTimingEqualized:
    def test_unknown_email_still_calls_verify_with_dummy_hash(self):
        verify = MagicMock(return_value=False)
        with (
            patch("app.db.postgres.session.acquire", return_value=_conn()),
            patch("app.api.v1.auth.bcrypt.verify", verify),
        ):
            response = _login()

        assert response.status_code == 401
        # Staff lookup misses, then clients lookup misses -> two dummy verifies.
        assert verify.call_count == 2
        assert all(call.args[1] == _DUMMY_BCRYPT_HASH for call in verify.call_args_list)

    def test_existing_user_wrong_password_verifies_real_hash_then_dummy(self):
        verify = MagicMock(return_value=False)
        conn = _conn(side_effect=[None, STAFF_USER, None])
        with (
            patch("app.db.postgres.session.acquire", return_value=conn),
            patch("app.api.v1.auth.bcrypt.verify", verify),
        ):
            response = _login(email=STAFF_USER["email"], password="not-the-password")

        assert response.status_code == 401
        assert verify.call_count == 2
        assert verify.call_args_list[0].args[1] == STAFF_USER["password_hash"]
        assert verify.call_args_list[1].args[1] == _DUMMY_BCRYPT_HASH

    def test_client_login_unknown_email_verifies_dummy_hash(self):
        verify = MagicMock(return_value=False)
        with (
            patch("app.db.postgres.session.acquire", return_value=_conn()),
            patch("app.api.v1.auth.bcrypt.verify", verify),
        ):
            response = _login(path="/api/v1/auth/client-login")

        assert response.status_code == 401
        assert verify.call_count == 1
        assert verify.call_args_list[0].args[1] == _DUMMY_BCRYPT_HASH