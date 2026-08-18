"""Unit tests for J4 — query suggestion helpers (no DB needed)."""

from __future__ import annotations

from app.search.suggest import _escape_like, _scope_clause


class TestEscapeLike:
    def test_plain_text_unchanged(self):
        assert _escape_like("credit") == "credit"

    def test_wildcards_escaped(self):
        assert _escape_like("100%") == "100\\%"
        assert _escape_like("a_b") == "a\\_b"

    def test_backslash_escaped(self):
        assert _escape_like("a\\b") == "a\\\\b"


class TestScopeClause:
    def test_admin_no_filter(self):
        clause, params = _scope_clause({
            "role": "super_admin",
            "department": "general",
            "allowed_departments": [],
        })
        assert clause == "TRUE"
        assert params == []

    def test_unauthenticated_no_filter(self):
        clause, params = _scope_clause(None)
        assert clause == "TRUE"
        assert params == []

    def test_client_own_scope(self):
        clause, params = _scope_clause({
            "audience": "client",
            "client_id": 42,
            "id": 42,
            "role": "client",
            "department": None,
            "allowed_departments": [],
        })
        assert clause == "user_id = %s AND audience = 'client'"
        assert params == [42]

    def test_staff_department_scope(self):
        clause, params = _scope_clause({
            "role": "loan_officer",
            "department": "general",
            "allowed_departments": ["underwriting"],
        })
        assert "users" in clause
        assert "audience != 'client'" in clause
        assert "general" in params
        assert "underwriting" in params

    def test_staff_no_departments_deny_all(self):
        clause, params = _scope_clause({
            "audience": "client",
            "role": "client",
            "department": None,
            "allowed_departments": [],
        })
        assert clause == "1=0"
