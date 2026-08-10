"""Unit tests for Phase F7 admin audit log endpoint.

Covers: route wiring, auth requirements, client denial, filter clauses
(q/actor/outcome/from/to), pagination, total count, and payload shape.
"""

from __future__ import annotations

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
    "created_at": None,
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
    return conn


def _teardown():
    from app.main import app
    from app.dependencies import require_auth
    app.dependency_overrides.pop(require_auth, None)


class TestAuditLogRoutes:
    def test_route_exists(self):
        from app.main import app
        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/admin/audit" in paths

    def test_requires_auth(self):
        from app.main import app
        assert TestClient(app).get("/api/v1/admin/audit").status_code == 401

    def test_denies_client(self):
        try:
            response = _authorized(CLIENT_USER).get("/api/v1/admin/audit")
        finally:
            _teardown()
        assert response.status_code == 403


class TestAuditLogContent:
    def test_returns_paginated_entries(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"n": 1}
        cur.fetchall.return_value = [AUDIT_ROW]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get("/api/v1/admin/audit")
            finally:
                _teardown()

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["limit"] == 50
        assert data["offset"] == 0
        entry = data["entries"][0]
        assert entry["query"] == "minimum credit score"
        assert entry["outcome"] == "answer"
        assert entry["actor"] == "Admin User"
        assert entry["actor_email"] == "admin@asto.local"
        assert entry["response_id"] == "resp-1"

    def test_applies_q_filter(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"n": 0}
        cur.fetchall.return_value = []
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get(
                    "/api/v1/admin/audit?q=credit"
                )
            finally:
                _teardown()

        assert response.status_code == 200
        select_sql = cur.execute.call_args_list[1].args[0]
        assert "a.query ILIKE %s" in select_sql
        params = cur.execute.call_args_list[1].args[1]
        assert params[0] == "%credit%"

    def test_applies_actor_filter(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"n": 0}
        cur.fetchall.return_value = []
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get(
                    "/api/v1/admin/audit?actor=admin"
                )
            finally:
                _teardown()

        assert response.status_code == 200
        select_sql = cur.execute.call_args_list[1].args[0]
        assert "u.email ILIKE %s" in select_sql
        assert "c.full_name ILIKE %s" in select_sql

    def test_applies_outcome_filter(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"n": 0}
        cur.fetchall.return_value = []
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get(
                    "/api/v1/admin/audit?outcome=no_answer"
                )
            finally:
                _teardown()

        assert response.status_code == 200
        select_sql = cur.execute.call_args_list[1].args[0]
        assert "a.outcome = %s" in select_sql
        assert cur.execute.call_args_list[1].args[1][0] == "no_answer"

    def test_applies_date_range(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"n": 0}
        cur.fetchall.return_value = []
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get(
                    "/api/v1/admin/audit?from=2026-08-01&to=2026-08-10"
                )
            finally:
                _teardown()

        assert response.status_code == 200
        select_sql = cur.execute.call_args_list[1].args[0]
        assert "a.created_at >= %s" in select_sql
        assert "a.created_at <= %s" in select_sql

    def test_pagination_params(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"n": 0}
        cur.fetchall.return_value = []
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                response = _authorized(ADMIN_USER).get(
                    "/api/v1/admin/audit?limit=10&offset=20"
                )
            finally:
                _teardown()

        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 10
        assert data["offset"] == 20
        params = cur.execute.call_args_list[1].args[1]
        assert params[-2:] == [10, 20]

    def test_rejects_bad_limit(self):
        try:
            response = _authorized(ADMIN_USER).get("/api/v1/admin/audit?limit=0")
        finally:
            _teardown()
        assert response.status_code == 422
