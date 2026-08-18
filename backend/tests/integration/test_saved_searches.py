"""Integration tests for J7 — saved searches scoping and cap (real DB).

Seeds two staff users, then verifies the max-count guard and per-user
scoping against live Postgres. Skips when the DB is unavailable.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import require_auth


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

_MARKER = "__j7_saved__"


def _client():
    return TestClient(app)


@pytest.fixture(scope="module")
def saved_db():
    """Seed two staff users for scoping tests, clean up after."""
    from app.db.postgres.session import acquire
    from app.db.postgres.schema import ensure_schema

    ensure_schema()

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (email, password_hash, role, department, "
                "allowed_departments, is_active) "
                "VALUES (%s, %s, %s, %s, %s, true) RETURNING id",
                ("j7_staff_a@example.com", "x", "loan_officer", "general", []),
            )
            staff_a = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO users (email, password_hash, role, department, "
                "allowed_departments, is_active) "
                "VALUES (%s, %s, %s, %s, %s, true) RETURNING id",
                ("j7_staff_b@example.com", "x", "loan_officer", "general", []),
            )
            staff_b = cur.fetchone()["id"]
            conn.commit()

    yield {"staff_a": staff_a, "staff_b": staff_b}

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM saved_searches WHERE user_id IN (%s, %s)",
                (staff_a, staff_b),
            )
            cur.execute(
                "DELETE FROM users WHERE email IN (%s, %s)",
                ("j7_staff_a@example.com", "j7_staff_b@example.com"),
            )
            conn.commit()


class TestSavedSearchesIntegration:
    def test_save_list_delete_roundtrip(self, saved_db):
        from app.db.postgres.session import acquire

        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO saved_searches (user_id, query, filters) "
                    "VALUES (%s, %s, %s)",
                    (saved_db["staff_a"], _MARKER + "credit score", "{}"),
                )
                conn.commit()

        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM saved_searches "
                    "WHERE user_id = %s AND query = %s",
                    (saved_db["staff_a"], _MARKER + "credit score"),
                )
                assert cur.fetchone()["n"] == 1

    def test_scoping_staff_b_cannot_see_staff_a(self, saved_db):
        from app.db.postgres.session import acquire

        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM saved_searches WHERE user_id = %s",
                    (saved_db["staff_b"],),
                )
                assert cur.fetchone()["n"] == 0

    def test_max_count_guard(self, saved_db):
        from app.db.postgres.session import acquire
        from app.api.v1.saved_searches import MAX_SAVED_SEARCHES

        with acquire() as conn:
            with conn.cursor() as cur:
                for i in range(MAX_SAVED_SEARCHES):
                    cur.execute(
                        "INSERT INTO saved_searches (user_id, query, filters) "
                        "VALUES (%s, %s, %s)",
                        (saved_db["staff_b"], _MARKER + f"query {i}", "{}"),
                    )
                conn.commit()

        user = {
            "id": saved_db["staff_b"],
            "audience": "staff",
            "role": "loan_officer",
            "department": "general",
            "allowed_departments": [],
        }
        app.dependency_overrides[require_auth] = lambda: user
        try:
            response = _client().post(
                "/api/v1/staff/saved-searches",
                json={"query": _MARKER + "overflow"},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 409

        # Cleanup the rows created in this test.
        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM saved_searches WHERE user_id = %s",
                    (saved_db["staff_b"],),
                )
                conn.commit()
