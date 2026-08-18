"""Integration tests for J2 — faceted filters in the search pipeline.

Seeds company-wide AND client-scoped documents plus staff/client
assignments, then verifies:
  - each filter (department, doc_type, date range, client_id) narrows the
    candidate set correctly, AND
  - the filters can only narrow, never widen, the RBAC scope (a staff
    member filtering to an unassigned client gets zero candidates).

Requires a live Postgres instance (skips gracefully when unavailable).
"""

from __future__ import annotations

import hashlib

import pytest

from app.config import settings
from app.search.hybrid_orchestrator import _build_filter_clause, search_knowledge_base


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

_MARKER = "__j2_filter_test__"


@pytest.fixture(scope="module")
def filter_db():
    """Seed client-scoped docs + assignments for filter tests, then clean up."""
    from app.db.postgres.session import acquire
    from app.db.postgres.schema import ensure_schema
    from app.search.pgvector_search import embed_query

    ensure_schema()

    with acquire() as conn:
        with conn.cursor() as cur:
            # --- Client-scoped fixture: two clients, one assigned staff ---
            cur.execute(
                "INSERT INTO clients (email, password_hash, full_name, is_active) "
                "VALUES (%s, %s, %s, true) RETURNING id",
                ("j2_client_a@example.com", "x", "Client A"),
            )
            client_a = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO clients (email, password_hash, full_name, is_active) "
                "VALUES (%s, %s, %s, true) RETURNING id",
                ("j2_client_b@example.com", "x", "Client B"),
            )
            client_b = cur.fetchone()["id"]

            cur.execute(
                "INSERT INTO users (email, password_hash, role, department, "
                "allowed_departments, is_active) "
                "VALUES (%s, %s, %s, %s, %s, true) RETURNING id",
                ("j2_staff@example.com", "x", "loan_officer", "general",
                 ["general", "underwriting"]),
            )
            staff_id = cur.fetchone()["id"]

            # Staff assigned to client A only.
            cur.execute(
                "INSERT INTO staff_client_assignments (user_id, client_id) VALUES (%s, %s)",
                (staff_id, client_a),
            )

            # --- Documents: client A doc (underwriting), client B doc (general) ---
            def insert_doc(title: str, doc_type: str, department: str,
                           client_id: int | None, content: str,
                           created_days_ago: int = 0) -> None:
                cur.execute(
                    "INSERT INTO documents (title, doc_type, department, client_id, "
                    "is_active, is_approved, version, source_path, created_at) "
                    "VALUES (%s, %s, %s, %s, true, true, 1, %s, "
                    "now() - make_interval(days => %s)) RETURNING id",
                    (title, doc_type, department, client_id, _MARKER, created_days_ago),
                )
                doc_id = cur.fetchone()["id"]
                chunk_hash = hashlib.md5(content.encode()).hexdigest()
                cur.execute(
                    "INSERT INTO document_chunks "
                    "(document_id, content, content_hash, section, chunk_type, "
                    "department, is_active, is_approved) "
                    "VALUES (%s, %s, %s, %s, %s, %s, true, true) RETURNING id",
                    (doc_id, content, chunk_hash, "Facts", "paragraph", department),
                )
                chunk_id = cur.fetchone()["id"]
                try:
                    embedding = embed_query(content)
                    cur.execute(
                        "UPDATE document_chunks SET embedding = %s WHERE id = %s",
                        (embedding, chunk_id),
                    )
                except Exception:
                    pass

            insert_doc(
                "J2 Credit Rules A", "policy", "underwriting", client_a,
                "A private credit rule for client A only.",
            )
            insert_doc(
                "J2 Credit Rules B", "policy", "general", client_b,
                "A private credit rule for client B only.",
            )
            insert_doc(
                "J2 Checklist", "checklist", "general", None,
                "A company-wide checklist on required documentation.",
            )
            insert_doc(
                "J2 Reference Guide", "reference", "general", None,
                "A recent company-wide reference guide with loan facts.",
            )
            insert_doc(
                "J2 Old Reference", "reference", "general", None,
                "An old company-wide reference from over a year ago.",
                created_days_ago=400,
            )

            conn.commit()

    admin_user = {
        "id": staff_id,
        "role": "super_admin",
        "department": "general",
        "allowed_departments": [],
    }
    staff_user = {
        "id": staff_id,
        "role": "loan_officer",
        "department": "general",
        "allowed_departments": ["general", "underwriting"],
    }

    yield {"client_a": client_a, "client_b": client_b, "staff_id": staff_id,
           "admin_user": admin_user, "staff_user": staff_user}

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM document_chunks WHERE document_id IN "
                "(SELECT id FROM documents WHERE source_path = %s)",
                (_MARKER,),
            )
            cur.execute(
                "DELETE FROM documents WHERE source_path = %s",
                (_MARKER,),
            )
            cur.execute(
                "DELETE FROM staff_client_assignments WHERE user_id = %s",
                (staff_id,),
            )
            cur.execute(
                "DELETE FROM clients WHERE email LIKE %s",
                ("j2_client_%@example.com",),
            )
            cur.execute(
                "DELETE FROM users WHERE email = %s",
                ("j2_staff@example.com",),
            )
            conn.commit()


class TestBuildFilterClause:
    """Unit-level checks of the SQL fragment builder (no DB needed)."""

    def test_none_returns_empty(self):
        clause, params = _build_filter_clause(None)
        assert clause == ""
        assert params == []

    def test_departments(self):
        from app.api.v1.search import SearchFilters
        clause, params = _build_filter_clause(SearchFilters(departments=["general"]))
        assert "d.department" in clause
        assert params == ["general"]

    def test_doc_types(self):
        from app.api.v1.search import SearchFilters
        clause, params = _build_filter_clause(SearchFilters(doc_types=["policy", "reference"]))
        assert "d.doc_type" in clause
        assert params == ["policy", "reference"]

    def test_date_range(self):
        from app.api.v1.search import SearchFilters
        clause, params = _build_filter_clause(
            SearchFilters(date_from="2026-01-01", date_to="2026-01-31")
        )
        assert "d.created_at >=" in clause
        assert "d.created_at <" in clause
        assert params == ["2026-01-01", "2026-01-31"]

    def test_client_id(self):
        from app.api.v1.search import SearchFilters
        clause, params = _build_filter_clause(SearchFilters(client_id=7))
        assert "d.client_id" in clause
        assert params == [7]


class TestFacetedFilters:
    """Each filter narrows the hybrid-search candidate set correctly."""

    def _search(self, query: str, user: dict, filters: dict | None):
        from app.api.v1.search import SearchFilters
        from app.db.postgres.session import acquire

        with acquire() as conn:
            return search_knowledge_base(
                conn=conn,
                sub_queries=[query],
                user=user,
                filters=SearchFilters(**(filters or {})),
            )

    def test_no_filter_returns_mixed_candidates(self, filter_db):
        result = self._search("credit rules", filter_db["admin_user"], None)
        titles = {c.title for c in result.candidates}
        assert "J2 Credit Rules A" in titles
        assert "J2 Credit Rules B" in titles

    def test_department_filter_narrows(self, filter_db):
        result = self._search(
            "credit rules",
            filter_db["admin_user"],
            {"departments": ["underwriting"]},
        )
        assert len(result.candidates) > 0
        for c in result.candidates:
            assert c.department == "underwriting"

    def test_doc_type_filter_narrows(self, filter_db):
        result = self._search(
            "documentation",
            filter_db["admin_user"],
            {"doc_types": ["checklist"]},
        )
        assert len(result.candidates) > 0
        for c in result.candidates:
            assert c.doc_type == "checklist"

    def test_client_id_filter_narrows(self, filter_db):
        result = self._search(
            "credit rules",
            filter_db["admin_user"],
            {"client_id": filter_db["client_a"]},
        )
        assert len(result.candidates) > 0
        for c in result.candidates:
            assert c.client_id == filter_db["client_a"]

    def test_date_range_excludes_old_docs(self, filter_db):
        result = self._search(
            "reference",
            filter_db["admin_user"],
            {"date_from": "2026-08-01"},
        )
        assert len(result.candidates) > 0
        for c in result.candidates:
            assert c.title == "J2 Reference Guide"

    def test_date_to_excludes_new_docs(self, filter_db):
        result = self._search(
            "reference",
            filter_db["admin_user"],
            {"date_to": "2026-01-01"},
        )
        assert len(result.candidates) > 0
        for c in result.candidates:
            assert c.title == "J2 Old Reference"

    def test_combined_filters_narrow(self, filter_db):
        result = self._search(
            "documentation",
            filter_db["admin_user"],
            {"doc_types": ["policy", "checklist"], "departments": ["general"]},
        )
        for c in result.candidates:
            assert c.doc_type in ("policy", "checklist")
            assert c.department == "general"


class TestFilterRbac:
    """Filters must never widen the RBAC scope (CLAUDE.md rule #1/rule #3)."""

    def test_staff_can_filter_to_assigned_client(self, filter_db):
        from app.db.postgres.session import acquire

        with acquire() as conn:
            result = search_knowledge_base(
                conn=conn,
                sub_queries=["credit rules"],
                user=filter_db["staff_user"],
                filters=None,
            )
        titles = {c.title for c in result.candidates}
        assert "J2 Credit Rules A" in titles
        assert "J2 Credit Rules B" not in titles  # client B not assigned

    def test_staff_cannot_filter_to_unassigned_client(self, filter_db):
        from app.api.v1.search import SearchFilters
        from app.db.postgres.session import acquire

        with acquire() as conn:
            result = search_knowledge_base(
                conn=conn,
                sub_queries=["credit rules"],
                user=filter_db["staff_user"],
                filters=SearchFilters(client_id=filter_db["client_b"]),
            )
        # Filtering to an unassigned client must yield nothing, not a leak.
        assert result.candidates == []

    def test_staff_filter_to_own_client_still_scoped(self, filter_db):
        from app.api.v1.search import SearchFilters
        from app.db.postgres.session import acquire

        with acquire() as conn:
            result = search_knowledge_base(
                conn=conn,
                sub_queries=["credit rules"],
                user=filter_db["staff_user"],
                filters=SearchFilters(client_id=filter_db["client_a"]),
            )
        assert len(result.candidates) > 0
        for c in result.candidates:
            assert c.client_id == filter_db["client_a"]
