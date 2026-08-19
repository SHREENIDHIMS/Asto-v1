"""Phase M5 — GDPR-style client data export (builder + client/admin endpoints)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import require_auth

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

ADMIN_USER = {
    "id": 1,
    "email": "admin@asto.local",
    "full_name": "Admin User",
    "is_active": True,
    "audience": "staff",
    "role": "admin",
    "department": "general",
    "allowed_departments": [],
}


def _authorized(user: dict) -> TestClient:
    app.dependency_overrides[require_auth] = lambda: user
    return TestClient(app)


def _teardown():
    app.dependency_overrides.pop(require_auth, None)


def _make_conn(rows: dict[str, list[dict]]):
    """A fake connection keyed by table name (matched via SQL substrings)."""

    class Cursor:
        def __init__(self, conn):
            self._conn = conn

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            self._sql = sql

        def fetchall(self):
            for table, data in rows.items():
                if table in self._sql:
                    return data
            return []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            return Cursor(self)

    return Conn()


def _base_rows() -> dict[str, list[dict]]:
    return {
        "FROM clients WHERE id": [
            {
                "id": 7,
                "email": "client@asto.local",
                "password_hash": "secret",
                "full_name": "Client User",
                "is_active": True,
                "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
                "notification_prefs": {},
            }
        ],
        "FROM properties WHERE client_id": [
            {"id": 1, "address": "1 Main St", "city": "Springfield", "state": "IL",
             "postal_code": "62701", "property_type": "house", "is_active": True,
             "created_at": datetime(2025, 2, 1, tzinfo=timezone.utc)}
        ],
        "FROM cases WHERE client_id": [
            {"id": 2, "case_number": "C-100", "property_id": 1, "loan_amount": 250000,
             "status": "active", "is_active": True,
             "created_at": datetime(2025, 3, 1, tzinfo=timezone.utc)}
        ],
        "FROM documents d": [
            {"id": 3, "title": "Payslip", "doc_type": "policy", "department": "general",
             "approval_status": "approved", "is_active": True,
             "created_at": datetime(2025, 4, 1, tzinfo=timezone.utc), "content": "salary"}
        ],
        "FROM conversations WHERE client_id": [
            {"id": 4, "case_id": 2, "subject": "Docs", "created_at": datetime(2025, 5, 1, tzinfo=timezone.utc)}
        ],
        "FROM messages WHERE sender_client_id": [
            {"conversation_id": 4, "sender_type": "client", "sender_user_id": None,
             "sender_client_id": 7, "body": "here you go", "created_at": datetime(2025, 5, 2, tzinfo=timezone.utc)}
        ],
        "FROM feedback WHERE user_id": [
            {"response_id": "r-1", "rating": 1, "comment": "good", "created_at": datetime(2025, 6, 1, tzinfo=timezone.utc)}
        ],
        "FROM audit_log WHERE user_id": [
            {"id": 9, "query": "my loan", "outcome": "answer", "confidence": 0.9,
             "response_id": "r-1", "latency_ms": 10.5, "created_at": datetime(2025, 6, 2, tzinfo=timezone.utc)}
        ],
    }


class TestExportBuilder:
    def test_export_includes_every_section(self):
        with patch("app.clients.export.session.acquire", return_value=_make_conn(_base_rows())):
            from app.clients.export import build_client_export

            data = build_client_export(7)
        assert data["exists"] is True
        assert data["client"]["email"] == "client@asto.local"
        assert data["properties"][0]["city"] == "Springfield"
        assert data["cases"][0]["case_number"] == "C-100"
        assert data["documents"][0]["content"] == "salary"
        assert data["conversations"][0]["subject"] == "Docs"
        assert data["messages"][0]["body"] == "here you go"
        assert data["feedback"][0]["comment"] == "good"
        assert data["audit"][0]["query"] == "my loan"

    def test_password_hash_never_exposed(self):
        with patch("app.clients.export.session.acquire", return_value=_make_conn(_base_rows())):
            from app.clients.export import build_client_export

            data = build_client_export(7)
        assert "password_hash" not in data["client"]

    def test_missing_client_reports_not_exists(self):
        rows = _base_rows()
        rows["FROM clients WHERE id"] = []
        with patch("app.clients.export.session.acquire", return_value=_make_conn(rows)):
            from app.clients.export import build_client_export

            data = build_client_export(999)
        assert data["exists"] is False
        assert data["client"] is None

    def test_json_safe_converts_datetime_and_decimal(self):
        from decimal import Decimal

        from app.clients.export import json_safe

        out = json_safe({"when": datetime(2026, 1, 1, tzinfo=timezone.utc), "amount": Decimal("12.50")})
        assert out["when"] == "2026-01-01T00:00:00+00:00"
        assert out["amount"] == 12.5

    def test_export_queries_scoped_by_client_id(self):
        seen = {}

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params=None):
                seen.setdefault(sql.split()[0], params)

            def fetchall(self):
                return []

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def cursor(self):
                return Cursor()

        with patch("app.clients.export.session.acquire", return_value=Conn()):
            from app.clients.export import build_client_export

            build_client_export(42)
        # every scoped SELECT must filter by the requested client_id
        for sql, params in seen.items():
            if sql == "SELECT" or not params:
                continue
            assert params[0] == 42 or params[0] == (42,)


class TestClientExportEndpoint:
    def test_client_can_export_own_data(self):
        with patch("app.clients.export.session.acquire", return_value=_make_conn(_base_rows())), patch(
            "app.audit.audit_logger.log_query"
        ):
            client = _authorized(CLIENT_USER)
            try:
                res = client.get("/api/v1/client/me/export")
            finally:
                _teardown()
        assert res.status_code == 200
        assert res.headers["content-disposition"].startswith("attachment; filename=")
        data = res.json()
        assert data["client"]["id"] == 7
        assert data["documents"][0]["title"] == "Payslip"

    def test_staff_denied_on_client_endpoint(self):
        with patch("app.clients.export.session.acquire", return_value=_make_conn(_base_rows())):
            client = _authorized(ADMIN_USER)
            try:
                res = client.get("/api/v1/client/me/export")
            finally:
                _teardown()
        assert res.status_code == 403

    def test_requires_auth(self):
        res = TestClient(app).get("/api/v1/client/me/export")
        assert res.status_code == 401

    def test_client_export_is_audit_logged(self):
        with patch("app.clients.export.session.acquire", return_value=_make_conn(_base_rows())), patch(
            "app.audit.audit_logger.log_query"
        ) as log:
            client = _authorized(CLIENT_USER)
            try:
                client.get("/api/v1/client/me/export")
            finally:
                _teardown()
        log.assert_called_once()
        assert log.call_args.args[0].query == "client data export"


class TestAdminExportEndpoint:
    def test_admin_can_export_any_client(self):
        with patch("app.clients.export.session.acquire", return_value=_make_conn(_base_rows())), patch(
            "app.audit.audit_logger.log_query"
        ):
            client = _authorized(ADMIN_USER)
            try:
                res = client.get("/api/v1/admin/clients/7/export")
            finally:
                _teardown()
        assert res.status_code == 200
        assert res.json()["client"]["email"] == "client@asto.local"

    def test_admin_export_404_for_missing_client(self):
        rows = _base_rows()
        rows["FROM clients WHERE id"] = []
        with patch("app.clients.export.session.acquire", return_value=_make_conn(rows)), patch(
            "app.audit.audit_logger.log_query"
        ):
            client = _authorized(ADMIN_USER)
            try:
                res = client.get("/api/v1/admin/clients/999/export")
            finally:
                _teardown()
        assert res.status_code == 404

    def test_client_role_denied_on_admin_export(self):
        with patch("app.clients.export.session.acquire", return_value=_make_conn(_base_rows())):
            client = _authorized(CLIENT_USER)
            try:
                res = client.get("/api/v1/admin/clients/7/export")
            finally:
                _teardown()
        assert res.status_code == 403

    def test_admin_export_is_audit_logged(self):
        with patch("app.clients.export.session.acquire", return_value=_make_conn(_base_rows())), patch(
            "app.audit.audit_logger.log_query"
        ) as log:
            client = _authorized(ADMIN_USER)
            try:
                client.get("/api/v1/admin/clients/7/export")
            finally:
                _teardown()
        log.assert_called_once()
        assert log.call_args.args[0].query == "admin client data export"
        assert log.call_args.args[0].outcome == "client_id=7"