"""Unit tests for the staff onboard-client endpoint (Session 9/10 decision #2).

Covers: role/permission gating (client denied, staff without permission
denied), duplicate-email conflict, happy path (client + property + initial
case), the skip-property path, and validation of the request shape.
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


def _payload(**overrides) -> dict:
    data = {
        "email": "new.client@asto.local",
        "password": "supersecret1",
        "full_name": "New Client",
        "address": "12 Main St",
        "city": "Springfield",
        "state": "IL",
        "postal_code": "62701",
        "property_type": "single_family",
        "loan_amount": 250000,
        "case_status": "active",
    }
    data.update(overrides)
    return data


class TestOnboardClientRoutes:
    def test_route_exists(self):
        from app.main import app

        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/staff/clients" in paths

    def test_requires_auth(self):
        from app.main import app

        response = TestClient(app).post("/api/v1/staff/clients", json=_payload())
        assert response.status_code == 401


class TestOnboardClientGating:
    def test_client_token_denied(self):
        try:
            response = _authorized(CLIENT_USER).post(
                "/api/v1/staff/clients", json=_payload()
            )
            assert response.status_code == 403
        finally:
            _cleanup()

    def test_staff_without_permission_denied(self):
        staff_no_perm = {**STAFF_USER, "role": "viewer"}
        try:
            response = _authorized(staff_no_perm).post(
                "/api/v1/staff/clients", json=_payload()
            )
            assert response.status_code == 403
        finally:
            _cleanup()


class TestOnboardClientFlow:
    def test_onboard_client_property_and_case(self):
        """Full path: email-unique check, client insert, property insert,
        initial case insert, all committed."""
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            None,  # (1) duplicate-email check returns nothing
            {"id": 41},  # (2) clients RETURNING id
            {"id": 83},  # (3) properties RETURNING id
            {"n": 2},  # (4) case-number count
            {"id": 90},  # (5) cases RETURNING id
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).post(
                    "/api/v1/staff/clients", json=_payload()
                )
            finally:
                _cleanup()

        assert response.status_code == 201
        data = response.json()
        assert data["client_id"] == 41
        assert data["property_id"] == 83
        assert data["case_id"] == 90

        calls = [c.args[0] for c in cur.execute.call_args_list]
        assert any("INSERT INTO clients" in sql for sql in calls)
        assert any("INSERT INTO properties" in sql for sql in calls)
        assert any("INSERT INTO cases" in sql for sql in calls)
        assert conn.commit.called

    def test_onboard_client_without_property_skips_property_but_no_case(self):
        """No address fields and no loan amount → property and case skipped."""
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            None,  # duplicate-email check
            {"id": 42},  # clients RETURNING id
            {"n": 0},  # case-number count (computed, not inserted)
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).post(
                    "/api/v1/staff/clients",
                    json=_payload(address=None, city=None, state=None,
                                  postal_code=None, property_type=None,
                                  loan_amount=None),
                )
            finally:
                _cleanup()

        assert response.status_code == 201
        data = response.json()
        assert data["client_id"] == 42
        assert data["property_id"] is None
        assert data["case_id"] is None

        calls = [c.args[0] for c in cur.execute.call_args_list]
        assert any("INSERT INTO clients" in sql for sql in calls)
        assert not any("INSERT INTO properties" in sql for sql in calls)
        assert not any("INSERT INTO cases" in sql for sql in calls)

    def test_onboard_client_duplicate_email_409(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"id": 7}  # existing client found
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(STAFF_USER).post(
                    "/api/v1/staff/clients", json=_payload()
                )
            finally:
                _cleanup()

        assert response.status_code == 409
        calls = [c.args[0] for c in cur.execute.call_args_list]
        assert not any("INSERT INTO clients" in sql for sql in calls)

    def test_onboard_client_invalid_email_422(self):
        try:
            response = _authorized(STAFF_USER).post(
                "/api/v1/staff/clients",
                json=_payload(email="not-an-email"),
            )
            assert response.status_code == 422
        finally:
            _cleanup()

    def test_onboard_client_short_password_422(self):
        try:
            response = _authorized(STAFF_USER).post(
                "/api/v1/staff/clients",
                json=_payload(password="short"),
            )
            assert response.status_code == 422
        finally:
            _cleanup()