"""Integration test for RBAC pre-filter enforcement (CLAUDE.md rule #1).

Primary enforcement is the Postgres WHERE clause: a chunk the test user is
NOT permitted to see must never reach the reranker or the response package.
We verify this at the SQL level against a live database — NOT by mocking
``search_knowledge_base`` (the earlier version patched the very function
that owns the WHERE clause, proving nothing).

Scenarios:
- staff sees department-scoped + company-wide + assigned-client docs,
- staff does NOT see out-of-department or unassigned-client docs,
- client sees only their own docs,
- the restricted chunk is absent from the returned candidates entirely
  (i.e. it was filtered in SQL, not removed downstream).
"""

from __future__ import annotations

import hashlib
import uuid

import pytest

from app.search.metadata_filters import get_search_filter

_MARKER = uuid.uuid4().hex[:8]

_STAFF_USER = {
    "id": None,  # filled in by the fixture
    "role": "loan_officer",
    "department": "general",
    "allowed_departments": ["general"],
}
_CLIENT_USER = {"audience": "client", "client_id": None, "role": "client"}


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
def rbac_db():
    """Seed cross-department + cross-client docs, then clean up."""
    from app.db.postgres.session import acquire
    from app.db.postgres.schema import ensure_schema

    ensure_schema()

    ids: dict[str, int] = {}
    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO clients (email, password_hash, full_name, is_active) "
                "VALUES (%s, 'x', 'Rbac A', true) RETURNING id",
                (f"rbac_a_{_MARKER}@example.com",),
            )
            ids["client_a"] = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO clients (email, password_hash, full_name, is_active) "
                "VALUES (%s, 'x', 'Rbac B', true) RETURNING id",
                (f"rbac_b_{_MARKER}@example.com",),
            )
            ids["client_b"] = cur.fetchone()["id"]

            cur.execute(
                "INSERT INTO users (email, password_hash, role, department, "
                "allowed_departments, is_active) "
                "VALUES (%s, 'x', 'loan_officer', 'general', "
                "ARRAY['general'], true) RETURNING id",
                (f"rbac_staff_{_MARKER}@example.com",),
            )
            ids["staff"] = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO staff_client_assignments (user_id, client_id) "
                "VALUES (%s, %s)",
                (ids["staff"], ids["client_a"]),
            )

            def insert_doc(title: str, department: str, client_id: int | None,
                           content: str) -> int:
                cur.execute(
                    "INSERT INTO documents (title, doc_type, department, client_id, "
                    "source_path, is_active, is_approved, version) "
                    "VALUES (%s, 'policy', %s, %s, %s, true, true, 1) RETURNING id",
                    (title, department, client_id, _MARKER),
                )
                doc_id = cur.fetchone()["id"]
                chunk_hash = hashlib.md5(content.encode()).hexdigest()
                cur.execute(
                    "INSERT INTO document_chunks "
                    "(document_id, content, content_hash, section, chunk_type, "
                    "department, is_active, is_approved) "
                    "VALUES (%s, %s, %s, %s, 'paragraph', %s, true, true) RETURNING id",
                    (doc_id, content, chunk_hash, "Facts", department),
                )
                chunk_id = cur.fetchone()["id"]
                from app.search.pgvector_search import embed_query
                try:
                    embedding = embed_query(content)
                    cur.execute(
                        "UPDATE document_chunks SET embedding = %s WHERE id = %s",
                        (embedding, chunk_id),
                    )
                except Exception:
                    pass
                return chunk_id

            ids["chunk_general"] = insert_doc(
                f"Rbac {_MARKER} General", "general", None,
                f"{_MARKER} companywide eligibility policy.",
            )
            ids["chunk_underwriting"] = insert_doc(
                f"Rbac {_MARKER} Underwriting", "underwriting", None,
                f"{_MARKER} internal underwriting guidelines.",
            )
            ids["chunk_client_a"] = insert_doc(
                f"Rbac {_MARKER} Client A", "general", ids["client_a"],
                f"{_MARKER} credit rule private to client A.",
            )
            ids["chunk_client_b"] = insert_doc(
                f"Rbac {_MARKER} Client B", "general", ids["client_b"],
                f"{_MARKER} credit rule private to client B.",
            )
        conn.commit()

    _STAFF_USER["id"] = ids["staff"]
    _CLIENT_USER["client_id"] = ids["client_a"]
    yield ids

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM documents WHERE source_path = %s", (_MARKER,)
            )
            cur.execute(
                "DELETE FROM staff_client_assignments WHERE user_id = %s",
                (ids["staff"],),
            )
            cur.execute("DELETE FROM users WHERE id = %s", (ids["staff"],))
            cur.execute(
                "DELETE FROM clients WHERE id IN (%s, %s)",
                (ids["client_a"], ids["client_b"]),
            )
        conn.commit()


class TestRBACPreFilter:
    def test_admin_sees_all_departments(self):
        clause, params = get_search_filter({
            "role": "super_admin",
            "department": "compliance",
            "allowed_departments": [],
        })
        assert clause == ""
        assert params == []

    def test_loan_officer_only_sees_allowed(self):
        clause, params = get_search_filter({
            "role": "loan_officer",
            "department": "general",
            "allowed_departments": ["compliance"],
        })
        assert "department" in clause
        assert "general" in params
        assert "compliance" in params
        assert "underwriting" not in params

    def test_unauthenticated_user_gets_no_results(self):
        clause, params = get_search_filter(None)
        assert clause == "1=0"
        assert params == []


class TestRbacPrefilterLiveDB:
    """SQL-level enforcement against a live Postgres (rule #1).

    The restricted chunk must be absent from the candidates the query
    returns — it never reaches the reranker because the WHERE clause
    excluded it.
    """

    def _search(self, user: dict, query: str):
        from app.db.postgres.session import acquire
        from app.search.hybrid_orchestrator import search_knowledge_base

        with acquire() as conn:
            result = search_knowledge_base(conn, [query], user=user)
        return result

    def test_staff_never_sees_restricted_departments_or_clients(self, rbac_db):
        ids = rbac_db
        result = self._search(_STAFF_USER, _MARKER)
        chunk_ids = {c.chunk_id for c in result.candidates}

        # Visible: company-wide general doc + assigned client A doc.
        assert ids["chunk_general"] in chunk_ids
        assert ids["chunk_client_a"] in chunk_ids
        # Forbidden: out-of-department (underwriting) + unassigned client B.
        assert ids["chunk_underwriting"] not in chunk_ids
        assert ids["chunk_client_b"] not in chunk_ids

    def test_client_sees_only_own_docs(self, rbac_db):
        ids = rbac_db
        result = self._search(_CLIENT_USER, _MARKER)
        chunk_ids = {c.chunk_id for c in result.candidates}

        assert ids["chunk_client_a"] in chunk_ids
        assert ids["chunk_client_b"] not in chunk_ids
        assert ids["chunk_general"] not in chunk_ids
        assert ids["chunk_underwriting"] not in chunk_ids

    def test_admin_sees_everything(self, rbac_db):
        ids = rbac_db
        admin = {
            "role": "super_admin", "department": "general",
            "allowed_departments": [],
        }
        result = self._search(admin, _MARKER)
        chunk_ids = {c.chunk_id for c in result.candidates}
        assert chunk_ids == {
            ids["chunk_general"],
            ids["chunk_underwriting"],
            ids["chunk_client_a"],
            ids["chunk_client_b"],
        }