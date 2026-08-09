"""Integration test for the Phase 1 structured-fact path.

Exercises the dual-path router against a live Postgres instance
(docs/architecture/dual_path_assistant.md §10):

- Client fact query → ``retrieval_path="structured_fact"`` package with
  verbatim facts and explicit sources.
- Client cannot read another client's case → ``no_answer`` package.
- Staff assigned to a client sees facts; unassigned staff get no_answer.
- A non-fact query falls through to the document path (``None``).
- Full HTTP round-trip through ``/search/`` returns the fact package.

Requires a running Postgres with the asto_assistant schema; skips
gracefully when no DB is available (same pattern as test_end_to_end.py).
"""

from __future__ import annotations

import pytest

from app.db.postgres.session import acquire

CLIENT_EMAIL = "factpath.client@asto.test"
CLIENT2_EMAIL = "factpath.client2@asto.test"
STAFF_EMAIL = "factpath.staff@asto.test"
CASE1_NUMBER = "FACT-2026-0001"
CASE2_NUMBER = "FACT-2026-0002"


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
def fact_db():
    """Seed isolated operational rows for fact-path tests, then clean up."""
    from app.db.postgres.schema import ensure_schema

    ensure_schema()

    with acquire() as conn:
        with conn.cursor() as cur:
            # Two clients so we can assert cross-client isolation.
            cur.execute(
                "INSERT INTO clients (email, full_name, password_hash, is_active) "
                "VALUES (%s, %s, 'x', true) RETURNING id",
                (CLIENT_EMAIL, "Factpath Client"),
            )
            client1 = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO clients (email, full_name, password_hash, is_active) "
                "VALUES (%s, %s, 'x', true) RETURNING id",
                (CLIENT2_EMAIL, "Other Client"),
            )
            client2 = cur.fetchone()["id"]

            # A staff user assigned only to client1.
            cur.execute(
                "INSERT INTO users (email, password_hash, full_name, role, department, allowed_departments) "
                "VALUES (%s, 'x', 'Factpath Staff', 'loan_officer', 'general', ARRAY['general']) RETURNING id",
                (STAFF_EMAIL,),
            )
            staff = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO staff_client_assignments (user_id, client_id) VALUES (%s, %s)",
                (staff, client1),
            )

            # A property + case per client (case2 has a property, case1 does not).
            cur.execute(
                "INSERT INTO properties (client_id, address, city, state, postal_code, property_type) "
                "VALUES (%s, '1 Factpath Ave', 'Factville', 'IL', '62565', 'single_family') RETURNING id",
                (client2,),
            )
            property2 = cur.fetchone()["id"]

            cur.execute(
                "INSERT INTO cases (case_number, client_id, property_id, loan_amount, status) "
                "VALUES (%s, %s, NULL, 250000.00, 'under_review') RETURNING id",
                (CASE1_NUMBER, client1),
            )
            case1 = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO cases (case_number, client_id, property_id, loan_amount, status) "
                "VALUES (%s, %s, %s, 185000.00, 'active') RETURNING id",
                (CASE2_NUMBER, client2, property2),
            )
            case2 = cur.fetchone()["id"]

            cur.execute(
                "INSERT INTO case_events (case_id, status, note) "
                "VALUES (%s, 'submitted', 'Application submitted online')",
                (case1,),
            )
            cur.execute(
                "INSERT INTO case_events (case_id, status, note) "
                "VALUES (%s, 'under_review', 'Documents received; underwriting review in progress')",
                (case1,),
            )
            cur.execute(
                "INSERT INTO case_events (case_id, status, note) "
                "VALUES (%s, 'active', 'Loan approved and active')",
                (case2,),
            )

            # One pending document on client1's case (missing-documents intent).
            cur.execute(
                "INSERT INTO documents "
                "(title, doc_type, department, client_id, approval_status, is_active, is_approved, version) "
                "VALUES (%s, 'income', 'general', %s, 'pending', true, false, 1) RETURNING id",
                ("Pay Stubs (Pending Review)", client1),
            )
            doc_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO document_chunks "
                "(document_id, content, content_hash, chunk_type, department, is_active, is_approved, approval_status) "
                "VALUES (%s, 'pay stub income verification content', %s, 'paragraph', 'general', true, false, 'pending') "
                "RETURNING id",
                (doc_id, "factpath-paystubs-hash"),
            )
            cur.fetchone()

            # An active workflow on case1.
            cur.execute(
                "INSERT INTO workflows (title, department, case_id, status, assigned_to) "
                "VALUES (%s, 'general', %s, 'in_progress', %s) RETURNING id",
                ("Income verification", case1, staff),
            )
            cur.fetchone()

            conn.commit()

            ids = {
                "client1": client1,
                "client2": client2,
                "staff": staff,
                "case1": case1,
                "case2": case2,
                "property2": property2,
            }

    yield ids

    # Cleanup in FK order.
    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM staff_client_assignments WHERE user_id = %s", (ids["staff"],))
            cur.execute("DELETE FROM case_notes WHERE case_id IN (%s, %s)", (ids["case1"], ids["case2"]))
            cur.execute("DELETE FROM workflows WHERE case_id IN (%s, %s)", (ids["case1"], ids["case2"]))
            cur.execute("DELETE FROM case_events WHERE case_id IN (%s, %s)", (ids["case1"], ids["case2"]))
            cur.execute("DELETE FROM approval_log WHERE document_id IN (SELECT id FROM documents WHERE client_id IN (%s, %s))", (ids["client1"], ids["client2"]))
            cur.execute("DELETE FROM document_chunks WHERE document_id IN (SELECT id FROM documents WHERE client_id IN (%s, %s))", (ids["client1"], ids["client2"]))
            cur.execute("DELETE FROM documents WHERE client_id IN (%s, %s)", (ids["client1"], ids["client2"]))
            cur.execute("DELETE FROM cases WHERE id IN (%s, %s)", (ids["case1"], ids["case2"]))
            cur.execute("DELETE FROM properties WHERE id = %s", (ids["property2"],))
            cur.execute("DELETE FROM users WHERE id = %s", (ids["staff"],))
            cur.execute("DELETE FROM clients WHERE id IN (%s, %s)", (ids["client1"], ids["client2"]))
            conn.commit()


def _client_user(client_id: int) -> dict:
    return {
        "id": client_id,
        "email": CLIENT_EMAIL,
        "full_name": "Factpath Client",
        "is_active": True,
        "audience": "client",
        "client_id": client_id,
        "role": "client",
        "department": None,
        "allowed_departments": [],
    }


def _staff_user(staff_id: int) -> dict:
    return {
        "id": staff_id,
        "email": STAFF_EMAIL,
        "full_name": "Factpath Staff",
        "is_active": True,
        "audience": "staff",
        "role": "loan_officer",
        "department": "general",
        "allowed_departments": ["general"],
    }


class TestFactPathIntegration:
    def test_client_case_status_returns_facts(self, fact_db):
        from app.query_processing.fact_path import run_fact_path

        with acquire() as conn:
            package = run_fact_path(
                conn=conn,
                normalized_query="what is the current status of my application?",
                user=_client_user(fact_db["client1"]),
                case_id=fact_db["case1"],
                query_text="what is the current status of my application?",
            )

        assert package is not None
        assert package.retrieval_path == "structured_fact"
        values = {f.label: f.value for f in package.facts}
        assert values["Status"] == "under_review"
        assert values["Case number"] == CASE1_NUMBER
        assert values["Loan amount"] == "250000.00"
        # Latest event note is a verbatim stored value with a source.
        assert any(f.kind == "note" for f in package.facts)
        assert all(f.source and "#" in f.source for f in package.facts)
        assert package.related_questions  # role-appropriate follow-ups

    def test_client_cannot_read_other_clients_case(self, fact_db):
        from app.query_processing.fact_path import run_fact_path

        # Client1 asks about client2's case id → no_answer, not a leak.
        with acquire() as conn:
            package = run_fact_path(
                conn=conn,
                normalized_query="what is the status of my case?",
                user=_client_user(fact_db["client1"]),
                case_id=fact_db["case2"],
                query_text="what is the status of my case?",
            )

        assert package is not None
        assert package.routing == "no_answer"
        assert package.no_answer_reason
        assert package.facts == []

    def test_client_auto_resolves_own_most_recent_case(self, fact_db):
        from app.query_processing.fact_path import run_fact_path

        # No case_id passed; client1 has exactly one active case.
        with acquire() as conn:
            package = run_fact_path(
                conn=conn,
                normalized_query="how much is my loan?",
                user=_client_user(fact_db["client1"]),
                case_id=None,
                query_text="how much is my loan?",
            )

        assert package is not None
        assert any(f.kind == "amount" and f.value == "250000.00" for f in package.facts)

    def test_assigned_staff_sees_facts(self, fact_db):
        from app.query_processing.fact_path import run_fact_path

        with acquire() as conn:
            package = run_fact_path(
                conn=conn,
                normalized_query="what happens next?",
                user=_staff_user(fact_db["staff"]),
                case_id=fact_db["case1"],
                query_text="what happens next?",
            )

        assert package is not None
        assert package.retrieval_path == "structured_fact"
        assert any(f.kind == "workflow" for f in package.facts)

    def test_unassigned_staff_gets_no_answer(self, fact_db):
        from app.query_processing.fact_path import run_fact_path

        # Staff is only assigned to client1; client2's case is out of scope.
        with acquire() as conn:
            package = run_fact_path(
                conn=conn,
                normalized_query="what is the status of my case?",
                user=_staff_user(fact_db["staff"]),
                case_id=fact_db["case2"],
                query_text="what is the status of my case?",
            )

        assert package is not None
        assert package.routing == "no_answer"

    def test_non_fact_query_falls_through_to_document_path(self, fact_db):
        from app.query_processing.fact_path import run_fact_path

        with acquire() as conn:
            package = run_fact_path(
                conn=conn,
                normalized_query="how does mortgage insurance work?",
                user=_client_user(fact_db["client1"]),
                case_id=fact_db["case1"],
                query_text="how does mortgage insurance work?",
            )

        assert package is None  # caller runs the document path instead

    def test_missing_documents_intent_returns_pending_docs(self, fact_db):
        from app.query_processing.fact_path import run_fact_path

        with acquire() as conn:
            package = run_fact_path(
                conn=conn,
                normalized_query="what documents are still missing?",
                user=_client_user(fact_db["client1"]),
                case_id=fact_db["case1"],
                query_text="what documents are still missing?",
            )

        assert package is not None
        assert any(
            f.kind == "document" and f.value == "Pay Stubs (Pending Review)"
            for f in package.facts
        )

    def test_http_round_trip_returns_fact_package(self, fact_db):
        """Full request → _run_pipeline → fact package over HTTP."""
        from fastapi.testclient import TestClient

        from app.dependencies import require_auth
        from app.main import app

        app.dependency_overrides[require_auth] = lambda: _client_user(fact_db["client1"])
        try:
            client = TestClient(app)
            response = client.post(
                "/api/v1/search/",
                json={
                    "query": "what is the current status of my application?",
                    "case_id": fact_db["case1"],
                },
            )
        finally:
            app.dependency_overrides.pop(require_auth, None)

        assert response.status_code == 200
        data = response.json()
        assert data["retrieval_path"] == "structured_fact"
        assert data["routing"] == "answer"
        assert len(data["facts"]) >= 3
        status_fact = next(f for f in data["facts"] if f["label"] == "Status")
        assert status_fact["value"] == "under_review"
        assert status_fact["source"].startswith("cases#")

    def test_ambiguous_personal_query_returns_clarify_chips(self, fact_db):
        """A personal-but-ambiguous query asks to rephrase with click-to-ask chips."""
        from app.query_processing.fact_path import CLARIFY_PROMPT, run_fact_path

        with acquire() as conn:
            package = run_fact_path(
                conn=conn,
                normalized_query="is my loan being processed",
                user=_client_user(fact_db["client1"]),
                case_id=fact_db["case1"],
                query_text="is my loan being processed",
            )

        assert package is not None
        assert package.routing == "no_answer"
        assert package.no_answer_reason == CLARIFY_PROMPT
        assert package.answer == ""
        # The chips are the frontend click-to-ask affordances.
        assert "What is the current status of my case?" in package.related_questions
        assert "What documents are still missing?" in package.related_questions
        assert "What is the loan amount on this case?" in package.related_questions

    def test_related_question_chips_click_through_to_facts(self, fact_db):
        """Every click-to-ask chip resolves to a real structured-fact answer.

        Related questions double as the clarify prompt's chips; the round
        trip must actually work — clicking a chip re-asks it and gets a
        fact package, not another dead-end.
        """
        from app.query_processing.fact_path import RELATED_QUESTIONS_BY_INTENT, run_fact_path

        chips = RELATED_QUESTIONS_BY_INTENT["case_status"]
        assert len(chips) == 3

        for chip in chips:
            with acquire() as conn:
                package = run_fact_path(
                    conn=conn,
                    normalized_query=chip,
                    user=_client_user(fact_db["client1"]),
                    case_id=fact_db["case1"],
                    query_text=chip,
                )
            assert package is not None, f"chip {chip!r} returned no package"
            assert package.retrieval_path == "structured_fact", f"chip {chip!r} did not hit the fact path"
            assert package.routing == "answer", f"chip {chip!r} did not resolve to a full answer"
            assert package.facts, f"chip {chip!r} returned no facts"
            assert all(f.source and "#" in f.source for f in package.facts)
