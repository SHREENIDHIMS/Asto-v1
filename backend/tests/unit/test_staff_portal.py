"""Unit tests for the staff portal (Â§1B) and client cases (Â§1A) endpoints.

Covers: route wiring, auth requirements, staff-vs-client audience gating,
dashboard RBAC scoping, case-note access, workflow stage transitions,
SOP authoring permissions, SOP access requests (staff submit, admin
reviews), and client-scoped case list/detail with status timeline.
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


class TestStaffRoutes:
    def test_routes_exist(self):
        from app.main import app
        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/staff/dashboard" in paths
        assert "/api/v1/staff/cases/{case_id}/notes" in paths
        assert "/api/v1/staff/workflows/{workflow_id}/advance" in paths
        assert "/api/v1/staff/sops" in paths
        assert "/api/v1/staff/sop-access-requests" in paths
        assert "/api/v1/admin/sop-access-requests" in paths

    def test_dashboard_requires_auth(self):
        from app.main import app
        response = TestClient(app).get("/api/v1/staff/dashboard")
        assert response.status_code == 401

    def test_dashboard_denies_client(self):
        try:
            client = _authorized(CLIENT_USER)
            response = client.get("/api/v1/staff/dashboard")
            assert response.status_code == 403
        finally:
            from app.main import app
            from app.dependencies import require_auth
            app.dependency_overrides.pop(require_auth, None)


class TestStaffDashboard:
    def test_non_admin_scopes_to_assigned_clients_and_dept(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchall.side_effect = [
            [{"client_id": 7}],  # assigned client ids
            [{"id": 10, "case_number": "CAS-1", "client_id": 7}],  # cases
            [  # workflows
                {
                    "id": 1, "title": "Income verification", "department": "general",
                    "case_id": None, "status": "in_progress", "assigned_to": None,
                    "created_at": None, "updated_at": None, "case_number": None,
                }
            ],
            [  # sops
                {
                    "id": 1, "title": "Intake SOP", "department": "general",
                    "body": "Steps", "version": 1, "created_by": 1,
                    "updated_at": None, "is_active": True,
                }
            ],
        ]
        cur.fetchone.return_value = None  # no approved SOP access
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).get(
                    "/api/v1/staff/dashboard"
                )
            finally:
                from app.main import app
                from app.dependencies import require_auth
                app.dependency_overrides.pop(require_auth, None)

        assert response.status_code == 200
        data = response.json()
        assert data["sop_access"] is False
        calls = [c.args[0] for c in cur.execute.call_args_list]
        assert any("client_id = ANY(%s)" in sql for sql in calls)
        assert any("department = ANY(%s)" in sql for sql in calls)

    def test_admin_sees_all_no_scoping_clause(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchall.side_effect = [
            [{"id": 1, "case_number": "CAS-1", "client_id": 7}],
            [
                {
                    "id": 1, "title": "W", "department": "general", "case_id": None,
                    "status": "in_progress", "assigned_to": None, "created_at": None,
                    "updated_at": None, "case_number": None,
                }
            ],
            [
                {
                    "id": 1, "title": "SOP", "department": "general", "body": "B",
                    "version": 1, "created_by": 1, "updated_at": None, "is_active": True,
                }
            ],
        ]
        cur.fetchone.return_value = None
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get(
                    "/api/v1/staff/dashboard"
                )
            finally:
                from app.main import app
                from app.dependencies import require_auth
                app.dependency_overrides.pop(require_auth, None)

        assert response.status_code == 200
        assert response.json()["sop_access"] is True  # admins always may author
        calls = [c.args[0] for c in cur.execute.call_args_list]
        assert not any("ANY(%s)" in sql for sql in calls)


class TestCaseNotes:
    def test_unassigned_staff_cannot_read_notes(self):
        conn = _conn()
        conn.cursor.return_value.fetchone.return_value = None  # not assigned
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).get(
                    "/api/v1/staff/cases/99/notes"
                )
            finally:
                from app.main import app
                from app.dependencies import require_auth
                app.dependency_overrides.pop(require_auth, None)
        assert response.status_code == 404

    def test_add_note_success(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"id": 1},  # access check passes
            {"id": 5, "case_id": 1, "user_id": 2, "body": "Call borrower", "created_at": None},
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).post(
                    "/api/v1/staff/cases/1/notes", json={"body": "Call borrower"}
                )
            finally:
                from app.main import app
                from app.dependencies import require_auth
                app.dependency_overrides.pop(require_auth, None)
        assert response.status_code == 201
        assert response.json()["note"]["body"] == "Call borrower"
        conn.commit.assert_called_once()

    def test_blank_note_rejected(self):
        try:
            response = _authorized(STAFF_USER).post(
                "/api/v1/staff/cases/1/notes", json={"body": "   "}
            )
            assert response.status_code == 422
        finally:
            from app.main import app
            from app.dependencies import require_auth
            app.dependency_overrides.pop(require_auth, None)


class TestWorkflowAdvance:
    def test_advances_in_progress_to_review(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"id": 3, "status": "in_progress"}
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).post(
                    "/api/v1/staff/workflows/3/advance"
                )
            finally:
                from app.main import app
                from app.dependencies import require_auth
                app.dependency_overrides.pop(require_auth, None)
        assert response.status_code == 200
        assert response.json() == {"workflow_id": 3, "status": "review"}
        update = [c.args for c in cur.execute.call_args_list if "UPDATE workflows" in c.args[0]]
        assert update and update[0][1][0] == "review"

    def test_done_returns_conflict(self):
        conn = _conn()
        conn.cursor.return_value.fetchone.return_value = {"id": 3, "status": "done"}
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).post(
                    "/api/v1/staff/workflows/3/advance"
                )
            finally:
                from app.main import app
                from app.dependencies import require_auth
                app.dependency_overrides.pop(require_auth, None)
        assert response.status_code == 409

    def test_missing_workflow_404(self):
        conn = _conn()
        conn.cursor.return_value.fetchone.return_value = None
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).post(
                    "/api/v1/staff/workflows/999/advance"
                )
            finally:
                from app.main import app
                from app.dependencies import require_auth
                app.dependency_overrides.pop(require_auth, None)
        assert response.status_code == 404


class TestSopAuthoring:
    def test_create_requires_approved_request(self):
        conn = _conn()
        conn.cursor.return_value.fetchone.return_value = None  # no approved request
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).post(
                    "/api/v1/staff/sops",
                    json={"title": "New SOP", "department": "general", "body": "Steps..."},
                )
            finally:
                from app.main import app
                from app.dependencies import require_auth
                app.dependency_overrides.pop(require_auth, None)
        assert response.status_code == 403

    def test_create_with_approved_request(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"id": 1},  # approved request exists
            {"id": 9},  # RETURNING id
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).post(
                    "/api/v1/staff/sops",
                    json={"title": "New SOP", "department": "general", "body": "Steps..."},
                )
            finally:
                from app.main import app
                from app.dependencies import require_auth
                app.dependency_overrides.pop(require_auth, None)
        assert response.status_code == 201
        assert response.json()["sop_id"] == 9

    def test_create_outside_department_scope_denied(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"id": 1},  # approved request
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).post(
                    "/api/v1/staff/sops",
                    json={"title": "X", "department": "compliance", "body": "B"},
                )
            finally:
                from app.main import app
                from app.dependencies import require_auth
                app.dependency_overrides.pop(require_auth, None)
        assert response.status_code == 403

    def test_admin_create_bypasses_request(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"id": 11}
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).post(
                    "/api/v1/staff/sops",
                    json={"title": "SOP", "department": "compliance", "body": "B"},
                )
            finally:
                from app.main import app
                from app.dependencies import require_auth
                app.dependency_overrides.pop(require_auth, None)
        assert response.status_code == 201
        assert response.json()["sop_id"] == 11

    def test_update_bumps_version(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"id": 4, "department": "general", "version": 2}
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).put(
                    "/api/v1/staff/sops/4",
                    json={"title": "SOP", "department": "general", "body": "New"},
                )
            finally:
                from app.main import app
                from app.dependencies import require_auth
                app.dependency_overrides.pop(require_auth, None)
        assert response.status_code == 200
        update = [c.args for c in cur.execute.call_args_list if "UPDATE sops" in c.args[0]]
        assert update and update[0][1][3] == 3  # version 2 -> 3


class TestSopAccessRequests:
    def test_staff_submits_request(self):
        conn = _conn()
        conn.cursor.return_value.fetchone.side_effect = [
            None,  # no existing pending
            {"id": 12, "status": "pending"},
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).post(
                    "/api/v1/staff/sop-access-requests",
                    json={"action": "create", "department": "general", "reason": "Need it"},
                )
            finally:
                from app.main import app
                from app.dependencies import require_auth
                app.dependency_overrides.pop(require_auth, None)
        assert response.status_code == 201
        assert response.json() == {"id": 12, "status": "pending"}

    def test_duplicate_pending_request_409(self):
        conn = _conn()
        conn.cursor.return_value.fetchone.side_effect = [{"id": 1}]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).post(
                    "/api/v1/staff/sop-access-requests",
                    json={"action": "create", "department": "general"},
                )
            finally:
                from app.main import app
                from app.dependencies import require_auth
                app.dependency_overrides.pop(require_auth, None)
        assert response.status_code == 409

    def test_admin_auto_approved(self):
        try:
            response = _authorized(ADMIN_USER).post(
                "/api/v1/staff/sop-access-requests",
                json={"action": "create", "department": "compliance"},
            )
            assert response.status_code == 201
            assert response.json()["status"] == "approved"
        finally:
            from app.main import app
            from app.dependencies import require_auth
            app.dependency_overrides.pop(require_auth, None)


class TestAdminSopReview:
    def test_non_admin_denied(self):
        conn = _conn()
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).get(
                    "/api/v1/admin/sop-access-requests"
                )
            finally:
                from app.main import app
                from app.dependencies import require_auth
                app.dependency_overrides.pop(require_auth, None)
        assert response.status_code == 403

    def test_admin_approves(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [{"id": 5}, None]  # exists, then update returns nothing
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).post(
                    "/api/v1/admin/sop-access-requests/5/review",
                    json={"decision": "approved"},
                )
            finally:
                from app.main import app
                from app.dependencies import require_auth
                app.dependency_overrides.pop(require_auth, None)
        assert response.status_code == 200
        update = [c.args for c in cur.execute.call_args_list if "UPDATE sop_access_requests" in c.args[0]]
        assert update and update[0][1][0] == "approved"

    def test_missing_request_404(self):
        conn = _conn()
        conn.cursor.return_value.fetchone.return_value = None
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).post(
                    "/api/v1/admin/sop-access-requests/999/review",
                    json={"decision": "approved"},
                )
            finally:
                from app.main import app
                from app.dependencies import require_auth
                app.dependency_overrides.pop(require_auth, None)
        assert response.status_code == 404


class TestClientCases:
    def test_cases_list_includes_property_and_latest_event(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchall.side_effect = [
            [
                {
                    "id": 1, "case_number": "CAS-1", "client_id": 7,
                    "property_id": 3, "loan_amount": 275000.00, "status": "under_review",
                    "is_active": True, "created_at": None, "address": "123 Main St",
                    "city": "Springfield", "state": "IL", "property_type": "single_family",
                }
            ],
            [
                {"case_id": 1, "status": "under_review", "note": "Reviewing", "created_at": None},
            ],
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(CLIENT_USER).get(
                    "/api/v1/client/cases"
                )
            finally:
                from app.main import app
                from app.dependencies import require_auth
                app.dependency_overrides.pop(require_auth, None)
        assert response.status_code == 200
        case = response.json()["cases"][0]
        assert case["property_address"] == "123 Main St, Springfield, IL"
        assert case["latest_event"]["status"] == "under_review"

    def test_case_detail_returns_timeline(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {
                "id": 1, "case_number": "CAS-1", "client_id": 7, "property_id": None,
                "loan_amount": 275000.00, "status": "active", "is_active": True,
                "created_at": None, "address": None, "city": None, "state": None,
                "property_type": None,
            },
        ]
        cur.fetchall.return_value = [
            {"id": 1, "case_id": 1, "status": "submitted", "note": "In", "created_at": None},
            {"id": 2, "case_id": 1, "status": "active", "note": "Approved", "created_at": None},
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(CLIENT_USER).get(
                    "/api/v1/client/cases/1"
                )
            finally:
                from app.main import app
                from app.dependencies import require_auth
                app.dependency_overrides.pop(require_auth, None)
        assert response.status_code == 200
        data = response.json()
        assert data["case"]["status"] == "active"
        assert [e["status"] for e in data["events"]] == ["submitted", "active"]

    def test_case_detail_other_clients_case_404(self):
        conn = _conn()
        conn.cursor.return_value.fetchone.return_value = None
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(CLIENT_USER).get(
                    "/api/v1/client/cases/999"
                )
            finally:
                from app.main import app
                from app.dependencies import require_auth
                app.dependency_overrides.pop(require_auth, None)
        assert response.status_code == 404
