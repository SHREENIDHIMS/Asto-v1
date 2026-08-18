"""Tests for J7 — saved searches (staff-only CRUD, per-user scoping).

Unit tests mock the DB via dependency override + ``session.acquire`` patch.
DB-backed scoping tests live in ``tests/integration/test_saved_searches.py``
(the unit conftest mocks every ``acquire`` call).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import require_auth

STAFF_USER = {
    "id": 1,
    "email": "staff@asto.local",
    "full_name": "Staff User",
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


def _client():
    return TestClient(app)


class TestSavedSearches:
    def test_list_empty(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        cur = conn.cursor.return_value
        cur.__enter__.return_value = cur
        cur.fetchall.return_value = []

        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = _client().get("/api/v1/staff/saved-searches")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["saved_searches"] == []

    def test_save_search(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        cur = conn.cursor.return_value
        cur.__enter__.return_value = cur
        cur.fetchone.side_effect = [
            {"n": 0},  # count before insert
            {"id": 10, "query": "credit score", "filters": {"departments": ["general"]},
             "created_at": "2026-08-15T00:00:00Z"},  # INSERT RETURNING
        ]

        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = _client().post(
                    "/api/v1/staff/saved-searches",
                    json={"query": "credit score", "filters": {"departments": ["general"]}},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 201
        body = response.json()
        assert body["id"] == 10
        assert body["query"] == "credit score"

        insert_sql = [c.args[0] for c in cur.execute.call_args_list
                      if "INSERT INTO saved_searches" in c.args[0]]
        assert insert_sql, "INSERT not issued"
        assert "user_id" in insert_sql[0]

    def test_save_search_rejects_client(self):
        app.dependency_overrides[require_auth] = lambda: CLIENT_USER
        try:
            response = _client().post(
                "/api/v1/staff/saved-searches",
                json={"query": "credit score"},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 403

    def test_list_rejects_client(self):
        app.dependency_overrides[require_auth] = lambda: CLIENT_USER
        try:
            response = _client().get("/api/v1/staff/saved-searches")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 403

    def test_delete_own_search(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        cur = conn.cursor.return_value
        cur.__enter__.return_value = cur
        cur.rowcount = 1

        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = _client().delete("/api/v1/staff/saved-searches/10")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 204
        delete_sql = [c.args[0] for c in cur.execute.call_args_list
                      if "DELETE FROM saved_searches" in c.args[0]]
        assert delete_sql
        # The WHERE must scope to the caller's own id (rule #1).
        args = cur.execute.call_args_list[
            [c.args[0] for c in cur.execute.call_args_list].index(delete_sql[0])
        ].args[1]
        assert STAFF_USER["id"] in args

    def test_delete_missing_404(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        cur = conn.cursor.return_value
        cur.__enter__.return_value = cur
        cur.rowcount = 0

        app.dependency_overrides[require_auth] = lambda: STAFF_USER
        try:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = _client().delete("/api/v1/staff/saved-searches/999")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
