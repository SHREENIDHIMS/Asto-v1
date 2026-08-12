"""Unit tests for Phase H3: login rate limiting + account lockout.

``POST /auth/login`` and the legacy ``/auth/client-login`` share a
Postgres-backed ``login_attempts`` evidence table. Before an attempt is
made, stale rows (older than the prune window) are deleted and recent
failures are counted in the same transaction; if either counter is at its
cap the request is rejected with 429. Every failed attempt is recorded and
a successful login clears the email's failure history.

These tests mock all DB access; the live-DB integration suite
(``test_h3_login_rate_limit.py`` in tests/integration) covers the real
lockout + window-expiry + reset flow.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

STAFF_USER = {
    "id": 2,
    "email": "staff@asto.local",
    "password_hash": "$2b$12$3SLjUJ0DcXjdS7nEro3ZbuUPYP8rAWpXyMce67IoH7FM35etPiAy6",  # "whatever123"
    "role": "loan_officer",
    "department": "general",
    "full_name": "Dana Officer",
    "allowed_departments": ["general"],
}


def _conn() -> MagicMock:
    """A connection whose cursor survives ``with`` blocks and yields mocks."""
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cur = conn.cursor.return_value
    cur.__enter__.return_value = cur
    return conn


def _login(email: str = "staff@asto.local", password: str = "whatever123", path: str = "/api/v1/auth/login"):
    from app.main import app
    return TestClient(app).post(path, json={"email": email, "password": password})


def _executed(conn) -> list[str]:
    return [a.args[0] for a in conn.cursor.return_value.execute.call_args_list]


class TestLoginThrottle:
    def test_email_at_cap_returns_429_with_headers(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"email_fails": 5, "ip_fails": 0}
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _login()
        assert response.status_code == 429
        assert "Too many failed attempts" in response.json()["detail"]
        headers = response.headers
        assert headers.get("retry-after")
        assert headers.get("x-ratelimit-limit") == "5"
        assert headers.get("x-ratelimit-remaining") == "0"

    def test_ip_at_cap_returns_429(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"email_fails": 2, "ip_fails": 10}
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _login()
        assert response.status_code == 429

    def test_below_threshold_proceeds_to_lookup(self):
        conn = _conn()
        cur = conn.cursor.return_value
        # Throttle COUNT row first, then the users lookup row.
        cur.fetchone.side_effect = [
            {"email_fails": 2, "ip_fails": 1},
            STAFF_USER,
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _login()
        assert response.status_code == 200
        assert response.json()["access_token"]

    def test_throttle_always_prunes_stale_rows(self):
        conn = _conn()
        cur = conn.cursor.return_value
        # Throttle row first, then the staff user (login succeeds).
        cur.fetchone.side_effect = [
            {"email_fails": 0, "ip_fails": 0},
            STAFF_USER,
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _login()
        assert response.status_code == 200
        assert any("DELETE FROM login_attempts" in c for c in _executed(conn))
        assert any("SELECT count(*) FILTER" in c for c in _executed(conn))

    def test_successful_login_clears_email_failures(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"email_fails": 3, "ip_fails": 0},
            STAFF_USER,
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _login()
        assert response.status_code == 200
        calls = _executed(conn)
        delete = next(c for c in calls if c.startswith("DELETE FROM login_attempts WHERE email"))
        assert "email = %s" in delete
        args = [
            a.args[1] for a in conn.cursor.return_value.execute.call_args_list
            if "DELETE FROM login_attempts WHERE email" in a.args[0]
        ][0]
        assert args[0] == "staff@asto.local"

    def test_failed_attempt_is_recorded(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"email_fails": 0, "ip_fails": 0},
            None,  # users lookup miss
            None,  # clients lookup miss
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _login(password="wrongpass")
        assert response.status_code == 401
        calls = [a.args[0] for a in conn.cursor.return_value.execute.call_args_list]
        insert = next(c for c in calls if c.startswith("INSERT INTO login_attempts"))
        assert "false" in insert
        args = [
            a.args[1] for a in conn.cursor.return_value.execute.call_args_list
            if "INSERT INTO login_attempts" in a.args[0]
        ][0]
        assert args[0] == "staff@asto.local"
        assert args[1] != ""  # an IP is always recorded

    def test_unknown_email_failure_is_recorded_for_ip_throttling(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"email_fails": 0, "ip_fails": 0},
            None,  # users lookup miss
            None,  # clients lookup miss
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _login(email="nobody@asto.test")
        assert response.status_code == 401
        assert any(
            "INSERT INTO login_attempts" in c
            for c in _executed(conn)
        )


class TestClientLoginThrottle:
    def test_client_login_uses_same_throttle(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"email_fails": 6, "ip_fails": 0}
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _login(path="/api/v1/auth/client-login")
        assert response.status_code == 429

    def test_client_login_success_clears_failures(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"email_fails": 0, "ip_fails": 0},
            {
                "id": 7, "email": "client@asto.local",
                "password_hash": STAFF_USER["password_hash"],
                "full_name": "Carl Client",
            },
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = _login(
                email="client@asto.local", path="/api/v1/auth/client-login"
            )
        assert response.status_code == 200
        assert any(
            "DELETE FROM login_attempts WHERE email" in c
            for c in _executed(conn)
        )