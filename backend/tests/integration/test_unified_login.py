"""Integration tests for the unified single sign-in endpoint.

``POST /auth/login`` now resolves the identity across both the ``users``
(staff) and ``clients`` (external client) tables in one request, so the
frontend needs no Staff/Client selector. These tests verify:

- A staff user resolves via /auth/login with audience="staff".
- An external client resolves via the same /auth/login with
  audience="client" + client_id.
- A bad password / unknown email returns a single generic 401.

Requires a running Postgres with the asto_assistant schema; skips
gracefully when no DB is available (same pattern as test_end_to_end.py).
"""

from __future__ import annotations

import pytest
from passlib.hash import bcrypt

from app.db.postgres.session import acquire

STAFF_EMAIL = "unified.staff@asto.test"
CLIENT_EMAIL = "unified.client@asto.test"


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
def unified_db():
    """Seed one staff user + one client for unified-login tests, then clean up."""
    from app.db.postgres.schema import ensure_schema

    ensure_schema()

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (email, password_hash, full_name, role, department, allowed_departments) "
                "VALUES (%s, %s, 'Unified Staff', 'loan_officer', 'general', ARRAY['general']) RETURNING id",
                (STAFF_EMAIL, bcrypt.hash("staffpass123")),
            )
            staff_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO clients (email, full_name, password_hash, is_active) "
                "VALUES (%s, %s, %s, true) RETURNING id",
                (CLIENT_EMAIL, "Unified Client", bcrypt.hash("clientpass123")),
            )
            client_id = cur.fetchone()["id"]
        conn.commit()

    yield {"staff_id": staff_id, "client_id": client_id}

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s", (staff_id,))
            cur.execute("DELETE FROM clients WHERE id = %s", (client_id,))
        conn.commit()


class TestUnifiedLogin:
    def test_staff_resolves_via_unified_login(self, unified_db):
        from fastapi.testclient import TestClient
        from app.auth.jwt_handler import verify_token
        from app.main import app

        client = TestClient(app)
        response = client.post(
            "/api/v1/auth/login",
            json={"email": STAFF_EMAIL, "password": "staffpass123"},
        )
        assert response.status_code == 200
        payload = verify_token(response.json()["access_token"])
        assert payload is not None
        assert payload["audience"] == "staff"
        assert payload["role"] == "loan_officer"

    def test_client_resolves_via_unified_login(self, unified_db):
        from fastapi.testclient import TestClient
        from app.auth.jwt_handler import verify_token
        from app.main import app

        client = TestClient(app)
        response = client.post(
            "/api/v1/auth/login",
            json={"email": CLIENT_EMAIL, "password": "clientpass123"},
        )
        assert response.status_code == 200
        payload = verify_token(response.json()["access_token"])
        assert payload is not None
        assert payload["audience"] == "client"
        assert payload["client_id"] == unified_db["client_id"]

    def test_bad_password_returns_generic_401(self, unified_db):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        for email in (STAFF_EMAIL, CLIENT_EMAIL, "nobody@asto.test"):
            response = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrongpass"},
            )
            assert response.status_code == 401
            assert response.json()["detail"] == "Invalid credentials"

    def test_legacy_client_login_endpoint_still_works(self, unified_db):
        from fastapi.testclient import TestClient
        from app.auth.jwt_handler import verify_token
        from app.main import app

        client = TestClient(app)
        response = client.post(
            "/api/v1/auth/client-login",
            json={"email": CLIENT_EMAIL, "password": "clientpass123"},
        )
        assert response.status_code == 200
        payload = verify_token(response.json()["access_token"])
        assert payload["audience"] == "client"
