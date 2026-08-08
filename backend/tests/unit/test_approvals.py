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
        cur.fetchone.return_value = {"id": 42}
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
        cur.fetchone.return_value = {"id": 1}
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
                ("get", "/api/v1/admin/documents/1/history"),
            ]:
                response = getattr(client, method)(path, headers=headers)
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
        assert "/api/v1/admin/documents/{document_id}/history" in paths

    def test_client_login_route_exists(self):
        from app.main import app
        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/auth/client-login" in paths

    def test_admin_management_routes_exist(self):
        from app.main import app
        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/admin/clients" in paths
        assert "/api/v1/admin/assignments" in paths
