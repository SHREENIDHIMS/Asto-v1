"""Phase M8 — feature flags: table-backed gates, admin toggles, gating.

Covers: default fallback, DB override, cache refresh, admin list/set
endpoints (audit-logged), and the ``audit_export`` gate on the M1 endpoint.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import require_auth

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


@pytest.fixture(autouse=True)
def _reset_flag_cache():
    """Reset the shared module cache so a fake snapshot never leaks to
    other test files (e.g. the M1 export suite expects ``audit_export`` on)."""
    from app import feature_flags as ff

    ff._cache.clear()
    ff._cache_loaded_at = 0.0
    yield
    ff._cache.clear()
    ff._cache_loaded_at = 0.0


def _authorized(user: dict) -> TestClient:
    app.dependency_overrides[require_auth] = lambda: user
    return TestClient(app)


def _teardown():
    app.dependency_overrides.pop(require_auth, None)


class FakeTable:
    """In-memory stand-in for the feature_flags table."""

    def __init__(self, rows: dict[str, bool] | None = None):
        self.rows: dict[str, bool] = dict(rows or {})

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def commit(self):
        pass

    def cursor(self):
        class Cursor:
            def __init__(self, table):
                self._table = table
                self._params = None

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params=None):
                self._sql = sql
                self._params = params
                if "INSERT INTO feature_flags" in sql:
                    name, enabled = params
                    self._table.rows[name] = bool(enabled)

            def fetchall(self):
                if "SELECT name, enabled FROM feature_flags" in self._sql:
                    return [{"name": name, "enabled": enabled} for name, enabled in self._table.rows.items()]
                if "SELECT name FROM feature_flags" in self._sql:
                    return [{"name": name} for name in self._table.rows]
                return []

        return Cursor(self)


class TestFlagGating:
    def test_default_fallback_when_table_empty(self, monkeypatch):
        from app import feature_flags as ff

        monkeypatch.setattr(ff.session, "acquire", FakeTable({}))
        ff._cache.clear()
        assert ff.is_enabled("audit_export") is True

    def test_unknown_flag_defaults_false(self, monkeypatch):
        from app import feature_flags as ff

        monkeypatch.setattr(ff.session, "acquire", FakeTable({}))
        ff._cache.clear()
        assert ff.is_enabled("totally_unknown_flag") is False

    def test_db_row_overrides_default(self, monkeypatch):
        from app import feature_flags as ff

        monkeypatch.setattr(ff.session, "acquire", FakeTable({"audit_export": False}))
        ff._cache.clear()
        ff._cache_loaded_at = 0.0
        assert ff.is_enabled("audit_export") is False

    def test_cache_ttl_refresh_picks_up_row_change(self, monkeypatch):
        import time

        from app import feature_flags as ff

        table = FakeTable({"audit_export": True})
        monkeypatch.setattr(ff.session, "acquire", table)
        ff._cache.clear()
        ff._cache_loaded_at = 0.0
        assert ff.is_enabled("audit_export") is True

        table.rows["audit_export"] = False
        ff._cache_loaded_at = time.monotonic() - ff._CACHE_TTL_SECONDS - 1
        assert ff.is_enabled("audit_export") is False

    def test_db_failure_falls_back_to_default(self, monkeypatch):
        from app import feature_flags as ff

        def boom():
            raise RuntimeError("db down")

        monkeypatch.setattr(ff.session, "acquire", boom)
        ff._cache.clear()
        ff._cache_loaded_at = 0.0
        assert ff.is_enabled("audit_export") is True


class TestAdminFlagEndpoints:
    def test_route_exists(self):
        from app.main import app as main_app

        paths = list(main_app.openapi()["paths"].keys())
        assert "/api/v1/admin/flags" in paths

    def test_list_flags_requires_admin(self):
        from app.main import app as main_app

        assert TestClient(main_app).get("/api/v1/admin/flags").status_code == 401

    def test_list_flags_reports_source(self, monkeypatch):
        from app import feature_flags as ff

        monkeypatch.setattr(ff.session, "acquire", FakeTable({"audit_export": True}))
        ff._cache.clear()
        ff._cache_loaded_at = 0.0

        client = _authorized(ADMIN_USER)
        try:
            res = client.get("/api/v1/admin/flags")
        finally:
            _teardown()
        assert res.status_code == 200
        flags = res.json()["flags"]
        assert any(f["name"] == "audit_export" for f in flags)
        audit_export = next(f for f in flags if f["name"] == "audit_export")
        assert audit_export["enabled"] is True
        assert audit_export["source"] == "table"

    def test_set_flag_upserts(self, monkeypatch):
        from app import feature_flags as ff

        table = FakeTable({})
        monkeypatch.setattr(ff.session, "acquire", table)

        client = _authorized(ADMIN_USER)
        try:
            res = client.post("/api/v1/admin/flags", json={"name": "audit_export", "enabled": False})
        finally:
            _teardown()
        assert res.status_code == 200
        assert res.json() == {"name": "audit_export", "enabled": False}
        assert table.rows.get("audit_export") is False

    def test_set_flag_requires_admin(self):
        from app.main import app as main_app

        res = TestClient(main_app).post(
            "/api/v1/admin/flags", json={"name": "audit_export", "enabled": True}
        )
        assert res.status_code == 401


class TestAuditExportGate:
    def test_export_403_when_flag_disabled(self, monkeypatch):
        from app import feature_flags as ff

        monkeypatch.setattr(ff, "is_enabled", lambda name: False)

        client = _authorized(ADMIN_USER)
        try:
            res = client.get("/api/v1/admin/audit/export")
        finally:
            _teardown()
        assert res.status_code == 403
        assert "Feature disabled" in res.json()["detail"]

    def test_export_allowed_when_flag_enabled(self, monkeypatch):
        from app import feature_flags as ff
        from app.api.v1 import admin as admin_mod

        monkeypatch.setattr(ff, "is_enabled", lambda name: True)

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def cursor(self):
                class Cur:
                    def __enter__(self):
                        return self

                    def __exit__(self, *exc):
                        return False

                    def execute(self, sql, params=None):
                        pass

                    def fetchall(self):
                        return []

                return Cur()

        monkeypatch.setattr(admin_mod.session, "acquire", Conn)

        client = _authorized(ADMIN_USER)
        try:
            res = client.get("/api/v1/admin/audit/export", params={"format": "json"})
        finally:
            _teardown()
        assert res.status_code == 200
        assert res.json() == {"entries": [], "count": 0}