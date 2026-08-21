"""Unit tests for Phase G: staff clients view, staff document upload,
admin metadata edit, reject-with-reason, and staff notifications.

Covers: route wiring, auth requirements, audience gating (client tokens
denied), RBAC scoping of staff clients, upload validation, metadata edit
constraints, reject-reason requirement, and notification creation on
approve/reject.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

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

ADMIN_USER = {
    "id": 1,
    "email": "admin@asto.local",
    "full_name": "Admin User",
    "is_active": True,
    "audience": "staff",
    "role": "admin",
    "department": "general",
    "allowed_departments": ["general", "compliance"],
}

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


def _conn() -> MagicMock:
    """A connection whose cursor survives ``with`` blocks and yields mocks."""
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


class TestPhaseGRoutes:
    def test_routes_exist(self):
        from app.main import app
        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/staff/clients" in paths
        assert "/api/v1/staff/documents/upload" in paths
        assert "/api/v1/staff/notifications" in paths
        assert "/api/v1/staff/notifications/read-all" in paths
        assert "/api/v1/staff/notifications/{notification_id}/read" in paths
        assert "/api/v1/admin/documents/{document_id}" in paths

    def test_staff_clients_requires_auth(self):
        from app.main import app
        response = TestClient(app).get("/api/v1/staff/clients")
        assert response.status_code == 401

    def test_staff_upload_requires_auth(self):
        from app.main import app
        response = TestClient(app).post("/api/v1/staff/documents/upload")
        assert response.status_code == 401

    def test_notifications_requires_auth(self):
        from app.main import app
        response = TestClient(app).get("/api/v1/staff/notifications")
        assert response.status_code == 401


class TestStaffClientsView:
    def test_client_token_denied(self):
        try:
            response = _authorized(CLIENT_USER).get("/api/v1/staff/clients")
            assert response.status_code == 403
        finally:
            _cleanup()

    def test_staff_sees_only_assigned_clients(self):
        """Non-admin staff see clients via the assignment join only."""
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchall.side_effect = [
            [{"id": 5, "email": "c@x.com", "full_name": "Casey",
              "is_active": True, "created_at": None}],  # assigned clients
            [],  # properties
            [],  # cases
            [],  # documents
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).get("/api/v1/staff/clients")
            finally:
                _cleanup()

        assert response.status_code == 200
        data = response.json()
        assert len(data["clients"]) == 1
        assert data["clients"][0]["id"] == 5
        # The client query must scope via staff_client_assignments.
        calls = [c.args[0] for c in cur.execute.call_args_list]
        assignment_scoped = any(
            "staff_client_assignments" in sql and "user_id" in sql for sql in calls
        )
        assert assignment_scoped, "staff client query must be assignment-scoped"

    def test_staff_clients_returns_properties_cases_documents(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchall.side_effect = [
            [{"id": 5, "email": "c@x.com", "full_name": "Casey",
              "is_active": True, "created_at": None}],
            [{"id": 11, "client_id": 5, "address": "1 Main St", "city": "SF",
              "state": "CA", "postal_code": None, "property_type": "sfh",
              "is_active": True, "created_at": None}],
            [{"id": 22, "case_number": "CAS-2026-0001", "client_id": 5,
              "property_id": 11, "loan_amount": 250000, "status": "active",
              "is_active": True, "created_at": None}],
            [{"id": 33, "title": "Doc", "doc_type": "policy", "department": "general",
              "source_path": "/x.pdf", "client_id": 5, "property_id": None,
              "uploaded_by": 2, "approval_status": "pending", "is_approved": False,
              "version": 1, "created_at": None}],
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).get("/api/v1/staff/clients")
            finally:
                _cleanup()

        assert response.status_code == 200
        client = response.json()["clients"][0]
        assert client["properties"][0]["id"] == 11
        assert client["cases"][0]["id"] == 22
        assert client["documents"][0]["approval_status"] == "pending"
        assert client["documents"][0]["uploaded_by"] == 2


class TestStaffDocumentUpload:
    def test_client_token_denied(self):
        try:
            response = _authorized(CLIENT_USER).post(
                "/api/v1/staff/documents/upload",
                files={"file": ("a.txt", b"hello", "text/plain")},
                data={"client_id": "5"},
            )
            assert response.status_code == 403
        finally:
            _cleanup()

    def test_upload_requires_client_id(self):
        try:
            response = _authorized(STAFF_USER).post(
                "/api/v1/staff/documents/upload",
                files={"file": ("a.txt", b"hello", "text/plain")},
            )
            assert response.status_code == 400
        finally:
            _cleanup()

    def test_upload_writes_pending_file_and_sidecar(self):
        """Valid upload writes the file + meta sidecar to storage/pending/ and
        notifies admins."""
        from app.main import app
        from app.dependencies import require_auth

        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchall.return_value = [{"id": 1}]  # admin user for notification
        with patch("app.db.postgres.session.acquire", return_value=conn), \
             patch("app.documents.validation.settings.storage_pending_dir", "storage/pending"):
            app.dependency_overrides[require_auth] = lambda: STAFF_USER
            try:
                client = TestClient(app)
                response = client.post(
                    "/api/v1/staff/documents/upload",
                    files={"file": ("upload.txt", b"staff doc content", "text/plain")},
                    params={"client_id": "5"},
                )
            finally:
                app.dependency_overrides.pop(require_auth, None)

        assert response.status_code == 201
        data = response.json()
        assert data["client_id"] == 5
        assert data["size_bytes"] == len(b"staff doc content")

        calls = [c.args[0] for c in cur.execute.call_args_list]
        assert any("INSERT INTO notifications" in sql for sql in calls)

    def test_upload_invalid_file_type(self):
        from app.main import app
        from app.dependencies import require_auth

        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"id": 5}  # client is visible to staff
        with patch("app.db.postgres.session.acquire", return_value=conn), \
             patch("app.documents.validation.settings.max_upload_bytes", 1000):
            app.dependency_overrides[require_auth] = lambda: STAFF_USER
            try:
                client = TestClient(app)
                response = client.post(
                    "/api/v1/staff/documents/upload",
                    files={"file": ("evil.exe", b"MZ", "application/x-msdownload")},
                    params={"client_id": "5"},
                )
            finally:
                app.dependency_overrides.pop(require_auth, None)

        assert response.status_code == 400


class TestAdminMetadataEdit:
    def test_client_token_denied(self):
        try:
            response = _authorized(CLIENT_USER).patch(
                "/api/v1/admin/documents/10", json={"title": "X"}
            )
            assert response.status_code == 403
        finally:
            _cleanup()

    def test_staff_token_denied(self):
        try:
            response = _authorized(STAFF_USER).patch(
                "/api/v1/admin/documents/10", json={"title": "X"}
            )
            assert response.status_code == 403
        finally:
            _cleanup()

    def test_empty_patch_rejected(self):
        conn = _conn()
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).patch(
                    "/api/v1/admin/documents/10", json={}
                )
            finally:
                _cleanup()
        assert response.status_code == 400

    def test_only_pending_documents_editable(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"approval_status": "approved"}
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).patch(
                    "/api/v1/admin/documents/10", json={"title": "New Title"}
                )
            finally:
                _cleanup()
        assert response.status_code == 400
        calls = [c.args[0] for c in cur.execute.call_args_list]
        assert not any("UPDATE documents" in sql for sql in calls)

    def test_pending_document_metadata_updated(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"approval_status": "pending"}
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).patch(
                    "/api/v1/admin/documents/10",
                    json={"title": "New Title", "doc_type": "policy"},
                )
            finally:
                _cleanup()
        assert response.status_code == 200
        assert response.json()["updated"] == ["title", "doc_type"]
        calls = [c.args[0] for c in cur.execute.call_args_list]
        assert any("UPDATE documents" in sql for sql in calls)


class TestRejectWithReason:
    def test_reject_requires_reason(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"approval_status": "pending", "title": "Doc", "uploaded_by": None},
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).post(
                    "/api/v1/admin/documents/10/reject", json={}
                )
            finally:
                _cleanup()
        assert response.status_code == 422

    def test_reject_blank_reason_rejected(self):
        conn = _conn()
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).post(
                    "/api/v1/admin/documents/10/reject", json={"reason": "   "}
                )
            finally:
                _cleanup()
        assert response.status_code == 422

    def test_reject_persists_reason_and_notifies_uploader(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {
            "approval_status": "pending", "title": "Doc X", "uploaded_by": 2,
        }
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).post(
                    "/api/v1/admin/documents/10/reject",
                    json={"reason": "Missing client signature"},
                )
            finally:
                _cleanup()
        assert response.status_code == 200

        calls = [c.args[0] for c in cur.execute.call_args_list]
        assert any("INSERT INTO approval_log" in sql for sql in calls)
        assert any("INSERT INTO notifications" in sql for sql in calls)
        log_args = [
            a.args[1] for a in cur.execute.call_args_list
            if "INSERT INTO approval_log" in a.args[0]
        ]
        assert "Missing client signature" in log_args[0]


class TestNotifications:
    def test_client_token_denied(self):
        try:
            response = _authorized(CLIENT_USER).get("/api/v1/staff/notifications")
            assert response.status_code == 403
        finally:
            _cleanup()

    def test_staff_lists_own_notifications(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchall.return_value = [
            {"id": 1, "user_id": 2, "type": "document_rejected",
             "title": "Document rejected", "body": "Doc X: reason",
             "link": "/staff?tab=clients", "is_read": False, "created_at": None}
        ]
        cur.fetchone.return_value = {"unread": 1}
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).get("/api/v1/staff/notifications")
            finally:
                _cleanup()
        assert response.status_code == 200
        data = response.json()
        assert data["unread_count"] == 1
        assert data["notifications"][0]["type"] == "document_rejected"

    def test_mark_read_scoped_to_user(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.rowcount = 1
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).post(
                    "/api/v1/staff/notifications/9/read"
                )
            finally:
                _cleanup()
        assert response.status_code == 200
        calls = [c.args[0] for c in cur.execute.call_args_list]
        assert any("user_id = %s" in sql for sql in calls)

    def test_mark_read_not_found(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.rowcount = 0
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).post(
                    "/api/v1/staff/notifications/99/read"
                )
            finally:
                _cleanup()
        assert response.status_code == 404

    def test_mark_all_read(self):
        conn = _conn()
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).post(
                    "/api/v1/staff/notifications/read-all"
                )
            finally:
                _cleanup()
        assert response.status_code == 200
        cur = conn.cursor.return_value
        calls = [c.args[0] for c in cur.execute.call_args_list]
        assert any("is_read = true" in sql for sql in calls)


class TestSignatureRequestNotification:
    """G3: creating a signature request emails the client; signing one
    notifies admins."""

    def test_create_signature_request_emails_client(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"id": 5, "client_id": 7},  # document lookup
            {  # client + document title for the notice
                "email": "client@asto.local",
                "full_name": "Client User",
                "document_title": "Loan Agreement",
            },
            {"id": 9, "token": "tok", "status": "pending", "created_at": None},
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                with patch("app.email.mailer.send_email") as mock_send:
                    response = _authorized(ADMIN_USER).post(
                        "/api/v1/admin/signature-requests",
                        json={"case_id": 3, "document_id": 5,
                              "requested_from": "client"},
                    )
            finally:
                _cleanup()
        assert response.status_code == 201
        assert mock_send.call_count == 1
        args = mock_send.call_args.args
        assert args[0] == "client@asto.local"
        assert "Loan Agreement" in args[2]
        # The raw signing token must never be emailed (clients sign via the
        # authenticated portal).
        assert "tok" not in args[2] and "tok" not in args[3]

    def test_create_signature_request_without_email_skips_mail(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"id": 5, "client_id": 7},
            {"email": None, "full_name": "Client User",
             "document_title": "Loan Agreement"},
            {"id": 9, "token": "tok", "status": "pending", "created_at": None},
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                with patch("app.email.mailer.send_email") as mock_send:
                    response = _authorized(ADMIN_USER).post(
                        "/api/v1/admin/signature-requests",
                        json={"case_id": 3, "document_id": 5,
                              "requested_from": "client"},
                    )
            finally:
                _cleanup()
        assert response.status_code == 201
        mock_send.assert_not_called()

    def test_create_signature_request_case_not_found_404(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"id": 5, "client_id": 7},
            None,  # no matching case
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).post(
                    "/api/v1/admin/signature-requests",
                    json={"case_id": 999, "document_id": 5,
                          "requested_from": "client"},
                )
            finally:
                _cleanup()
        assert response.status_code == 404

    def test_client_sign_notifies_admins(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {
            "id": 1, "document_id": 5, "status": "pending",
        }
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                with patch(
                    "app.api.v1.notifications.notify_admins"
                ) as mock_notify:
                    response = _authorized(CLIENT_USER).post(
                        "/api/v1/client/signature-requests/1/sign",
                        json={"signed_name": "Client User", "consent": True},
                    )
            finally:
                _cleanup()
        assert response.status_code == 200
        assert mock_notify.call_count == 1
        assert mock_notify.call_args.args[1] == "signature_signed"
