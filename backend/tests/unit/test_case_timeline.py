"""Unit tests for case timeline auto-events (document + workflow hooks)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.cases.timeline import (
    record_case_events,
    record_document_status_events,
    record_workflow_stage_event,
    resolve_case_ids_for_document,
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


def _conn() -> MagicMock:
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cur = conn.cursor.return_value
    cur.__enter__.return_value = cur
    return conn


class TestResolveCaseIdsForDocument:
    def test_property_match_takes_priority(self):
        conn = _conn()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = {"client_id": 7, "property_id": 3}
        cur.fetchall.return_value = [{"id": 10}]
        assert resolve_case_ids_for_document(conn, 5) == [10]
        sql = cur.execute.call_args_list[1].args[0]
        assert "property_id = %s::int" in sql

    def test_no_client_returns_empty(self):
        conn = _conn()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = {"client_id": None, "property_id": None}
        assert resolve_case_ids_for_document(conn, 5) == []

    def test_unknown_document_returns_empty(self):
        conn = _conn()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None
        assert resolve_case_ids_for_document(conn, 999) == []


class TestRecordCaseEvents:
    def test_inserts_one_row_per_case(self):
        conn = _conn()
        inserted = record_case_events(conn, [1, 2], "document_approved", "note")
        assert inserted == 2
        cur = conn.cursor.return_value.__enter__.return_value
        inserts = [
            c for c in cur.execute.call_args_list
            if "INSERT INTO case_events" in c.args[0]
        ]
        assert len(inserts) == 2

    def test_insert_failure_does_not_raise(self):
        conn = _conn()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.execute.side_effect = [None, RuntimeError("db broke")]
        inserted = record_case_events(conn, [1, 2], "document_approved", None)
        assert inserted == 1


class TestDocumentStatusHook:
    def test_approval_appends_timeline_event(self):
        conn = _conn()
        cur = conn.cursor.return_value.__enter__.return_value
        # document lookup (fetchone) → case ids lookup (fetchall)
        cur.fetchone.return_value = {"client_id": 7, "property_id": 3}
        cur.fetchall.return_value = [{"id": 10}]

        from app.cases.timeline import record_document_status_events as rec

        inserted = rec(conn, 5, "approved", "looks good")
        assert inserted == 1
        insert_calls = [
            c for c in cur.execute.call_args_list
            if "INSERT INTO case_events" in c.args[0]
        ]
        assert insert_calls[0].args[1] == (10, "document_approved",
                                           "Document #5 approved: looks good")

    def test_rejection_note_includes_reason(self):
        conn = _conn()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = {"client_id": 7, "property_id": None}
        cur.fetchall.return_value = [{"id": 11}]
        from app.cases.timeline import record_document_status_events as rec

        rec(conn, 6, "rejected", "blurry scan")
        insert_calls = [
            c for c in cur.execute.call_args_list
            if "INSERT INTO case_events" in c.args[0]
        ]
        assert insert_calls[0].args[1] == (11, "document_rejected",
                                           "Document #6 rejected: blurry scan")


class TestWorkflowStageHook:
    def test_skipped_without_case(self):
        conn = _conn()
        assert record_workflow_stage_event(conn, 9, None, "review") == 0
        conn.cursor.assert_not_called()

    def test_inserts_event_with_stage(self):
        conn = _conn()
        inserted = record_workflow_stage_event(conn, 9, 4, "review")
        assert inserted == 1
        cur = conn.cursor.return_value.__enter__.return_value
        call = [
            c for c in cur.execute.call_args_list
            if "INSERT INTO case_events" in c.args[0]
        ][0]
        assert call.args[1] == (4, "workflow_review",
                                "Workflow #9 moved to review")


class TestApprovalsEndpointIntegration:
    def test_approve_endpoint_triggers_timeline_recording(self):
        from app.main import app
        from app.dependencies import require_auth

        conn = _conn()
        cur = conn.cursor.return_value.__enter__.return_value
        # _apply_document_status: doc lookup (fetchone); uploader notify
        # skipped (uploaded_by None). Timeline: document row + case rows.
        cur.fetchone.side_effect = [
            {"pii_flagged": False},                # PII publish check
            {"approval_status": "pending", "title": "Doc", "uploaded_by": None},
            {"client_id": 7, "property_id": 3},   # timeline: document row
        ]
        cur.fetchall.return_value = [{"id": 10}]  # timeline: case rows

        app.dependency_overrides[require_auth] = lambda: ADMIN_USER
        try:
            client = TestClient(app)
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = client.post(
                    "/api/v1/admin/documents/5/approve",
                    json={"publish_anyway": False},
                )
        finally:
            app.dependency_overrides.pop(require_auth, None)

        assert response.status_code == 200
        inserts = [
            c for c in cur.execute.call_args_list
            if "INSERT INTO case_events" in c.args[0]
        ]
        assert len(inserts) == 1
