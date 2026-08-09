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
STAFF2_EMAIL = "factpath.staff2@asto.test"
CASE1_NUMBER = "FACT-2026-0001"
CASE2_NUMBER = "FACT-2026-0002"
CASE3_NUMBER = "FACT-2026-0003"


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

            # A staff user assigned only to client2 (single accessible case).
            cur.execute(
                "INSERT INTO users (email, password_hash, full_name, role, department, allowed_departments) "
                "VALUES (%s, 'x', 'Factpath Staff 2', 'loan_officer', 'general', ARRAY['general']) RETURNING id",
                (STAFF2_EMAIL,),
            )
            staff2 = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO staff_client_assignments (user_id, client_id) VALUES (%s, %s)",
                (staff2, client2),
            )

            # A property + case per client (case2 has a property, case1 does not).
            cur.execute(
                "INSERT INTO properties (client_id, address, city, state, postal_code, property_type) "
                "VALUES (%s, '1 Factpath Ave', 'Factville', 'IL', '62565', 'single_family') RETURNING id",
                (client2,),
            )
            property2 = cur.fetchone()["id"]

            # A second property + case for client1 so property mention can be ambiguous.
            cur.execute(
                "INSERT INTO properties (client_id, address, city, state, postal_code, property_type) "
                "VALUES (%s, '99 Factpath Ave', 'Factville', 'IL', '62565', 'single_family') RETURNING id",
                (client1,),
            )
            property1 = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO properties (client_id, address, city, state, postal_code, property_type) "
                "VALUES (%s, '77 Factpath Ave', 'Factville', 'IL', '62565', 'single_family') RETURNING id",
                (client1,),
            )
            property3 = cur.fetchone()["id"]

            cur.execute(
                "INSERT INTO cases (case_number, client_id, property_id, loan_amount, status) "
                "VALUES (%s, %s, %s, 250000.00, 'under_review') RETURNING id",
                (CASE1_NUMBER, client1, property1),
            )
            case1 = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO cases (case_number, client_id, property_id, loan_amount, status) "
                "VALUES (%s, %s, %s, 185000.00, 'active') RETURNING id",
                (CASE2_NUMBER, client2, property2),
            )
            case2 = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO cases (case_number, client_id, property_id, loan_amount, status) "
                "VALUES (%s, %s, %s, 175000.00, 'active') RETURNING id",
                (CASE3_NUMBER, client1, property3),
            )
            case3 = cur.fetchone()["id"]

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
                "case3": case3,
                "property1": property1,
                "property2": property2,
                "property3": property3,
                "staff2": staff2,
            }

    yield ids

    # Cleanup in FK order.
    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM staff_client_assignments WHERE user_id IN (%s, %s)", (ids["staff"], ids["staff2"]))
            cur.execute("DELETE FROM case_notes WHERE case_id IN (%s, %s, %s)", (ids["case1"], ids["case2"], ids["case3"]))
            cur.execute("DELETE FROM workflows WHERE case_id IN (%s, %s, %s)", (ids["case1"], ids["case2"], ids["case3"]))
            cur.execute("DELETE FROM case_events WHERE case_id IN (%s, %s, %s)", (ids["case1"], ids["case2"], ids["case3"]))
            cur.execute("DELETE FROM approval_log WHERE document_id IN (SELECT id FROM documents WHERE client_id IN (%s, %s))", (ids["client1"], ids["client2"]))
            cur.execute("DELETE FROM document_chunks WHERE document_id IN (SELECT id FROM documents WHERE client_id IN (%s, %s))", (ids["client1"], ids["client2"]))
            cur.execute("DELETE FROM documents WHERE client_id IN (%s, %s)", (ids["client1"], ids["client2"]))
            cur.execute("DELETE FROM cases WHERE id IN (%s, %s, %s)", (ids["case1"], ids["case2"], ids["case3"]))
            cur.execute("DELETE FROM properties WHERE id IN (%s, %s, %s)", (ids["property1"], ids["property2"], ids["property3"]))
            cur.execute("DELETE FROM users WHERE id IN (%s, %s)", (ids["staff"], ids["staff2"]))
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


def _staff2_user(staff2_id: int) -> dict:
    return {
        "id": staff2_id,
        "email": STAFF2_EMAIL,
        "full_name": "Factpath Staff 2",
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

        # No case_id passed; client1 has two active cases, auto-resolve
        # picks the most recent one (case3, id DESC tie-break).
        with acquire() as conn:
            package = run_fact_path(
                conn=conn,
                normalized_query="how much is my loan?",
                user=_client_user(fact_db["client1"]),
                case_id=None,
                query_text="how much is my loan?",
            )

        assert package is not None
        assert any(f.kind == "amount" and f.value == "175000.00" for f in package.facts)

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

    def test_stream_emits_fact_events_then_result(self, fact_db):
        """SSE stream pushes a ``fact`` event per fact, then ``result``."""
        from fastapi.testclient import TestClient

        from app.dependencies import require_auth
        from app.main import app

        app.dependency_overrides[require_auth] = lambda: _client_user(fact_db["client1"])
        try:
            client = TestClient(app)
            with client.stream(
                "POST",
                "/api/v1/search/stream",
                json={
                    "query": "what is the current status of my application?",
                    "case_id": fact_db["case1"],
                },
            ) as response:
                body = "".join(response.iter_text())
        finally:
            app.dependency_overrides.pop(require_auth, None)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        events = [
            part
            for part in body.split("\n\n")
            if part.strip()
        ]
        import json

        event_types = []
        stages = []
        fact_events = []
        result_event = None
        for part in events:
            lines = part.splitlines()
            event = next(
                (l[len("event: ") :] for l in lines if l.startswith("event: ")),
                "message",
            )
            data = next(
                (l[len("data: ") :] for l in lines if l.startswith("data: ")),
                None,
            )
            event_types.append(event)
            if event == "status":
                stages.append(json.loads(data)["stage"])
            elif event == "fact":
                fact_events.append(data)
            elif event == "result":
                result_event = data

        # Status progression comes first.
        assert event_types[0] == "status"
        assert "packaging" in stages
        assert event_types[-1] == "result"

        # One fact event per fact, each a verbatim retrieved row.
        assert len(fact_events) >= 3

        status_fact = next(
            json.loads(e) for e in fact_events
            if json.loads(e)["label"] == "Status"
        )
        assert status_fact["value"] == "under_review"
        assert status_fact["source"].startswith("cases#")

        # The final result carries the same package as the sync endpoint.
        result = json.loads(result_event)
        assert result["retrieval_path"] == "structured_fact"
        assert result["routing"] == "answer"
        assert len(result["facts"]) == len(fact_events)

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

    def test_staff_resolves_case_by_property_mention(self, fact_db):
        """Staff with no case_id resolves via the property address in the query."""
        from app.query_processing.fact_path import run_fact_path

        with acquire() as conn:
            package = run_fact_path(
                conn=conn,
                normalized_query="what is the loan amount on 99 factpath ave?",
                user=_staff_user(fact_db["staff"]),
                case_id=None,
                query_text="what is the loan amount on 99 factpath ave?",
            )

        assert package is not None
        assert package.retrieval_path == "structured_fact"
        assert any(f.label == "Loan amount" and f.value == "250000.00" for f in package.facts)

    def test_staff_resolves_case_by_case_number_mention(self, fact_db):
        """Staff can name the case number directly without selecting it in the UI."""
        from app.query_processing.fact_path import run_fact_path

        with acquire() as conn:
            package = run_fact_path(
                conn=conn,
                normalized_query="what is the status of FACT-2026-0001?",
                user=_staff_user(fact_db["staff"]),
                case_id=None,
                query_text="what is the status of FACT-2026-0001?",
            )

        assert package is not None
        assert package.retrieval_path == "structured_fact"
        assert any(f.label == "Status" and f.value == "under_review" for f in package.facts)

    def test_client_name_mention_is_ambiguous_when_client_has_multiple_cases(self, fact_db):
        """A client-name mention with several cases asks which one via chips."""
        from app.query_processing.fact_path import run_fact_path

        # Client1 ("Factpath Client") has two cases → the name mention is
        # ambiguous and returns candidate chips for client1's cases only.
        with acquire() as conn:
            package = run_fact_path(
                conn=conn,
                normalized_query="what is the loan amount for Factpath Client?",
                user=_staff_user(fact_db["staff"]),
                case_id=None,
                query_text="what is the loan amount for Factpath Client?",
            )

        assert package is not None
        assert package.routing == "no_answer"
        chips = " | ".join(package.related_questions)
        assert CASE1_NUMBER in chips
        assert CASE3_NUMBER in chips
        assert CASE2_NUMBER not in chips  # client2's case out of scope

    def test_ambiguous_property_returns_candidate_case_chips(self, fact_db):
        """A property matching multiple accessible cases asks which one, via chips."""
        from app.query_processing.fact_path import run_fact_path

        # Client1 has two cases, both on "Factpath Ave" (99 and 77). The
        # staff member (assigned only to client1) asking about "factpath
        # ave" matches both → ambiguous → candidate-case chips.
        with acquire() as conn:
            package = run_fact_path(
                conn=conn,
                normalized_query="what is the loan amount on factpath ave?",
                user=_staff_user(fact_db["staff"]),
                case_id=None,
                query_text="what is the loan amount on factpath ave?",
            )

        assert package is not None
        assert package.routing == "no_answer"
        assert package.no_answer_reason == (
            "I found a few cases matching your question. Which case did you mean?"
        )
        # Both candidate case numbers appear as click-to-ask chips.
        chips = " | ".join(package.related_questions)
        assert CASE1_NUMBER in chips
        assert CASE3_NUMBER in chips
        assert CASE2_NUMBER not in chips  # client2's case is out of scope

    def test_mention_resolution_never_leaks_other_clients_case(self, fact_db):
        """A client mentioning another client's address never surfaces that case."""
        from app.query_processing.fact_path import run_fact_path

        # "1 Factpath Ave" is client2's address (number 1 ≠ client1's 99/77),
        # so the property tie-break rejects it for both of client1's
        # properties. The query falls back to client1's own most recent case
        # (case3, 175000) — never client2's case2 (185000).
        with acquire() as conn:
            package = run_fact_path(
                conn=conn,
                normalized_query="what is the loan amount on 1 factpath ave?",
                user=_client_user(fact_db["client1"]),
                case_id=None,
                query_text="what is the loan amount on 1 factpath ave?",
            )

        assert package is not None
        assert package.retrieval_path == "structured_fact"
        amounts = {f.value for f in package.facts if f.label == "Loan amount"}
        assert amounts == {"175000.00"}
        assert "185000.00" not in amounts

    def test_candidate_chips_click_through_to_facts(self, fact_db):
        """Candidate chips re-ask with the case number and resolve deterministically."""
        from app.query_processing.fact_path import _candidate_cases_package, run_fact_path

        # Build a synthetic ambiguous resolution for client1's two addresses.
        from app.query_processing.case_resolver import CaseCandidate, CaseResolution, resolve_case_from_query

        with acquire() as conn:
            resolution = resolve_case_from_query(
                conn,
                _staff_user(fact_db["staff"]),
                "what is the loan amount on 99 factpath ave?",
            )

        assert resolution.case_id is not None
        assert resolution.matched_by == "property"

        with acquire() as conn:
            package = _candidate_cases_package(
                "what is the loan amount on 99 factpath ave?",
                [CaseCandidate(case_id=resolution.case_id, case_number="FACT-2026-0001")],
            )

        assert package.routing == "no_answer"
        assert package.no_answer_reason == (
            "I found a few cases matching your question. Which case did you mean?"
        )
        chip = package.related_questions[0]
        assert "FACT-2026-0001" in chip

        # Clicking the chip re-enters mention resolution via the case number.
        with acquire() as conn:
            re_run = run_fact_path(
                conn=conn,
                normalized_query=chip,
                user=_staff_user(fact_db["staff"]),
                case_id=None,
                query_text=chip,
            )

        assert re_run is not None
        assert re_run.retrieval_path == "structured_fact"
        # Case1's loan amount (250000) is the resolved case's fact.
        assert any(f.label == "Loan amount" and f.value == "250000.00" for f in re_run.facts)

    def test_explicit_mention_beats_dropdown_case_id(self, fact_db):
        """A property mention in the text wins over the selected dropdown case.

        Staff (assigned to client1) selects case1 (99 Factpath, 250000) in
        the UI but asks about 77 Factpath (case3, 175000). The mention must
        resolve to case3 rather than silently answering about the selected
        case1. Both cases are in scope, so this is a precedence test, not a
        leak test.
        """
        from app.query_processing.fact_path import run_fact_path

        with acquire() as conn:
            package = run_fact_path(
                conn=conn,
                normalized_query="what is the loan amount on 77 factpath ave?",
                user=_staff_user(fact_db["staff"]),
                case_id=fact_db["case1"],
                query_text="what is the loan amount on 77 factpath ave?",
            )

        assert package is not None
        assert package.retrieval_path == "structured_fact"
        amounts = {f.value for f in package.facts if f.label == "Loan amount"}
        assert amounts == {"175000.00"}  # case3's loan, not case1's 250000

    def test_dropdown_disambiguates_ambiguous_mention(self, fact_db):
        """When a mention is ambiguous but the selected case is one candidate,
        the dropdown resolves it instead of offering chips."""
        from app.query_processing.fact_path import run_fact_path

        # "Factpath Ave" matches client1's two cases (99 and 77). The staff
        # member has case1 selected → the dropdown disambiguates to case1,
        # so no candidate chips and no ambiguity.
        with acquire() as conn:
            package = run_fact_path(
                conn=conn,
                normalized_query="what is the loan amount on factpath ave?",
                user=_staff_user(fact_db["staff"]),
                case_id=fact_db["case1"],
                query_text="what is the loan amount on factpath ave?",
            )

        assert package is not None
        assert package.retrieval_path == "structured_fact"
        assert package.routing == "answer"
        amounts = {f.value for f in package.facts if f.label == "Loan amount"}
        assert amounts == {"250000.00"}  # case1's loan

    def test_staff_single_case_auto_resolves_without_selection(self, fact_db):
        """Staff with exactly one accessible case gets an answer, no selection needed."""
        from app.query_processing.fact_path import run_fact_path

        # staff2 is assigned only to client2, who has one case (case2).
        # A vague question with no mention and no case_id auto-resolves to
        # that single accessible case instead of dead-ending.
        with acquire() as conn:
            package = run_fact_path(
                conn=conn,
                normalized_query="what is the loan amount on this case?",
                user=_staff2_user(fact_db["staff2"]),
                case_id=None,
                query_text="what is the loan amount on this case?",
            )

        assert package is not None
        assert package.retrieval_path == "structured_fact"
        assert package.routing == "answer"
        amounts = {f.value for f in package.facts if f.label == "Loan amount"}
        assert amounts == {"185000.00"}  # case2's loan, auto-resolved

    def test_staff_multiple_cases_vague_query_returns_suggestion_chips(self, fact_db):
        """Staff with several accessible cases and no mention gets suggestion chips.

        The staff fixture is assigned to client1, who has two cases
        (case1 + case3). A vague case question with no mention, no case_id
        must offer both cases as chips instead of a dead-end — the end user
        can't always pick the right case from a dropdown.
        """
        from app.query_processing.fact_path import run_fact_path

        with acquire() as conn:
            package = run_fact_path(
                conn=conn,
                normalized_query="what is the loan amount on this case?",
                user=_staff_user(fact_db["staff"]),
                case_id=None,
                query_text="what is the loan amount on this case?",
            )

        assert package is not None
        assert package.routing == "no_answer"
        assert package.no_answer_reason == (
            "I found a few cases matching your question. Which case did you mean?"
        )
        chips = " | ".join(package.related_questions)
        assert CASE1_NUMBER in chips
        assert CASE3_NUMBER in chips
        assert CASE2_NUMBER not in chips  # client2's case is out of scope


