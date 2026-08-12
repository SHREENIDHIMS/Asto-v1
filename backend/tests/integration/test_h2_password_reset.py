"""Integration tests for Phase H2: forgot-password / reset flow.

Covers the real end-to-end reset against Postgres:

- /auth/forgot-password for a staff and a client identity writes a reset
  row, and the endpoint replies generically for unknown emails,
- the raw token returned by the reset link can be consumed once by
  /auth/reset-password, updating credentials and revoking sessions,
- a consumed token cannot be reused.

Requires a running Postgres with the asto_assistant schema; skips
gracefully when no DB is available (same pattern as test_unified_login.py).
"""

from __future__ import annotations

import pytest
from passlib.hash import bcrypt

from app.db.postgres.session import acquire

STAFF_EMAIL = "reset.staff@asto.test"
CLIENT_EMAIL = "reset.client@asto.test"


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
def reset_db():
    """Seed one staff user + one client, then clean up their rows."""
    from app.db.postgres.schema import ensure_schema

    ensure_schema()

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (email, password_hash, full_name, role, department, allowed_departments) "
                "VALUES (%s, %s, 'Reset Staff', 'loan_officer', 'general', ARRAY['general']) RETURNING id",
                (STAFF_EMAIL, bcrypt.hash("oldstaffpass123")),
            )
            staff_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO clients (email, full_name, password_hash, is_active) "
                "VALUES (%s, %s, %s, true) RETURNING id",
                (CLIENT_EMAIL, "Reset Client", bcrypt.hash("oldclientpass123")),
            )
            client_id = cur.fetchone()["id"]
        conn.commit()

    yield {"staff_id": staff_id, "client_id": client_id}

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM password_resets WHERE identity_id IN (%s, %s)", (staff_id, client_id))
            cur.execute("DELETE FROM users WHERE id = %s", (staff_id,))
            cur.execute("DELETE FROM clients WHERE id = %s", (client_id,))
        conn.commit()


def _last_reset_row(identity_id: int) -> dict:
    from app.auth.jwt_handler import hash_token

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM password_resets WHERE identity_id = %s ORDER BY id DESC LIMIT 1", (identity_id,))
            return cur.fetchone()


class TestForgotPasswordIntegration:
    def test_staff_forgot_writes_reset_row(self, reset_db):
        from fastapi.testclient import TestClient
        from app.main import app

        response = TestClient(app).post(
            "/api/v1/auth/forgot-password",
            json={"email": STAFF_EMAIL},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True

        row = _last_reset_row(reset_db["staff_id"])
        assert row is not None
        assert row["audience"] == "staff"
        assert len(row["token_hash"]) == 64  # hashed, consistent with H1 policy

    def test_client_forgot_writes_reset_row(self, reset_db):
        from fastapi.testclient import TestClient
        from app.main import app

        response = TestClient(app).post(
            "/api/v1/auth/forgot-password",
            json={"email": CLIENT_EMAIL},
        )
        assert response.status_code == 200

        row = _last_reset_row(reset_db["client_id"])
        assert row is not None
        assert row["audience"] == "client"

    def test_unknown_email_gets_generic_ok(self, reset_db):
        from fastapi.testclient import TestClient
        from app.main import app

        response = TestClient(app).post(
            "/api/v1/auth/forgot-password",
            json={"email": "not.registered@asto.test"},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True


class TestResetPasswordIntegration:
    def test_staff_reset_consumes_token_once_and_updates_password(self, reset_db):
        from fastapi.testclient import TestClient
        from app.auth.jwt_handler import hash_token
        from app.main import app

        row = _last_reset_row(reset_db["staff_id"])
        token = f"staff-reset-token-{row['id']}"
        # Re-point the row's hash at our known token so the test can emulate
        # the emailed link (the raw token is never stored).
        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE password_resets SET token_hash = %s WHERE id = %s", (hash_token(token), row["id"]))
            conn.commit()

        client = TestClient(app)
        response = client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": "brandnewstaff99"},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True

        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT password_hash FROM users WHERE id = %s", (reset_db["staff_id"],))
                new_hash = cur.fetchone()["password_hash"]
                cur.execute("SELECT used_at FROM password_resets WHERE id = %s", (row["id"],))
                used = cur.fetchone()["used_at"]

        assert bcrypt.verify("brandnewstaff99", new_hash) is True
        assert bcrypt.verify("oldstaffpass123", new_hash) is False
        assert used is not None

        # The same token must now be rejected (single-use).
        replay = client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": "replayedpass99"},
        )
        assert replay.status_code == 400

    def test_client_reset_updates_client_password(self, reset_db):
        from fastapi.testclient import TestClient
        from app.auth.jwt_handler import hash_token
        from app.main import app

        row = _last_reset_row(reset_db["client_id"])
        token = f"client-reset-token-{row['id']}"
        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE password_resets SET token_hash = %s WHERE id = %s", (hash_token(token), row["id"]))
            conn.commit()

        response = TestClient(app).post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": "brandnewclient99"},
        )
        assert response.status_code == 200

        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT password_hash FROM clients WHERE id = %s", (reset_db["client_id"],))
                new_hash = cur.fetchone()["password_hash"]
        assert bcrypt.verify("brandnewclient99", new_hash) is True

    def test_logout_all_sessions_after_reset(self, reset_db):
        """A password reset revokes active refresh sessions for the account."""
        from fastapi.testclient import TestClient
        from app.auth.jwt_handler import hash_token
        from app.main import app

        # Issue a real refresh token row for the staff account first.
        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO refresh_tokens (token_hash, user_id, audience, expires_at) "
                    "VALUES (%s, %s, 'staff', now() + interval '30 days') RETURNING id",
                    (hash_token("live-session-refresh"), reset_db["staff_id"]),
                )
                rt_id = cur.fetchone()["id"]
            conn.commit()

        row = _last_reset_row(reset_db["staff_id"])
        token = f"staff-reset-token-{row['id']}"  # row already consumed in earlier test
        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE password_resets SET used_at = NULL WHERE id = %s", (row["id"],))
                cur.execute("UPDATE password_resets SET token_hash = %s, expires_at = now() + interval '1 hour' WHERE id = %s", (hash_token(token), row["id"]))
            conn.commit()

        response = TestClient(app).post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": "freshafterreset99"},
        )
        assert response.status_code == 200

        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT revoked_at FROM refresh_tokens WHERE id = %s", (rt_id,))
                revoked = cur.fetchone()["revoked_at"]
        assert revoked is not None