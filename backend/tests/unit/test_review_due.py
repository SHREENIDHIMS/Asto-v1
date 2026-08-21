"""Unit tests for document review scheduling (review_due staleness)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.documents.review import overdue_review_documents, stale_source_titles

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


class TestStaleSourceTitles:
    def test_returns_titles_in_retrieval_order_deduped(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchall.return_value = [
            {"id": 2, "title": "Rate Sheet"},
            {"id": 1, "title": "SOP: Approvals"},
        ]
        titles = stale_source_titles(conn, [1, 2, 1])
        assert titles == ["SOP: Approvals", "Rate Sheet"]
        sql = cur.execute.call_args.args[0]
        assert "review_due < CURRENT_DATE" in sql

    def test_empty_ids_skip_query(self):
        conn = _conn()
        assert stale_source_titles(conn, [0, None]) == []
        conn.cursor.assert_not_called()


class TestOverdueReviewDocuments:
    def test_orders_most_overdue_first(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchall.return_value = [
            {"id": 1, "title": "Old SOP", "days_overdue": 30}
        ]
        docs = overdue_review_documents(conn, limit=50)
        assert docs[0]["days_overdue"] == 30
        params = cur.execute.call_args.args[1]
        assert params == (50,)
        sql = cur.execute.call_args.args[0]
        assert "approval_status = 'approved'" in sql


class TestReviewDueEndpoints:
    def test_set_review_due_requires_admin(self):
        try:
            response = _authorized(STAFF_USER).put(
                "/api/v1/admin/documents/5/review-due",
                json={"review_due": "2026-09-01"},
            )
            assert response.status_code == 403
        finally:
            _cleanup()

    def test_set_review_due_validates_iso_date(self):
        conn = _conn()
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = _authorized(ADMIN_USER).put(
                    "/api/v1/admin/documents/5/review-due",
                    json={"review_due": "not-a-date"},
                )
            assert response.status_code == 422
        finally:
            _cleanup()

    def test_set_review_due_success_and_clear(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.rowcount = 1
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = _authorized(ADMIN_USER).put(
                    "/api/v1/admin/documents/5/review-due",
                    json={"review_due": "2026-09-01"},
                )
                assert response.status_code == 200
                assert response.json()["review_due"] == "2026-09-01"

                response = _authorized(ADMIN_USER).put(
                    "/api/v1/admin/documents/5/review-due",
                    json={"review_due": None},
                )
                assert response.status_code == 200
                assert response.json()["review_due"] is None
            # Second call must have bound NULL, not the string.
            params = cur.execute.call_args_list[1].args[1]
            assert params[0] is None
        finally:
            _cleanup()

    def test_set_review_due_unknown_document_404(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.rowcount = 0
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = _authorized(ADMIN_USER).put(
                    "/api/v1/admin/documents/999/review-due",
                    json={"review_due": "2026-09-01"},
                )
            assert response.status_code == 404
        finally:
            _cleanup()

    def test_review_overdue_requires_admin(self):
        try:
            response = _authorized(STAFF_USER).get(
                "/api/v1/admin/documents/review-overdue"
            )
            assert response.status_code == 403
        finally:
            _cleanup()

    def test_review_overdue_lists_documents(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchall.return_value = [
            {"id": 1, "title": "Old SOP", "department": "general",
             "doc_type": "sop", "version": 2,
             "review_due": "2026-07-01", "days_overdue": 51}
        ]
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = _authorized(ADMIN_USER).get(
                    "/api/v1/admin/documents/review-overdue"
                )
            assert response.status_code == 200
            assert response.json()["documents"][0]["title"] == "Old SOP"
        finally:
            _cleanup()


class TestSummaryIncludesOverdueCount:
    def test_admin_summary_has_review_overdue_key(self):
        conn = _conn()
        cur = conn.cursor.return_value
        counts = iter([{"n": 1}, {"n": 0}, {"n": 10}, {"n": 3},
                       {"n": 4}, {"n": 5}, {"n": 6}, {"n": 7}, {"n": 2}])
        cur.fetchone.side_effect = lambda: next(counts)
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = _authorized(ADMIN_USER).get("/api/v1/admin/summary")
            assert response.status_code == 200
            assert response.json()["documents_review_overdue"] == 2
        finally:
            _cleanup()


class TestSearchStaleSources:
    def test_stale_sources_attached_to_payload(self):
        from app.api.v1.search import SearchResponse

        resp = SearchResponse(
            response_id="r1",
            title="t",
            excerpts=[],
            summary=[],
            confidence=0.9,
            routing="answer",
            related_questions=[],
            stale_sources=["Rate Sheet"],
        )
        assert resp.stale_sources == ["Rate Sheet"]
