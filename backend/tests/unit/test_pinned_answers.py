"""Unit tests for pinned answers: normalization, validation, lookup,
payload rebuild, admin CRUD endpoints, and the serving hook."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.response.pinned_answers import (
    find_pinned_answer,
    normalize_for_pin,
    pinned_payload,
    validate_pin_package,
)

ADMIN_USER = {
    "id": 1,
    "email": "admin@asto.local",
    "full_name": "Admin User",
    "is_active": True,
    "audience": "staff",
    "role": "admin",
    "department": "general",
    "allowed_departments": ["general"],
}

STAFF_USER = {
    "id": 2,
    "email": "staff@asto.local",
    "full_name": "Dana Officer",
    "is_active": True,
    "audience": "staff",
    "role": "loan_officer",
    "department": "general",
    "allowed_departments": ["general"],
}

GOOD_PACKAGE = {
    "title": "APR explained",
    "answer": "APR is the annual rate.",
    "routing": "answer",
    "confidence": 0.91,
    "excerpts": [
        {
            "text": "APR is the annual rate charged for borrowing.",
            "source": {"title": "Mortgage Basics", "section": "Rates", "chunk_type": "text"},
            "confidence": 0.9,
        }
    ],
    "summary": [],
    "facts": [],
}


def _conn() -> MagicMock:
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cur = conn.cursor.return_value
    cur.__enter__.return_value = cur
    return conn


def _authorized(user: dict):
    from app.main import app
    from app.dependencies import require_auth

    app.dependency_overrides[require_auth] = lambda: user
    return TestClient(app)


def _cleanup() -> None:
    from app.main import app
    from app.dependencies import require_auth

    app.dependency_overrides.pop(require_auth, None)


class TestNormalizeForPin:
    def test_case_whitespace_and_punctuation_insensitive(self):
        assert normalize_for_pin("What is an APR?") == normalize_for_pin(
            "  what   is an apr "
        )
        assert normalize_for_pin('"Escrow waiver!"') == normalize_for_pin(
            "escrow waiver"
        )

    def test_distinct_queries_stay_distinct(self):
        assert normalize_for_pin("apr") != normalize_for_pin("escrow")

    def test_empty_normalizes_to_empty(self):
        assert normalize_for_pin("  ?!  ") == ""


class TestValidatePinPackage:
    def test_good_package_passes(self):
        assert validate_pin_package(GOOD_PACKAGE) == []

    def test_rejects_non_answer_routing(self):
        pkg = {**GOOD_PACKAGE, "routing": "no_answer"}
        problems = validate_pin_package(pkg)
        assert any("routing" in p for p in problems)

    def test_rejects_empty_content(self):
        problems = validate_pin_package({"routing": "answer"})
        assert len(problems) == 1
        assert "no excerpts" in problems[0]

    def test_rejects_excerpt_without_text_or_source(self):
        problems = validate_pin_package({
            "routing": "answer",
            "excerpts": [{"text": "  ", "source": {}}, {"text": "x"}],
        })
        assert any("excerpt[0]" in p for p in problems)
        assert any("excerpt[1]" in p for p in problems)


class TestPinnedPayload:
    def test_fresh_response_id_and_verbatim_content(self):
        row = {
            "id": 3,
            "query": "What is an APR?",
            "audience": "any",
            "package": GOOD_PACKAGE,
            "confidence": 0.95,
            "source_response_id": "abc123",
        }
        payload = pinned_payload(row, "what is an apr")
        assert payload["pinned"] is True
        assert payload["routing"] == "answer"
        assert payload["response_id"] != "abc123"  # fresh per serve
        assert payload["excerpts"][0]["text"] == GOOD_PACKAGE["excerpts"][0]["text"]
        assert payload["confidence"] == 0.95

    def test_missing_package_fields_default(self):
        row = {
            "id": 4,
            "query": "q",
            "audience": "staff",
            "package": None,
            "confidence": None,
            "source_response_id": None,
        }
        payload = pinned_payload(row, "q")
        assert payload["excerpts"] == []
        assert payload["summary"] == []
        assert payload["facts"] == []
        assert payload["confidence"] == 1.0


class TestFindPinnedAnswer:
    def test_audience_scoping_in_sql_where(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = None
        find_pinned_answer(conn, "what is an apr", "client")
        sql = cur.execute.call_args.args[0]
        params = cur.execute.call_args.args[1]
        # Rule 1: audience filter must be part of the WHERE clause.
        assert "audience IN ('any', %s)" in sql
        assert "is_active = true" in sql
        assert params[0] == normalize_for_pin("what is an apr")
        assert params[1] == "client"

    def test_blank_query_short_circuits(self):
        conn = _conn()
        assert find_pinned_answer(conn, "  ?", "staff") is None
        conn.cursor.assert_not_called()


class TestPinnedAnswerEndpoints:
    def test_create_requires_admin(self):
        try:
            response = _authorized(STAFF_USER).post(
                "/api/v1/admin/pinned-answers",
                json={
                    "query": "what is an apr",
                    "response_id": "resp-1",
                    "package": GOOD_PACKAGE,
                },
            )
            assert response.status_code == 403
        finally:
            _cleanup()

    def test_create_requires_existing_successful_audit_row(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"outcome": "no_answer"},  # audit lookup: wrong outcome
        ]
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = _authorized(ADMIN_USER).post(
                    "/api/v1/admin/pinned-answers",
                    json={
                        "query": "what is an apr",
                        "response_id": "resp-2",
                        "package": GOOD_PACKAGE,
                    },
                )
            assert response.status_code == 422
            assert "only fully answered" in response.json()["detail"]
        finally:
            _cleanup()

    def test_create_unknown_response_id_404(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = None
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = _authorized(ADMIN_USER).post(
                    "/api/v1/admin/pinned-answers",
                    json={
                        "query": "what is an apr",
                        "response_id": "missing",
                        "package": GOOD_PACKAGE,
                    },
                )
            assert response.status_code == 404
        finally:
            _cleanup()

    def test_create_success_upserts_with_normalized_key(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"outcome": "answer"},
            {
                "id": 9,
                "query": "What is an APR?",
                "audience": "staff",
                "package": GOOD_PACKAGE,
                "confidence": 0.91,
                "source_response_id": "resp-3",
                "is_active": True,
                "created_at": None,
                "updated_at": None,
            },
        ]
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = _authorized(ADMIN_USER).post(
                    "/api/v1/admin/pinned-answers",
                    json={
                        "query": "What is an APR?",
                        "response_id": "resp-3",
                        "audience": "any",
                        "package": GOOD_PACKAGE,
                    },
                )
            assert response.status_code == 201
            data = response.json()
            assert data["id"] == 9
            assert data["excerpt_count"] == 1
            insert_sql = cur.execute.call_args_list[1].args[0]
            assert "ON CONFLICT (query_norm) DO UPDATE" in insert_sql
            params = cur.execute.call_args_list[1].args[1]
            assert params[1] == normalize_for_pin("What is an APR?")
            assert params[2] == "any"
        finally:
            _cleanup()

    def test_create_rejects_invalid_package(self):
        conn = _conn()
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = _authorized(ADMIN_USER).post(
                    "/api/v1/admin/pinned-answers",
                    json={
                        "query": "q",
                        "response_id": "resp-4",
                        "package": {"routing": "partial", "excerpts": []},
                    },
                )
            assert response.status_code == 422
        finally:
            _cleanup()

    def test_patch_toggle_active(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.rowcount = 1
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = _authorized(ADMIN_USER).patch(
                    "/api/v1/admin/pinned-answers/9",
                    json={"is_active": False},
                )
            assert response.status_code == 200
            sql = cur.execute.call_args.args[0]
            assert "is_active = %s" in sql
        finally:
            _cleanup()

    def test_patch_not_found(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.rowcount = 0
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = _authorized(ADMIN_USER).patch(
                    "/api/v1/admin/pinned-answers/99",
                    json={"is_active": False},
                )
            assert response.status_code == 404
        finally:
            _cleanup()

    def test_delete(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.rowcount = 1
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = _authorized(ADMIN_USER).delete(
                    "/api/v1/admin/pinned-answers/9"
                )
            assert response.status_code == 204
        finally:
            _cleanup()


class TestPipelineServingHook:
    def test_matching_pin_served_without_retrieval(self):
        from app.main import app
        from app.api.v1.search import SearchRequest

        row = {
            "id": 5,
            "query": "What is an APR?",
            "audience": "any",
            "package": GOOD_PACKAGE,
            "confidence": 0.93,
            "source_response_id": "orig-1",
        }

        def _fail_search(*args, **kwargs):
            raise AssertionError("retrieval must not run for a pinned hit")

        with patch(
            "app.api.v1.search.find_pinned_answer", return_value=row
        ), patch("app.api.v1.search.search_knowledge_base", side_effect=_fail_search):
            from app.api.v1.search import _run_pipeline

            response = _run_pipeline(
                "What is an APR?", STAFF_USER, case_id=None, filters=None
            )
        assert response.pinned is True
        assert response.routing == "answer"
        assert response.excerpts[0]["text"] == GOOD_PACKAGE["excerpts"][0]["text"]

    def test_pin_miss_falls_through_to_pipeline(self):
        # With no pin found (autouse mock returns None), the pipeline must
        # proceed past the hook — reaching retrieval proves fall-through.
        with patch(
            "app.api.v1.search.find_pinned_answer", return_value=None
        ), patch(
            "app.api.v1.search.search_knowledge_base",
            side_effect=AssertionError("should be reached"),
        ) as mock_search:
            from app.api.v1.search import _run_pipeline

            try:
                _run_pipeline("some other query", STAFF_USER)
            except AssertionError:
                pass  # raised by our sentinel deeper in the pipeline
            mock_search.assert_called()
