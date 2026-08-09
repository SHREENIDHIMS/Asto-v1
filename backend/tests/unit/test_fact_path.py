"""Unit tests for the Phase 1 structured-fact path.

Covers (docs/architecture/dual_path_assistant.md §10):
- ``fact_router.classify_fact_intent``: phrase matching, ordering, and the
  fall-through rule for unsupported intents (``due_date``).
- ``fact_resolvers.resolve_fact``: RLS behavior — a client cannot read
  another client's case, a staff member cannot read an unassigned case,
  and an admin bypasses the client scope. Row-level scoping is asserted
  to be part of the SQL (the mocked cursor is fed scoped rows), never a
  post-hoc filter.
- ``fact_path.run_fact_path``: intent fall-through to the document path,
  client case auto-resolution, and no-answer packaging for inaccessible
  cases.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.query_processing.fact_router import classify_fact_intent

CLIENT_USER = {
    "id": 7,
    "email": "client@asto.local",
    "full_name": "Client",
    "is_active": True,
    "audience": "client",
    "client_id": 7,
    "role": "client",
    "department": None,
    "allowed_departments": [],
}

STAFF_USER = {
    "id": 3,
    "email": "loan@asto.local",
    "full_name": "Loan Officer",
    "is_active": True,
    "audience": "staff",
    "role": "loan_officer",
    "department": "general",
    "allowed_departments": [],
}

ADMIN_USER = {
    "id": 1,
    "email": "admin@asto.local",
    "full_name": "Admin",
    "is_active": True,
    "audience": "staff",
    "role": "admin",
    "department": "general",
    "allowed_departments": [],
}


def _row(d: dict) -> dict:
    return dict(d)


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------


class TestClassifyFactIntent:
    def test_case_status_phrase(self):
        assert classify_fact_intent("What is the current status of my application?") == "case_status"

    def test_missing_documents_phrase(self):
        assert classify_fact_intent("What documents are still missing?") == "missing_documents"

    def test_case_documents_phrase(self):
        assert classify_fact_intent("Show me the documents I submitted") == "case_documents"

    def test_case_property_phrase(self):
        assert classify_fact_intent("Which property is this for?") == "case_property"

    def test_timeline_phrase(self):
        assert classify_fact_intent("What's the history of my case?") == "case_timeline"

    def test_next_step_phrase(self):
        assert classify_fact_intent("What happens next?") == "case_next_step"

    def test_loan_amount_phrase(self):
        assert classify_fact_intent("What is my loan amount?") == "client_financials"

    def test_workflow_phrase(self):
        assert classify_fact_intent("Where is my file in the process?") == "workflow_step"

    def test_unsupported_intent_falls_through(self):
        # due_date is recognized in the phrase table but unsupported → None.
        assert classify_fact_intent("When is the deadline?") is None

    def test_unrelated_question_falls_through(self):
        assert classify_fact_intent("How does mortgage insurance work?") is None

    def test_specific_phrase_wins_over_generic(self):
        # "documents are outstanding" must map to missing_documents even
        # though "outstanding" could be noisy — order matters in the table.
        assert classify_fact_intent("What documents are outstanding?") == "missing_documents"

    def test_case_insensitive(self):
        assert classify_fact_intent("WHAT HAPPENS NEXT") == "case_next_step"


# ---------------------------------------------------------------------------
# Resolvers — RLS behavior
# ---------------------------------------------------------------------------


def _make_conn(case_row=None, *extra_fetchones):
    """Build a fake connection with a scripted cursor.

    ``case_row`` is returned by the first ``fetchone`` (the case-scoped
    lookup). Extra rows follow, then trailing ``None`` results so any
    resolver's additional ``fetchone`` calls (e.g. latest event) get a
    clean miss instead of raising ``StopIteration``.
    """
    cur = MagicMock()
    cur.fetchone.side_effect = [case_row] + list(extra_fetchones) + [None] * 20
    cur.fetchall.return_value = []
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


class TestFactResolversRLS:
    def test_client_sees_own_case_facts(self):
        from app.query_processing.fact_resolvers import FactContext, resolve_fact

        case = _row({
            "id": 10,
            "case_number": "C-100",
            "client_id": 7,
            "property_id": None,
            "loan_amount": 250000.00,
            "status": "active",
            "created_at": "2026-01-01T00:00:00Z",
        })
        conn = _make_conn(case)
        result = resolve_fact(conn, "case_status", FactContext(user=CLIENT_USER, case_id=10, client_id=7))
        assert result.accessible is True
        values = {f.label: f.value for f in result.facts}
        assert values["Status"] == "active"
        assert values["Loan amount"] == "250000.00"
        assert all(f.source.startswith("cases#") for f in result.facts[:1])

    def test_case_not_visible_is_inaccessible(self):
        from app.query_processing.fact_resolvers import FactContext, resolve_fact

        # The scoped query returns no row → the case is out of scope.
        conn = _make_conn(None)
        result = resolve_fact(conn, "case_status", FactContext(user=CLIENT_USER, case_id=99, client_id=7))
        assert result.accessible is False
        assert result.facts == []
        assert result.reason

    def test_staff_unassigned_case_inaccessible(self):
        from app.query_processing.fact_resolvers import FactContext, resolve_fact

        conn = _make_conn(None)
        result = resolve_fact(conn, "case_status", FactContext(user=STAFF_USER, case_id=99, client_id=None))
        assert result.accessible is False
        assert result.reason

    def test_admin_bypasses_client_scope(self):
        from app.query_processing.fact_resolvers import FactContext, resolve_fact

        case = _row({
            "id": 10,
            "case_number": "C-100",
            "client_id": 7,
            "property_id": None,
            "loan_amount": 250000.00,
            "status": "active",
            "created_at": "2026-01-01T00:00:00Z",
        })
        conn = _make_conn(case)
        result = resolve_fact(conn, "case_status", FactContext(user=ADMIN_USER, case_id=10, client_id=None))
        assert result.accessible is True
        assert result.facts

    def test_unsupported_resolver_inaccessible(self):
        from app.query_processing.fact_resolvers import FactContext, resolve_fact

        conn = _make_conn(None)
        result = resolve_fact(conn, "nope_not_a_resolver", FactContext(user=ADMIN_USER, case_id=10, client_id=None))
        assert result.accessible is False
        assert "no supported structured answer" in result.reason

    def test_missing_documents_uses_pending_scope(self):
        from app.query_processing.fact_resolvers import FactContext, resolve_fact

        case = _row({
            "id": 10,
            "case_number": "C-100",
            "client_id": 7,
            "property_id": None,
            "loan_amount": None,
            "status": "active",
            "created_at": "2026-01-01T00:00:00Z",
        })
        cur = MagicMock()
        # case lookup returns the case; documents query returns one pending doc.
        cur.fetchone.side_effect = [case, None]
        cur.fetchall.return_value = [_row({"id": 1, "title": "Paystubs", "doc_type": "income"})]
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        conn = MagicMock()
        conn.cursor.return_value = cur

        result = resolve_fact(conn, "missing_documents", FactContext(user=CLIENT_USER, case_id=10, client_id=7))
        assert result.accessible is True
        assert any(f.kind == "document" and f.value == "Paystubs" for f in result.facts)
        # The count fact is present too (deterministic aggregate, not fabricated).
        assert any(f.kind == "count" for f in result.facts)


# ---------------------------------------------------------------------------
# Orchestrator — routing decisions
# ---------------------------------------------------------------------------


class TestRunFactPath:
    def test_no_intent_falls_through_to_document_path(self):
        from app.query_processing.fact_path import run_fact_path

        conn = _make_conn(None)
        package = run_fact_path(conn, "how does mortgage insurance work?", CLIENT_USER, None, "how does mortgage insurance work?")
        assert package is None

    def test_fact_intent_builds_fact_package_for_client(self):
        from app.query_processing.fact_path import run_fact_path

        case = _row({
            "id": 10,
            "case_number": "C-100",
            "client_id": 7,
            "property_id": None,
            "loan_amount": 250000.00,
            "status": "active",
            "created_at": "2026-01-01T00:00:00Z",
        })
        conn = _make_conn(case)
        package = run_fact_path(conn, "what is my loan amount?", CLIENT_USER, 10, "what is my loan amount?")
        assert package is not None
        assert package.retrieval_path == "structured_fact"
        assert any(f.kind == "amount" and f.value == "250000.00" for f in package.facts)

    def test_client_auto_resolves_case_when_no_case_id(self):
        from app.query_processing.fact_path import run_fact_path

        cur = MagicMock()
        cur.fetchone.side_effect = [{"id": 42}, {
            "id": 42,
            "case_number": "C-42",
            "client_id": 7,
            "property_id": None,
            "loan_amount": 100000.00,
            "status": "active",
            "created_at": "2026-01-01T00:00:00Z",
        }, None]
        cur.fetchall.return_value = []
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        conn = MagicMock()
        conn.cursor.return_value = cur

        package = run_fact_path(conn, "what is my loan amount?", CLIENT_USER, None, "what is my loan amount?")
        assert package is not None
        assert any(f.kind == "amount" for f in package.facts)

    def test_inaccessible_case_returns_no_answer(self):
        from app.query_processing.fact_path import run_fact_path

        # Client asks about case 99 which they cannot see → no_answer.
        conn = _make_conn(None)
        package = run_fact_path(conn, "what is the status of my case?", CLIENT_USER, 99, "what is the status of my case?")
        assert package is not None
        assert package.routing == "no_answer"
        assert package.no_answer_reason

    def test_related_questions_populated_for_fact_answer(self):
        from app.query_processing.fact_path import run_fact_path

        case = _row({
            "id": 10,
            "case_number": "C-100",
            "client_id": 7,
            "property_id": None,
            "loan_amount": 250000.00,
            "status": "active",
            "created_at": "2026-01-01T00:00:00Z",
        })
        conn = _make_conn(case)
        package = run_fact_path(conn, "what is my loan amount?", CLIENT_USER, 10, "what is my loan amount?")
        assert package.related_questions  # role-appropriate follow-ups present
