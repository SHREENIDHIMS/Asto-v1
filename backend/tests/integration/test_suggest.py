"""Integration tests for J4 — suggestion scoping against the audit_log.

Seeds audit_log rows for an admin, a staff user (underwriting), and two
clients, then verifies:
  - prefix match returns the right suggestions ranked by usage
  - clients see only their own past queries
  - staff see only queries from their department scope
  - admins see all
  - empty prefix → empty list
"""

from __future__ import annotations

import pytest

from app.search.suggest import suggest_queries


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

_MARKER = "__j4_suggest__"


@pytest.fixture(scope="module")
def suggest_db():
    from app.db.postgres.session import acquire
    from app.db.postgres.schema import ensure_schema

    ensure_schema()

    with acquire() as conn:
        with conn.cursor() as cur:
            # Users: admin (id from sequence), staff (underwriting), clients.
            cur.execute(
                "INSERT INTO users (email, password_hash, role, department, "
                "allowed_departments, is_active) "
                "VALUES (%s, %s, %s, %s, %s, true) RETURNING id",
                ("j4_admin@example.com", "x", "super_admin", "general", []),
            )
            admin_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO users (email, password_hash, role, department, "
                "allowed_departments, is_active) "
                "VALUES (%s, %s, %s, %s, %s, true) RETURNING id",
                ("j4_staff@example.com", "x", "underwriter", "underwriting", []),
            )
            staff_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO clients (email, password_hash, full_name, is_active) "
                "VALUES (%s, %s, %s, true) RETURNING id",
                ("j4_client1@example.com", "x", "Client One"),
            )
            client1_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO clients (email, password_hash, full_name, is_active) "
                "VALUES (%s, %s, %s, true) RETURNING id",
                ("j4_client2@example.com", "x", "Client Two"),
            )
            client2_id = cur.fetchone()["id"]

            def log(user_id, query, outcome, audience, created_days_ago=0):
                cur.execute(
                    "INSERT INTO audit_log (user_id, audience, query, outcome, created_at) "
                    "VALUES (%s, %s, %s, %s, now() - make_interval(days => %s))",
                    (user_id, audience, _MARKER + query, outcome, created_days_ago),
                )

            # Admin queries
            log(admin_id, "what is the minimum credit score", "answer", "staff")
            log(admin_id, "what is the minimum credit score", "answer", "staff", 1)
            log(admin_id, "credit score requirements", "partial", "staff", 1)
            log(admin_id, "underwriting guidelines", "answer", "staff")
            # Staff (underwriting) queries
            log(staff_id, "underwriting guidelines", "answer", "staff")
            log(staff_id, "underwriting guidelines", "answer", "staff", 1)
            log(staff_id, "credit review checklist", "answer", "staff")
            # Client 1
            log(client1_id, "what is my case status", "answer", "client")
            log(client1_id, "missing documents for my loan", "answer", "client")
            # Client 2
            log(client2_id, "what is my case status", "answer", "client", 1)
            log(client2_id, "my loan balance", "answer", "client")
            # A failed query — must never surface as a suggestion
            log(admin_id, "credit score asdfqwer zxcvbnm", "no_answer", "staff")

            conn.commit()

    users = {
        "admin": {"id": admin_id, "role": "super_admin", "department": "general",
                  "allowed_departments": []},
        "staff": {"id": staff_id, "role": "underwriter", "department": "underwriting",
                  "allowed_departments": []},
        "client1": {"id": client1_id, "role": "client", "department": None,
                    "allowed_departments": [], "audience": "client",
                    "client_id": client1_id},
        "client2": {"id": client2_id, "role": "client", "department": None,
                    "allowed_departments": [], "audience": "client",
                    "client_id": client2_id},
    }

    yield users

    from app.db.postgres.session import acquire

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM audit_log WHERE query LIKE %s", ("%__marker__%",))
            cur.execute(
                "DELETE FROM audit_log WHERE user_id IN "
                "(SELECT id FROM users WHERE email IN (%s, %s))",
                ("j4_admin@example.com", "j4_staff@example.com"),
            )
            cur.execute(
                "DELETE FROM audit_log WHERE user_id IN "
                "(SELECT id FROM clients WHERE email IN (%s, %s))",
                ("j4_client1@example.com", "j4_client2@example.com"),
            )
            cur.execute(
                "DELETE FROM users WHERE email IN (%s, %s)",
                ("j4_admin@example.com", "j4_staff@example.com"),
            )
            cur.execute(
                "DELETE FROM clients WHERE email IN (%s, %s)",
                ("j4_client1@example.com", "j4_client2@example.com"),
            )
            conn.commit()


class TestSuggestions:
    def _suggest(self, prefix: str, user: dict):
        from app.db.postgres.session import acquire

        with acquire() as conn:
            raw = suggest_queries(conn=conn, prefix=_MARKER + prefix, user=user)
        return [q.replace(_MARKER, "") for q in raw]

    def test_empty_prefix_returns_empty(self, suggest_db):
        from app.db.postgres.session import acquire

        with acquire() as conn:
            assert suggest_queries(conn=conn, prefix="", user=suggest_db["admin"]) == []
            assert suggest_queries(conn=conn, prefix="   ", user=suggest_db["admin"]) == []

    def test_admin_sees_all_scopes(self, suggest_db):
        results = self._suggest("what is", suggest_db["admin"])
        assert "what is the minimum credit score" in results
        assert "what is my case status" in results

    def test_admin_prefix_ranking_by_usage(self, suggest_db):
        results = self._suggest("underwriting", suggest_db["admin"])
        assert "underwriting guidelines" in results[:2]

    def test_client_sees_own_queries_only(self, suggest_db):
        results = self._suggest("what is", suggest_db["client1"])
        assert "what is my case status" in results
        assert "what is the minimum credit score" not in results  # admin's
        assert "missing documents for my loan" not in results  # doesn't match prefix

    def test_client2_scoped_away(self, suggest_db):
        results = self._suggest("what is", suggest_db["client2"])
        assert "what is my case status" in results
        # client1's documents query must not leak to client2
        assert "missing documents for my loan" not in results

    def test_staff_sees_department_scope_only(self, suggest_db):
        results = self._suggest("credit", suggest_db["staff"])
        assert "credit review checklist" in results
        # admin's general credit-score queries are outside underwriting scope
        assert "credit score requirements" not in results

    def test_no_answer_never_suggested(self, suggest_db):
        results = self._suggest("credit score asdfqwer", suggest_db["admin"])
        assert "credit score asdfqwer zxcvbnm" not in results

    def test_like_wildcards_matched_literally(self, suggest_db):
        results = self._suggest("100%", suggest_db["admin"])
        assert results == []

    def test_client_does_not_see_staff_queries_with_same_id(self, suggest_db):
        """Regression: staff and clients can share a numeric id; a client
        must never see a staff member's queries via the audit_log."""
        from app.db.postgres.session import acquire

        staff_id = suggest_db["staff"]["id"]
        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO audit_log (user_id, audience, query, outcome) "
                    "VALUES (%s, 'staff', %s, 'answer')",
                    (staff_id, _MARKER + "secret underwriting formula"),
                )
                conn.commit()

        # A client that shares the SAME numeric id as the staff member.
        colliding_client = {
            "id": staff_id,
            "client_id": staff_id,
            "role": "client",
            "audience": "client",
            "department": None,
            "allowed_departments": [],
        }
        with acquire() as conn:
            results = suggest_queries(
                conn=conn, prefix=_MARKER + "secret", user=colliding_client
            )
        assert results == []  # client scope ANDs on audience='client'

        # The staff member themselves can see it.
        with acquire() as conn:
            results = suggest_queries(
                conn=conn, prefix=_MARKER + "secret", user=suggest_db["staff"]
            )
        assert _MARKER + "secret underwriting formula" in results
