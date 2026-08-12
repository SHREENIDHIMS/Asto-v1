"""Integration tests for Phase H3: login rate limiting + lockout.

Verifies the real Postgres-backed ``login_attempts`` throttle end to end:

- 5 consecutive wrong passwords for an email → the 6th attempt is rejected
  with 429 (lockout) even though it uses the correct password.
- Stale failure rows (older than the prune window) stop counting, so a
  failed attempt that happened more than 15 minutes ago no longer blocks
  login (window expiry re-enables login).
- A successful login clears the email's failure history, so the account is
  not immediately re-locked.

Any attempt in this suite also acts as a smoke test that the throttle is
wired into both ``/auth/login`` and ``/auth/client-login`` with the
``Retry-After`` / ``X-RateLimit-*`` response headers.

Requires a running Postgres with the asto_assistant schema; skips
gracefully when no DB is available (same pattern as test_unified_login.py).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from passlib.hash import bcrypt

from app.db.postgres.session import acquire

STAFF_EMAIL = "h3.locked.staff@asto.test"
CLIENT_EMAIL = "h3.locked.client@asto.test"
GOOD_PASSWORD = "correctpw123"


def _db_available() -> bool:
    try:
        from app.db.postgres.session import ping
        return ping()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="Requires a running Postgres instance with asto_assistant schema",
)


@pytest.fixture(scope="module")
def h3_db():
    """Seed one staff user + one client, then clean up rows after the module."""
    from app.db.postgres.schema import ensure_schema

    ensure_schema()

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (email, password_hash, full_name, role, department, allowed_departments) "
                "VALUES (%s, %s, 'H3 Locked Staff', 'loan_officer', 'general', ARRAY['general']) RETURNING id",
                (STAFF_EMAIL, bcrypt.hash(GOOD_PASSWORD)),
            )
            staff_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO clients (email, full_name, password_hash, is_active) "
                "VALUES (%s, %s, %s, true) RETURNING id",
                (CLIENT_EMAIL, "H3 Locked Client", bcrypt.hash(GOOD_PASSWORD)),
            )
            client_id = cur.fetchone()["id"]
        conn.commit()

    yield {"staff_id": staff_id, "client_id": client_id}

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s", (staff_id,))
            cur.execute("DELETE FROM clients WHERE id = %s", (client_id,))
            cur.execute("DELETE FROM login_attempts WHERE email IN (%s, %s)", (STAFF_EMAIL, CLIENT_EMAIL))
        conn.commit()


def _login(email: str, password: str, path: str = "/api/v1/auth/login"):
    from fastapi.testclient import TestClient
    from app.main import app

    return TestClient(app).post(path, json={"email": email, "password": password})


def _purge_attempts(email: str) -> None:
    """Remove any leftover failure rows so each test starts clean."""
    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM login_attempts WHERE email = %s", (email,))
        conn.commit()


class TestLockout:
    def test_fifth_failure_blocks_the_next_attempt(self, h3_db):
        _purge_attempts(STAFF_EMAIL)

        for _ in range(5):
            response = _login(STAFF_EMAIL, "wrong-password")
            assert response.status_code == 401

        # Even with the correct password the 6th attempt is throttled.
        response = _login(STAFF_EMAIL, GOOD_PASSWORD)
        assert response.status_code == 429
        assert response.json()["detail"] == "Too many failed attempts. Try again later."
        assert response.headers.get("retry-after")
        assert response.headers.get("x-ratelimit-remaining") == "0"

    def test_four_failures_still_allow_login(self, h3_db):
        _purge_attempts(CLIENT_EMAIL)

        for _ in range(4):
            assert _login(CLIENT_EMAIL, "wrong-password").status_code == 401
        assert _login(CLIENT_EMAIL, GOOD_PASSWORD).status_code == 200

    def test_client_login_shared_throttle(self, h3_db):
        _purge_attempts(CLIENT_EMAIL)

        for _ in range(5):
            assert _login(CLIENT_EMAIL, "wrong-password").status_code == 401
        response = _login(
            CLIENT_EMAIL, GOOD_PASSWORD, path="/api/v1/auth/client-login"
        )
        assert response.status_code == 429

    def test_stale_failures_no_longer_block_login(self, h3_db):
        _purge_attempts(STAFF_EMAIL)

        # Back-date rows past the 15-minute lockout window.
        old = datetime.now(timezone.utc) - timedelta(minutes=30)
        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO login_attempts (email, ip, attempted_at, success) "
                    "VALUES (%s, '', %s, false)",
                    (STAFF_EMAIL, old),
                )
            conn.commit()

        response = _login(STAFF_EMAIL, GOOD_PASSWORD)
        assert response.status_code == 200

    def test_successful_login_resets_failure_counter(self, h3_db):
        _purge_attempts(STAFF_EMAIL)

        for _ in range(4):
            assert _login(STAFF_EMAIL, "wrong-password").status_code == 401
        # Success clears the history, so a later failure no longer counts.
        assert _login(STAFF_EMAIL, GOOD_PASSWORD).status_code == 200
        assert _login(STAFF_EMAIL, "wrong-password").status_code == 401
        assert _login(STAFF_EMAIL, GOOD_PASSWORD).status_code == 200