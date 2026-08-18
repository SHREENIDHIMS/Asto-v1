"""Unit tests for the document approval workflow (Phase B3).

Covers: ingestion defaulting to pending, admin-only gating on approval
endpoints (client tokens denied), and route wiring for the pending list,
approve, reject, and history endpoints.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth.jwt_handler import create_token

CLIENT_USER = {
    "id": 7,
    "email": "client@asto.local",
    "full_name": "Client User",
    "is_active": True,
    "audience": "client",
    "client_id": 7,
    "role": "client",
    "department": None,
    "allowed_departments": [],
}

STAFF_USER = {
    "id": 1,
    "email": "admin@asto.local",
    "full_name": "Admin User",
    "is_active": True,
    "audience": "staff",
    "role": "admin",
    "department": "general",
    "allowed_departments": ["general"],
}


def _client_token() -> str:
    return create_token(subject="7", role="client", audience="client", client_id=7)


def _staff_token(role: str = "admin") -> str:
    return create_token(
        subject="1", role=role, department="general",
        allowed_departments=["general"], audience="staff",
    )


class TestIngestionApprovalDefault:
    def test_index_document_defaults_to_pending(self):
        """New ingestions must enter the approval workflow as pending."""
        from app.documents.chunking.structural_chunker import Chunk
        from app.documents.indexing import index_document

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.side_effect = [
            None,  # version lookup: no prior active document
            {"id": 42},  # document INSERT RETURNING id
        ]
        cur.rowcount = 1
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur

        chunks = [Chunk(content="pending chunk", chunk_type="paragraph", section=None, page_number=None)]

        result = index_document(
            conn=conn, doc_title="New Doc", doc_type="policy",
            department="general", source_path="/docs/new.pdf", chunks=chunks,
        )

        assert result.document_id == 42
        # The document INSERT must carry approval_status='pending', is_approved=false
        calls = [c.args[0] for c in cur.execute.call_args_list if "INSERT INTO documents" in c.args[0]]
        assert calls, "document INSERT statement not found"
        assert "approval_status" in calls[0]
        insert_args = cur.execute.call_args_list
        assert any(
            "pending" in str(a.args[1])
            for a in insert_args
            if "INSERT INTO documents" in a.args[0]
        )

    def test_index_document_approved_override(self):
        """Passing approval_status='approved' skips the pending workflow."""
        from app.documents.chunking.structural_chunker import Chunk
        from app.documents.indexing import index_document

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.side_effect = [
            None,  # version lookup: no prior active document
            {"id": 1},  # document INSERT RETURNING id
        ]
        cur.rowcount = 1
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur

        chunks = [Chunk(content="approved chunk", chunk_type="paragraph", section=None, page_number=None)]

        index_document(
            conn=conn, doc_title="Trusted Doc", doc_type="policy",
            department="general", source_path=None, chunks=chunks,
            approval_status="approved",
        )

        insert_args = cur.execute.call_args_list
        assert any(
            "approved" in str(a.args[1])
            for a in insert_args
            if "INSERT INTO documents" in a.args[0]
        )

    def test_index_document_reupload_bumps_version(self):
        """Re-uploading the same title/department deactivates the old active
        document and indexes the new one with version = old + 1."""
        from app.documents.chunking.structural_chunker import Chunk
        from app.documents.indexing import index_document

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.side_effect = [
            {"id": 5, "version": 3},  # version lookup: prior active v3
            {"id": 99},  # document INSERT RETURNING id
        ]
        cur.rowcount = 1
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur

        chunks = [Chunk(content="v4 chunk", chunk_type="paragraph", section=None, page_number=None)]

        result = index_document(
            conn=conn, doc_title="Loan Policy", doc_type="policy",
            department="general", source_path="/docs/loan-v4.pdf", chunks=chunks,
            approval_status="approved",
        )

        assert result.document_id == 99

        # Old active document must be deactivated
        deactivate = [
            a.args[0] for a in cur.execute.call_args_list
            if "UPDATE documents" in a.args[0]
        ]
        assert deactivate
        update_args = [
            a.args[1] for a in cur.execute.call_args_list
            if "UPDATE documents" in a.args[0]
        ]
        assert 5 in update_args[0]

        # New insert carries version=4
        insert_args = [
            a.args[1] for a in cur.execute.call_args_list
            if "INSERT INTO documents" in a.args[0]
        ]
        assert insert_args
        assert 4 in insert_args[0]

    def test_index_document_first_upload_version_one(self):
        """A first upload (no prior active document) is indexed as version 1."""
        from app.documents.chunking.structural_chunker import Chunk
        from app.documents.indexing import index_document

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.side_effect = [
            None,  # no prior active document
            {"id": 7},  # document INSERT RETURNING id
        ]
        cur.rowcount = 1
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur

        chunks = [Chunk(content="first chunk", chunk_type="paragraph", section=None, page_number=None)]

        index_document(
            conn=conn, doc_title="Brand New Doc", doc_type="policy",
            department="general", source_path=None, chunks=chunks,
        )

        insert_args = [
            a.args[1] for a in cur.execute.call_args_list
            if "INSERT INTO documents" in a.args[0]
        ]
        assert insert_args
        assert 1 in insert_args[0]

    def test_index_document_sets_pii_flag_when_chunk_has_ssn(self):
        """A chunk containing an SSN must surface pii_flagged=true on the doc row (I6)."""
        from app.documents.chunking.structural_chunker import Chunk
        from app.documents.indexing import index_document

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.side_effect = [
            None,  # version lookup: no prior active document
            {"id": 7},  # document INSERT RETURNING id
        ]
        cur.rowcount = 1
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur

        chunks = [
            Chunk(content="Client SSN is 123-45-6789", chunk_type="paragraph", section=None, page_number=None)
        ]

        index_document(
            conn=conn, doc_title="PII Doc", doc_type="policy",
            department="general", source_path="/docs/pii.pdf", chunks=chunks,
        )

        doc_insert_args = [
            a.args[1] for a in cur.execute.call_args_list
            if "INSERT INTO documents" in a.args[0]
        ][0]
        # pii_flagged is the last positional arg -> must be True
        assert doc_insert_args[-1] is True
        """A corrected re-upload of a rejected doc must become a new pending
        version and deactivate the old rejected doc (I3)."""
        from app.documents.chunking.structural_chunker import Chunk
        from app.documents.indexing import index_document

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.side_effect = [
            {"id": 3, "version": 2},  # prior active (rejected) doc v2
            {"id": 44},  # document INSERT RETURNING id
        ]
        cur.rowcount = 1
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur

        chunks = [Chunk(content="corrected chunk", chunk_type="paragraph", section=None, page_number=None)]

        result = index_document(
            conn=conn, doc_title="Loan Policy", doc_type="policy",
            department="general", source_path="/docs/loan-v3.pdf", chunks=chunks,
        )

        assert result.document_id == 44

        # Old (rejected) active doc is deactivated
        deactivate = [
            a.args[0] for a in cur.execute.call_args_list
            if "UPDATE documents" in a.args[0]
        ]
        assert deactivate
        update_args = [
            a.args[1] for a in cur.execute.call_args_list
            if "UPDATE documents" in a.args[0]
        ]
        assert 3 in update_args[0]

        # New version inherits version=3 and defaults to pending
        insert_args = [
            a.args[1] for a in cur.execute.call_args_list
            if "INSERT INTO documents" in a.args[0]
        ]
        assert insert_args
        assert 3 in insert_args[0]
        assert "pending" in str(insert_args[0])
        assert "approved" not in str(insert_args[0])


class TestApprovalEndpointAuth:
    def test_list_pending_requires_auth(self):
        from app.main import app
        client = TestClient(app)
        response = client.get("/api/v1/admin/documents/pending")
        assert response.status_code == 401

    def test_approve_requires_auth(self):
        from app.main import app
        client = TestClient(app)
        response = client.post("/api/v1/admin/documents/1/approve")
        assert response.status_code == 401

    def test_reject_requires_auth(self):
        from app.main import app
        client = TestClient(app)
        response = client.post("/api/v1/admin/documents/1/reject")
        assert response.status_code == 401

    def test_bulk_approve_requires_auth(self):
        from app.main import app
        client = TestClient(app)
        response = client.post("/api/v1/admin/documents/bulk-approve")
        assert response.status_code == 401

    def test_bulk_reject_requires_auth(self):
        from app.main import app
        client = TestClient(app)
        response = client.post("/api/v1/admin/documents/bulk-reject")
        assert response.status_code == 401

    def test_history_requires_auth(self):
        from app.main import app
        client = TestClient(app)
        response = client.get("/api/v1/admin/documents/1/history")
        assert response.status_code == 401

    def test_approval_endpoints_deny_client_tokens(self):
        """Client identities must never reach approval endpoints (403)."""
        from app.main import app
        from app.dependencies import require_auth
        app.dependency_overrides[require_auth] = lambda: CLIENT_USER
        try:
            client = TestClient(app)
            headers = {"Authorization": "Bearer client-token"}
            for method, path in [
                ("get", "/api/v1/admin/documents/pending"),
                ("post", "/api/v1/admin/documents/1/approve"),
                ("post", "/api/v1/admin/documents/1/reject"),
                ("post", "/api/v1/admin/documents/bulk-approve"),
                ("post", "/api/v1/admin/documents/bulk-reject"),
                ("get", "/api/v1/admin/documents/1/history"),
            ]:
                kwargs = {}
                if path.endswith("/reject") and "bulk" not in path:
                    kwargs = {"json": {"reason": "test"}}
                elif path.endswith("/approve") and "bulk" not in path:
                    kwargs = {"json": {"publish_anyway": False}}
                elif path.endswith("/bulk-approve"):
                    kwargs = {"json": {"document_ids": [1]}}
                elif path.endswith("/bulk-reject"):
                    kwargs = {"json": {"document_ids": [1], "reason": "test"}}
                response = getattr(client, method)(path, headers=headers, **kwargs)
                assert response.status_code == 403, f"{method} {path} should 403 for client"
        finally:
            app.dependency_overrides.pop(require_auth, None)

    def test_client_endpoints_deny_staff_tokens(self):
        """Staff identities must not reach client-only endpoints (403)."""
        from app.main import app
        from app.dependencies import require_auth
        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            client = TestClient(app)
            headers = {"Authorization": "Bearer staff-token"}
            for path in [
                "/api/v1/client/me",
                "/api/v1/client/properties",
                "/api/v1/client/cases",
                "/api/v1/client/documents",
            ]:
                response = client.get(path, headers=headers)
                assert response.status_code == 403, f"{path} should 403 for staff"
        finally:
            app.dependency_overrides.pop(require_auth, None)

    def test_client_endpoints_require_auth(self):
        from app.main import app
        client = TestClient(app)
        for path in [
            "/api/v1/client/me",
            "/api/v1/client/properties",
            "/api/v1/client/cases",
            "/api/v1/client/documents",
        ]:
            response = client.get(path)
            assert response.status_code == 401, f"{path} should 401 unauthenticated"


class TestApprovalRouteWiring:
    def test_pending_list_route_exists(self):
        from app.main import app
        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/admin/documents/pending" in paths
        assert "/api/v1/admin/documents/{document_id}/approve" in paths
        assert "/api/v1/admin/documents/{document_id}/reject" in paths
        assert "/api/v1/admin/documents/bulk-approve" in paths
        assert "/api/v1/admin/documents/bulk-reject" in paths
        assert "/api/v1/admin/documents/{document_id}/history" in paths
        assert "/api/v1/admin/documents/{document_id}/versions" in paths

    def test_client_login_route_exists(self):
        from app.main import app
        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/auth/client-login" in paths

    def test_admin_management_routes_exist(self):
        from app.main import app
        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/admin/clients" in paths
        assert "/api/v1/admin/assignments" in paths


class TestDocumentVersions:
    def test_versions_returns_family_ordered_by_version(self):
        """Versions endpoint groups all docs sharing the same family key."""
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        conn = MagicMock()
        conn.__enter__.return_value = conn
        cur = conn.cursor.return_value
        cur.__enter__.return_value = cur
        cur.fetchone.side_effect = [
            {"title": "Loan Policy", "department": "general", "client_id": None, "property_id": None},
        ]
        cur.fetchall.return_value = [
            {"id": 5, "title": "Loan Policy", "version": 1, "approval_status": "approved", "is_active": False, "created_at": "2026-01-01T00:00:00Z", "uploaded_by_email": "a@asto.local"},
            {"id": 6, "title": "Loan Policy", "version": 2, "approval_status": "pending", "is_active": True, "created_at": "2026-02-01T00:00:00Z", "uploaded_by_email": "b@asto.local"},
        ]

        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                client = TestClient(app)
                response = client.get("/api/v1/admin/documents/6/versions")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        versions = response.json()["versions"]
        assert [v["id"] for v in versions] == [5, 6]
        assert versions[0]["version"] == 1
        assert versions[1]["version"] == 2
        assert versions[1]["is_active"] is True

    def test_versions_404_for_missing_document(self):
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        conn = MagicMock()
        conn.__enter__.return_value = conn
        cur = conn.cursor.return_value
        cur.__enter__.return_value = cur
        cur.fetchone.return_value = None

        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                client = TestClient(app)
                response = client.get("/api/v1/admin/documents/999/versions")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404

    def test_versions_denies_client_tokens(self):
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        app.dependency_overrides[require_auth] = lambda: CLIENT_USER
        try:
            client = TestClient(app)
            response = client.get("/api/v1/admin/documents/1/versions")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 403

    def test_versioned_file_404_for_missing_version(self):
        """Requesting a version that does not exist in the family returns 404."""
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        conn = MagicMock()
        conn.__enter__.return_value = conn
        cur = conn.cursor.return_value
        cur.__enter__.return_value = cur
        cur.fetchone.side_effect = [
            {"title": "Loan Policy", "department": "general", "client_id": None, "property_id": None, "source_path": "/tmp/loan.pdf"},
            None,  # no document with version=99
        ]

        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                client = TestClient(app)
                response = client.get("/api/v1/documents/5/file?version=99")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404


class TestPiiPublishGating:
    def _mock_conn(self, pii_flagged: bool):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        cur = conn.cursor.return_value
        cur.__enter__.return_value = cur
        cur.__exit__ = MagicMock(return_value=False)
        # _check_pii_publish queries documents.pii_flagged
        cur.fetchone.return_value = {"pii_flagged": pii_flagged}
        return conn

    def test_approve_flagged_without_publish_anyway_422(self):
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        conn = self._mock_conn(pii_flagged=True)
        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                client = TestClient(app)
                response = client.post(
                    "/api/v1/admin/documents/1/approve",
                    json={"publish_anyway": False},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422

    def test_approve_flagged_with_publish_anyway_200(self):
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        conn = self._mock_conn(pii_flagged=True)
        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                with patch("app.api.v1.approvals._apply_document_status") as apply_mock:
                    client = TestClient(app)
                    response = client.post(
                        "/api/v1/admin/documents/1/approve",
                        json={"publish_anyway": True},
                    )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        apply_mock.assert_called_once()

    def test_approve_clean_doc_without_publish_anyway_200(self):
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        conn = self._mock_conn(pii_flagged=False)
        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                with patch("app.api.v1.approvals._apply_document_status") as apply_mock:
                    client = TestClient(app)
                    response = client.post(
                        "/api/v1/admin/documents/1/approve",
                        json={},
                    )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        apply_mock.assert_called_once()


class TestBulkApproval:
    def test_bulk_approve_runs_per_doc_and_commits_once(self):
        """Every id moves through the state machine on one shared connection."""
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from app.api.v1.approvals import _apply_document_status
        from app.main import app
        from app.dependencies import require_auth

        conn = MagicMock()
        conn.__enter__.return_value = conn
        cur = conn.cursor.return_value
        cur.__enter__.return_value = cur
        # 1st fetchall = pii-flagged docs (none), 2nd = id resolution (all found)
        cur.fetchall.side_effect = [[], [{"id": 1}, {"id": 2}, {"id": 3}]]

        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                applied = []
                def fake_apply(**kwargs):
                    applied.append(kwargs)
                with patch("app.api.v1.approvals._apply_document_status", side_effect=fake_apply):
                    client = TestClient(app)
                    response = client.post(
                        "/api/v1/admin/documents/bulk-approve",
                        json={"document_ids": [1, 2, 3]},
                        headers={"Authorization": "Bearer staff-token"},
                    )
            assert response.status_code == 200
            assert response.json()["message"] == "3 documents approved"
            assert [a["document_id"] for a in applied] == [1, 2, 3]
            assert all(a["to_status"] == "approved" for a in applied)
            assert all(a["conn"] is conn for a in applied)
            conn.commit.assert_called_once()
        finally:
            app.dependency_overrides.pop(require_auth, None)

    def test_bulk_approve_missing_id_aborts_no_partial(self):
        """An unknown id 404s the whole batch before any row is written."""
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        conn = MagicMock()
        conn.__enter__.return_value = conn
        cur = conn.cursor.return_value
        cur.__enter__.return_value = cur
        # 1st fetchall = pii-flagged docs (none), 2nd = id resolution (1,2 found; 99 missing)
        cur.fetchall.side_effect = [[], [{"id": 1}, {"id": 2}]]

        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                from app.api.v1.approvals import _apply_document_status
                with patch("app.api.v1.approvals._apply_document_status") as apply_mock:
                    client = TestClient(app)
                    response = client.post(
                        "/api/v1/admin/documents/bulk-approve",
                        json={"document_ids": [1, 2, 99]},
                        headers={"Authorization": "Bearer staff-token"},
                    )
            assert response.status_code == 404
            apply_mock.assert_not_called()
            conn.commit.assert_not_called()
        finally:
            app.dependency_overrides.pop(require_auth, None)

    def test_bulk_approve_validates_ids(self):
        """Duplicate or non-positive ids are rejected with 422."""
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            client = TestClient(app)
            headers = {"Authorization": "Bearer staff-token"}
            dup = client.post(
                "/api/v1/admin/documents/bulk-approve",
                json={"document_ids": [1, 1]}, headers=headers)
            assert dup.status_code == 422
            empty = client.post(
                "/api/v1/admin/documents/bulk-approve",
                json={"document_ids": []}, headers=headers)
            assert empty.status_code == 422
        finally:
            app.dependency_overrides.pop(require_auth, None)

    def test_bulk_reject_requires_reason(self):
        """Rejecting without a reason is a 422 (same rule as single reject)."""
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            client = TestClient(app)
            headers = {"Authorization": "Bearer staff-token"}
            response = client.post(
                "/api/v1/admin/documents/bulk-reject",
                json={"document_ids": [1, 2], "reason": ""},
                headers=headers)
            assert response.status_code == 422
        finally:
            app.dependency_overrides.pop(require_auth, None)

    def test_bulk_reject_runs_per_doc_with_reason(self):
        """A shared reason flows to each document's transition."""
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        conn = MagicMock()
        conn.__enter__.return_value = conn
        cur = conn.cursor.return_value
        cur.__enter__.return_value = cur
        cur.fetchall.return_value = [{"id": 4}, {"id": 5}]

        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                applied = []
                def fake_apply(**kwargs):
                    applied.append(kwargs)
                with patch("app.api.v1.approvals._apply_document_status", side_effect=fake_apply):
                    client = TestClient(app)
                    response = client.post(
                        "/api/v1/admin/documents/bulk-reject",
                        json={"document_ids": [4, 5], "reason": "Missing signatures"},
                        headers={"Authorization": "Bearer staff-token"},
                    )
            assert response.status_code == 200
            assert response.json()["message"] == "2 documents rejected"
            assert [a["document_id"] for a in applied] == [4, 5]
            assert all(a["to_status"] == "rejected" for a in applied)
            assert all(a["reason"] == "Missing signatures" for a in applied)
        finally:
            app.dependency_overrides.pop(require_auth, None)


class TestDocumentTags:
    def _admin_conn(self, fetchone_value=None, fetchall_value=None):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        cur = conn.cursor.return_value
        cur.__enter__.return_value = cur
        cur.fetchone.return_value = fetchone_value
        cur.fetchall.return_value = fetchall_value
        return conn

    def test_put_tags_updates_row_and_normalizes(self):
        """PUT tags replaces the row's tags; values are trimmed/lower/deduped."""
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        conn = self._admin_conn(fetchone_value={"id": 9})
        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                client = TestClient(app)
                response = client.put(
                    "/api/v1/admin/documents/9/tags",
                    json={"tags": ["Mortgage", "  credit  ", "Mortgage", "credit"]},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["tags"] == ["mortgage", "credit"]
        update_call = [
            c for c in conn.cursor.return_value.execute.call_args_list
            if "UPDATE documents SET tags" in c.args[0]
        ]
        assert update_call, "UPDATE documents SET tags statement not found"
        assert update_call[0].args[1][0] == ["mortgage", "credit"]

    def test_put_tags_empty_clears(self):
        """An empty tags array clears all tags on the document."""
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        conn = self._admin_conn(fetchone_value={"id": 9})
        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                client = TestClient(app)
                response = client.put(
                    "/api/v1/admin/documents/9/tags",
                    json={"tags": []},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["tags"] == []

    def test_put_tags_404_for_missing_document(self):
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        conn = self._admin_conn(fetchone_value=None)
        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                client = TestClient(app)
                response = client.put(
                    "/api/v1/admin/documents/999/tags",
                    json={"tags": ["loan"]},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404

    def test_put_tags_invalid_empty_422(self):
        """A blank/whitespace tag must be rejected with 422."""
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            client = TestClient(app)
            response = client.put(
                "/api/v1/admin/documents/9/tags",
                json={"tags": ["ok", "   "]},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422

    def test_put_tags_too_long_422(self):
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            client = TestClient(app)
            response = client.put(
                "/api/v1/admin/documents/9/tags",
                json={"tags": ["x" * 51]},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422

    def test_put_tags_denies_client_tokens(self):
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        app.dependency_overrides[require_auth] = lambda: CLIENT_USER
        try:
            client = TestClient(app)
            response = client.put(
                "/api/v1/admin/documents/9/tags",
                json={"tags": ["loan"]},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 403

    def test_list_tags_returns_aggregate_counts(self):
        """GET /admin/tags aggregates tags with per-tag document counts."""
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        conn = self._admin_conn(fetchall_value=[
            {"tag": "credit", "count": 3},
            {"tag": "mortgage", "count": 2},
        ])
        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                client = TestClient(app)
                response = client.get("/api/v1/admin/tags")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["tags"] == [
            {"tag": "credit", "count": 3},
            {"tag": "mortgage", "count": 2},
        ]

    def test_list_tags_denies_client_tokens(self):
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        app.dependency_overrides[require_auth] = lambda: CLIENT_USER
        try:
            client = TestClient(app)
            response = client.get("/api/v1/admin/tags")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 403

    def test_admin_list_filters_by_tag(self):
        """GET /documents?tag= folds the tag filter into the SQL WHERE."""
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        conn = self._admin_conn(fetchall_value=[{"id": 9, "title": "Loan", "tags": ["mortgage"]}])
        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                client = TestClient(app)
                response = client.get("/api/v1/documents/?tag=Mortgage")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert len(response.json()["documents"]) == 1
        calls = conn.cursor.return_value.execute.call_args_list
        assert any("ANY(d.tags)" in c.args[0] for c in calls), "tag filter missing from SQL"
        assert any(c.args[1][0] == "mortgage" for c in calls), "tag filter not parameterized"

    def test_client_documents_filter_by_tag(self):
        """Client documents endpoint folds tag filter + keeps client scoping."""
        from fastapi.testclient import TestClient

        from app.main import app
        from app.dependencies import require_auth

        conn = self._admin_conn(fetchall_value=[
            {"id": 3, "title": "Approved Doc", "tags": ["credit"]},
        ])
        app.dependency_overrides[require_auth] = lambda: CLIENT_USER
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                client = TestClient(app)
                response = client.get("/api/v1/client/documents?tag=credit")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        calls = conn.cursor.return_value.execute.call_args_list
        assert any("ANY(tags)" in c.args[0] for c in calls), "tag filter missing from SQL"
        assert any("client_id = %s" in c.args[0] for c in calls), "client scoping lost"
        # client_id param is first, tag is second
        assert any(c.args[1] == [7, "credit"] for c in calls), "params order wrong"

    def test_tags_routes_in_openapi(self):
        from app.main import app
        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/admin/documents/{document_id}/tags" in paths
        assert "/api/v1/admin/tags" in paths
