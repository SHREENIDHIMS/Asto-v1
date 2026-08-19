"""Unit tests for Phase M1 audit log export endpoint.

Covers: route wiring, auth requirements, client denial, CSV output
(header + rows + BOM + attachment disposition), JSON output, filter
clause application, and that the export itself is audit-logged.
"""

from __future__ import annotations

import csv as csvlib
import io
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

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
    "allowed_departments": ["general", "compliance"],
}

AUDIT_ROW = {
    "id": 42,
    "user_id": 1,
    "query": "minimum credit score",
    "sub_queries": ["credit score"],
    "retrieved_ids": [10, 11],
    "confidence": 0.92,
    "response_id": "resp-1",
    "outcome": "answer",
    "latency_ms": 11.2,
    "created_at": "2026-08-18T00:00:00+00:00",
    "actor": "Admin User",
    "actor_email": "admin@asto.local",
}


def _authorized(user: dict):
    from app.main import app
    from app.dependencies import require_auth

    app.dependency_overrides[require_auth] = lambda: user
    return TestClient(app)


def _conn() -> MagicMock:
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cur = conn.cursor.return_value
    cur.__enter__.return_value = cur
    cur.fetchall.return_value = [AUDIT_ROW]
    return conn


def _teardown():
    from app.main import app
    from app.dependencies import require_auth

    app.dependency_overrides.pop(require_auth, None)


class TestAuditExportRoutes:
    def test_route_exists(self):
        from app.main import app

        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/admin/audit/export" in paths

    def test_requires_auth(self):
        from app.main import app

        assert TestClient(app).get("/api/v1/admin/audit/export").status_code == 401

    def test_denies_client(self):
        try:
            response = _authorized(CLIENT_USER).get("/api/v1/admin/audit/export")
        finally:
            _teardown()
        assert response.status_code == 403

    def test_rejects_bad_format(self):
        try:
            response = _authorized(ADMIN_USER).get("/api/v1/admin/audit/export?format=xml")
        finally:
            _teardown()
        assert response.status_code == 422


class TestAuditExportCsv:
    def test_returns_csv_with_header_and_rows(self):
        conn = _conn()
        with patch("app.db.postgres.session.acquire", return_value=conn), patch(
            "app.audit.audit_logger.log_query"
        ) as log:
            try:
                response = _authorized(ADMIN_USER).get("/api/v1/admin/audit/export")
            finally:
                _teardown()

        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert response.headers["content-disposition"].startswith("attachment; filename=")
        assert response.text.startswith("\ufeff")

        rows = list(csvlib.reader(io.StringIO(response.text.lstrip("\ufeff"))))
        header = rows[0]
        assert header[0] == "id"
        assert "sub_queries" in header and "retrieved_ids" in header
        row = next(r for r in rows[1:] if r[header.index("query")] == "minimum credit score")
        assert row[header.index("sub_queries")] == '["credit score"]'
        assert row[header.index("retrieved_ids")] == "[10, 11]"
        assert row[header.index("actor_email")] == "admin@asto.local"
        log.assert_called_once()


class TestAuditExportJson:
    def test_returns_json_entries(self):
        conn = _conn()
        with patch("app.db.postgres.session.acquire", return_value=conn), patch(
            "app.audit.audit_logger.log_query"
        ):
            try:
                response = _authorized(ADMIN_USER).get(
                    "/api/v1/admin/audit/export?format=json"
                )
            finally:
                _teardown()

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        entry = data["entries"][0]
        assert entry["query"] == "minimum credit score"
        assert entry["sub_queries"] == ["credit score"]
        assert entry["retrieved_ids"] == [10, 11]
        assert entry["actor"] == "Admin User"


class TestAuditExportFilters:
    def test_applies_filters_to_select(self):
        conn = _conn()
        with patch("app.db.postgres.session.acquire", return_value=conn), patch(
            "app.audit.audit_logger.log_query"
        ):
            try:
                _authorized(ADMIN_USER).get(
                    "/api/v1/admin/audit/export?q=credit&outcome=answer&from=2026-08-01&to=2026-08-10"
                )
            finally:
                _teardown()

        select_sql = conn.cursor.return_value.execute.call_args.args[0]
        params = conn.cursor.return_value.execute.call_args.args[1]
        assert "a.query ILIKE %s" in select_sql
        assert "a.outcome = %s" in select_sql
        assert "a.created_at >= %s" in select_sql
        assert "a.created_at <= %s" in select_sql
        assert params[0] == "%credit%"
        assert params[1] == "answer"
