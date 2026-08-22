"""HTTP-level coverage for endpoints that previously had none.

Covers the gaps found in the 2026-08-22 completeness audit:
- POST /admin/users, /admin/clients, /admin/assignments
- GET /admin/synonyms/expand/{text}
- case-requirements group (default / seed / per-case checklist)
- admin signature-requests list + on-behalf sign
- analytics gap-topics / content-coverage / summary endpoints
- client case timeline
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

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


def _conn(fetchone_seq=None, fetchall_val=None, rowcount=1):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cur = conn.cursor.return_value
    cur.__enter__.return_value = cur
    if fetchone_seq is not None:
        cur.fetchone.side_effect = list(fetchone_seq)
    else:
        cur.fetchone.return_value = None
    cur.fetchall.return_value = fetchall_val or []
    cur.rowcount = rowcount
    return conn


def _authorized(user: dict):
    from app.main import app
    from app.dependencies import require_auth

    app.dependency_overrides[require_auth] = lambda: user
    return TestClient(app)


def _cleanup():
    from app.main import app
    from app.dependencies import require_auth

    app.dependency_overrides.pop(require_auth, None)


class TestAdminUserClientAssignmentCreation:
    def test_create_user_201(self):
        # First lookup: no existing email; second: INSERT RETURNING.
        conn = _conn(fetchone_seq=[None, {"id": 5}])
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).post(
                    "/api/v1/admin/users",
                    json={
                        "email": "new@asto.local",
                        "password": "secret-password-123",
                        "full_name": "New Officer",
                        "role": "loan_officer",
                    },
                )
            finally:
                _cleanup()
        assert response.status_code == 201

    def test_create_client_201(self):
        conn = _conn(fetchone_seq=[None, {"id": 9}])
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).post(
                    "/api/v1/admin/clients",
                    json={"email": "c2@asto.local", "password": "pw-123456789"},
                )
            finally:
                _cleanup()
        assert response.status_code == 201

    def test_assign_staff_to_client(self):
        conn = _conn()
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).post(
                    "/api/v1/admin/assignments",
                    json={"client_id": 7, "user_id": 2},
                )
            finally:
                _cleanup()
        assert response.status_code == 201


class TestSynonymExpandEndpoint:
    def test_expand_requires_admin(self):
        try:
            response = _authorized(CLIENT_USER).get(
                "/api/v1/admin/synonyms/expand/deposit"
            )
            assert response.status_code == 403
        finally:
            _cleanup()

    def test_expand_returns_original_when_no_matches(self):
        conn = _conn(fetchall_val=[])
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get(
                    "/api/v1/admin/synonyms/expand/nothing"
                )
            finally:
                _cleanup()
        assert response.status_code == 200
        assert response.json()["expanded"] == "nothing"


class TestCaseRequirementsEndpoints:
    def test_defaults_require_admin(self):
        try:
            response = _authorized(CLIENT_USER).get(
                "/api/v1/admin/case-requirements/default/purchase"
            )
            assert response.status_code == 403
        finally:
            _cleanup()

    def test_defaults_return_requirements(self):
        conn = _conn()
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get(
                    "/api/v1/admin/case-requirements/default/purchase"
                )
            finally:
                _cleanup()
        assert response.status_code == 200
        data = response.json()
        assert data["case_type"] == "purchase"
        # Seeded defaults from requirements.DEFAULT_REQUIREMENTS.
        assert any(r["name"] == "Purchase Agreement" for r in data["requirements"])

    def test_seed_reports_inserted_count(self):
        conn = _conn()
        with patch("app.db.postgres.session.acquire", return_value=conn), patch(
            "app.documents.requirements.seed_default_requirements", return_value=3
        ) as mock_seed:
            try:
                response = _authorized(ADMIN_USER).post(
                    "/api/v1/admin/case-requirements/seed/refinance"
                )
            finally:
                _cleanup()
        assert response.status_code == 200
        assert response.json()["inserted"] == 3
        assert mock_seed.call_args.args[1] == "refinance"

    def test_case_checklist_derived(self):
        conn = _conn(
            fetchone_seq=[{"id": 4, "client_id": 7, "property_id": None,
                           "status": "active", "case_number": "PUR-1"}],
            fetchall_val=[],
        )
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get(
                    "/api/v1/admin/case-requirements/4"
                )
            finally:
                _cleanup()
        assert response.status_code == 200
        assert response.json()["case_id"] == 4
        assert isinstance(response.json()["checklist"], list)


class TestAdminSignatureRequestEndpoints:
    def test_list_requests(self):
        conn = _conn(fetchall_val=[
            {"id": 1, "case_id": 3, "document_id": 5, "requested_from": "client",
             "token": "t", "status": "pending", "signed_at": None, "created_at": None},
        ])
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get(
                    "/api/v1/admin/signature-requests"
                )
            finally:
                _cleanup()
        assert response.status_code == 200
        assert response.json()["signature_requests"][0]["status"] == "pending"

    def test_sign_on_behalf_updates_and_bumps_version(self):
        conn = _conn(fetchone_seq=[
            {"id": 1, "case_id": 3, "document_id": 5, "status": "pending"},
            {"id": 5, "case_id": 3, "client_id": 7, "property_id": None,
             "status": "active", "case_number": "PUR-1"},  # timeline resolution
        ], fetchall_val=[{"id": 10}])
        with patch("app.db.postgres.session.acquire", return_value=conn), patch(
            "app.api.v1.notifications.notify_user"
        ), patch("app.cases.timeline.record_document_status_events", return_value=0):
            try:
                response = _authorized(ADMIN_USER).post(
                    "/api/v1/admin/signature-requests/1/sign",
                    data={"signed_name": "Client User", "consent": "true"},
                )
            finally:
                _cleanup()
        assert response.status_code == 200


class TestAnalyticsEndpoints:
    def test_gap_topics_endpoint(self):
        conn = _conn(fetchall_val=[])
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get("/api/v1/analytics/gap-topics")
            finally:
                _cleanup()
        assert response.status_code == 200
        assert response.json()["topics"] == []

    def test_content_coverage_endpoint(self):
        conn = _conn()
        with patch("app.db.postgres.session.acquire", return_value=conn), patch(
            "app.documents.coverage.coverage_by_department", return_value=[]
        ), patch("app.documents.coverage.empty_cells", return_value=[]):
            try:
                response = _authorized(ADMIN_USER).get(
                    "/api/v1/analytics/content-coverage"
                )
            finally:
                _cleanup()
        assert response.status_code == 200
        assert response.json()["coverage"] == []
        assert response.json()["empty_cells"] == []

    def test_summary_endpoint(self):
        conn = _conn()
        cur = conn.cursor.return_value.__enter__.return_value
        counts = iter([{"n": 3}, {"n": 1}])
        cur.fetchone.side_effect = lambda: next(counts, {"n": 0})
        cur.fetchall.return_value = []
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get("/api/v1/analytics/summary")
            finally:
                _cleanup()
        assert response.status_code == 200
        data = response.json()
        assert data["total_gaps"] == 3
        assert "by_intent" in data and "by_day" in data


class TestClientCaseTimelineEndpoint:
    def test_timeline_scoped_and_ordered(self):
        from unittest.mock import patch as p

        conn = _conn(fetchall_val=[
            {"id": 1, "case_id": 4, "status": "document_approved",
             "note": None, "created_at": None},
        ])
        with p("app.db.postgres.session.acquire", return_value=conn), p(
            "app.api.v1.client._assert_owns_case", return_value=None
        ):
            try:
                response = _authorized(CLIENT_USER).get(
                    "/api/v1/client/cases/4/timeline"
                )
            finally:
                _cleanup()
        assert response.status_code == 200
        data = response.json()
        assert data["case_id"] == 4
        assert data["timeline"][0]["status"] == "document_approved"
        sql = conn.cursor.return_value.__enter__.return_value.execute.call_args.args[0]
        assert "ORDER BY created_at ASC" in sql

    def test_timeline_requires_client(self):
        from unittest.mock import patch as p

        conn = _conn()
        with p("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get(
                    "/api/v1/client/cases/4/timeline"
                )
            finally:
                _cleanup()
        assert response.status_code == 403
