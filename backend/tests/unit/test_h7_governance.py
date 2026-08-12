"""Unit tests for Phase H7: governance config write-back.

Covers ROADMAP H7 step 4:
- render_config produces valid Python that round-trips the edited values
- write_config persists atomically and reloads a module from the new file
- PUT /admin/governance persists + reloads, permission gating (403 for
  non-admins), invalid role name -> 422, unknown capability -> 422,
  department rename migrates every department column, and the change is
  audit-logged.

The DB is mocked (``app.db.postgres.session.acquire``) and the real
``roles_config.py`` is never written: the endpoint's write path is patched
to a throwaway temp module so tests stay hermetic.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import governance
from app.auth.roles_config import (
    DEPARTMENTS as CURRENT_DEPARTMENTS,
    ROLE_HIERARCHY as CURRENT_HIERARCHY,
    ROLES as CURRENT_ROLES,
)

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


def _current_payload() -> dict:
    """The GET shape the UI would send straight back after an edit."""
    return {
        "roles": [
            {
                "name": r["name"],
                "label": r["label"],
                "description": r["description"],
                "access": r["access"],
                "capabilities": [],
            }
            for r in CURRENT_ROLES
        ],
        "departments": [dict(d) for d in CURRENT_DEPARTMENTS],
        "role_hierarchy": list(CURRENT_HIERARCHY),
    }


@pytest.fixture
def authorized_client():
    """TestClient factory with the given identity overriding require_auth."""
    from app.main import app
    from app.dependencies import require_auth

    def _factory(user: dict) -> TestClient:
        app.dependency_overrides[require_auth] = lambda: user
        return TestClient(app)

    yield _factory
    app.dependency_overrides.pop(require_auth, None)


def _load_module(path):
    """Load a Python file as a fresh module (spec_from_file_location).

    The file's directory is added to ``sys.path`` so ``importlib.reload`` can
    re-find the module by name after the file is rewritten.
    """
    d = os.path.dirname(path)
    if d not in sys.path:
        sys.path.insert(0, d)
    spec = importlib.util.spec_from_file_location("governance_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestRenderConfig:
    def test_round_trips_edited_values(self):
        src = governance.render_config(
            roles=[
                {
                    "name": "loan_officer",
                    "label": "Loan Officer",
                    "description": "updated description",
                    "access": ["general", "underwriting"],
                    "capabilities": ["onboard_clients"],
                },
            ],
            departments=[
                {"name": "general", "label": "General", "description": "d"},
                {"name": "underwriting", "label": "Underwriting", "description": "u"},
            ],
            role_hierarchy=["loan_officer", "admin"],
            default_department="general",
        )
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rc.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(src)
            module = _load_module(path)

        assert module.ROLE_DEPARTMENTS["loan_officer"] == ["general", "underwriting"]
        assert module.ROLE_CAPABILITIES["loan_officer"] == ["onboard_clients"]
        assert module.ROLES[0]["description"] == "updated description"
        assert module.ROLE_HIERARCHY == ["loan_officer", "admin"]
        assert module.DEFAULT_DEPARTMENT == "general"
        assert module.ADMIN_ROLES == {"super_admin", "admin"}
        assert module.can("loan_officer", "onboard_clients") is True
        assert module.can("loan_officer", "nonexistent") is False
        assert module.role_access("loan_officer") == ["general", "underwriting"]
        assert module.role_access("admin") is None

    def test_all_access_becomes_empty_department_list(self):
        src = governance.render_config(
            roles=[
                {
                    "name": "admin",
                    "label": "Admin",
                    "description": "d",
                    "access": "all",
                    "capabilities": [],
                },
            ],
            departments=[{"name": "general", "label": "General", "description": "d"}],
            role_hierarchy=["admin"],
            default_department="general",
        )
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rc.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(src)
            module = _load_module(path)
        assert module.ROLE_DEPARTMENTS["admin"] == []
        assert module.ROLES[0]["access"] == "all"


class TestWriteConfig:
    def test_persists_and_reloads_from_new_file(self):
        """The atomic write lands and a reload re-executes the new content."""
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "governance_under_test.py")
            initial = governance.render_config(
                roles=[
                    {
                        "name": "admin",
                        "label": "Admin",
                        "description": "before",
                        "access": "all",
                        "capabilities": [],
                    },
                ],
                departments=[
                    {"name": "general", "label": "General", "description": "d"}
                ],
                role_hierarchy=["admin"],
                default_department="general",
            )
            with open(path, "w", encoding="utf-8") as f:
                f.write(initial)
            module = _load_module(path)

            governance.write_config(
                roles=[
                    {
                        "name": "admin",
                        "label": "Admin",
                        "description": "after",
                        "access": "all",
                        "capabilities": ["onboard_clients"],
                    },
                ],
                departments=[
                    {"name": "general", "label": "General", "description": "d"}
                ],
                role_hierarchy=["admin"],
                default_department="general",
                config_path=path,
                module=module,
            )

            with open(path, encoding="utf-8") as f:
                content = f.read()
            assert "after" in content
            # The same module object was reloaded from the new file.
            assert module.ROLES[0]["description"] == "after"
            assert module.ROLE_CAPABILITIES["admin"] == ["onboard_clients"]


class TestUpdateGovernance:
    def test_admin_can_update_and_it_persists(self, authorized_client, tmp_path):
        conn = _conn()
        payload = _current_payload()
        payload["roles"][0]["capabilities"] = ["onboard_clients"]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            with patch("app.auth.governance.write_config") as mock_write:
                response = authorized_client(ADMIN_USER).put(
                    "/api/v1/admin/governance", json=payload
                )

        assert response.status_code == 200
        body = response.json()
        assert body["roles"][0]["capabilities"] == ["onboard_clients"]
        assert mock_write.called
        assert mock_write.call_args.kwargs["roles"][0]["capabilities"] == ["onboard_clients"]
        calls = [a.args[0] for a in conn.cursor.return_value.execute.call_args_list]
        assert any("INSERT INTO audit_log" in c for c in calls)

    def test_write_persists_to_disk(self, authorized_client, tmp_path):
        """The endpoint's write path lands a real file (via a temp path)."""
        conn = _conn()
        payload = _current_payload()
        target = tmp_path / "governance_under_test.py"
        real_write = governance.write_config
        with patch("app.db.postgres.session.acquire", return_value=conn):
            with patch("app.auth.governance.write_config") as mock_write:
                mock_write.side_effect = lambda **kw: real_write(
                    **kw, config_path=str(target), module=None
                )
                response = authorized_client(ADMIN_USER).put(
                    "/api/v1/admin/governance", json=payload
                )
        assert response.status_code == 200
        with open(target, encoding="utf-8") as f:
            content = f.read()
        assert "ROLE_DEPARTMENTS" in content
        assert "super_admin" in content

    def test_non_admin_403(self, authorized_client):
        conn = _conn()
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = authorized_client(STAFF_USER).put(
                "/api/v1/admin/governance", json=_current_payload()
            )
        assert response.status_code == 403

    def test_client_403(self, authorized_client):
        conn = _conn()
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = authorized_client(CLIENT_USER).put(
                "/api/v1/admin/governance", json=_current_payload()
            )
        assert response.status_code == 403

    def test_requires_auth(self):
        from app.main import app

        response = TestClient(app).put(
            "/api/v1/admin/governance", json=_current_payload()
        )
        assert response.status_code == 401

    def test_invalid_role_name_422(self, authorized_client):
        conn = _conn()
        payload = _current_payload()
        payload["roles"][0]["name"] = "not_a_role"
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = authorized_client(ADMIN_USER).put(
                "/api/v1/admin/governance", json=payload
            )
        assert response.status_code == 422

    def test_unknown_capability_422(self, authorized_client):
        conn = _conn()
        payload = _current_payload()
        payload["roles"][0]["capabilities"] = ["magic_powers"]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = authorized_client(ADMIN_USER).put(
                "/api/v1/admin/governance", json=payload
            )
        assert response.status_code == 422

    def test_invalid_department_name_422(self, authorized_client):
        conn = _conn()
        payload = _current_payload()
        payload["departments"][0]["name"] = "Bad Name!"
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = authorized_client(ADMIN_USER).put(
                "/api/v1/admin/governance", json=payload
            )
        assert response.status_code == 422

    def test_bad_role_access_department_422(self, authorized_client):
        conn = _conn()
        payload = _current_payload()
        payload["roles"][0]["access"] = ["ghost_department"]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = authorized_client(ADMIN_USER).put(
                "/api/v1/admin/governance", json=payload
            )
        assert response.status_code == 422

    def test_department_rename_migrates_columns(self, authorized_client):
        """Renaming the 2nd department positionally updates every table."""
        conn = _conn()
        payload = _current_payload()
        payload["departments"][1]["name"] = "regulatory"
        payload["departments"][1]["label"] = "Regulatory"
        # A role referencing the old name must be updated by the UI; here we
        # exercise the backend accepting the new name.
        for role in payload["roles"]:
            if isinstance(role["access"], list):
                role["access"] = [
                    "regulatory" if d == "underwriting" else d
                    for d in role["access"]
                ]

        with patch("app.auth.governance.write_config") as mock_write:
            mock_write.return_value = None
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = authorized_client(ADMIN_USER).put(
                    "/api/v1/admin/governance", json=payload
                )

        assert response.status_code == 200
        calls = [a.args[0] for a in conn.cursor.return_value.execute.call_args_list]
        rename_updates = [c for c in calls if "array_replace" in c]
        assert rename_updates, "expected allowed_departments migration"
        args = [
            a.args[1]
            for a in conn.cursor.return_value.execute.call_args_list
            if "array_replace" in a.args[0]
        ][0]
        assert args[0] == "underwriting"
        assert args[1] == "regulatory"
        # Config write-back received the renamed default tracking.
        assert mock_write.call_args.kwargs["default_department"] == "general"
        written_roles = mock_write.call_args.kwargs["roles"]
        assert written_roles == payload["roles"]

    def test_rename_general_updates_default_department(self, authorized_client):
        conn = _conn()
        payload = _current_payload()
        payload["departments"][0]["name"] = "lending"
        payload["departments"][0]["label"] = "Lending"
        for role in payload["roles"]:
            if isinstance(role["access"], list):
                role["access"] = ["lending" if d == "general" else d for d in role["access"]]

        with patch("app.auth.governance.write_config") as mock_write:
            mock_write.return_value = None
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = authorized_client(ADMIN_USER).put(
                    "/api/v1/admin/governance", json=payload
                )
        assert response.status_code == 200
        assert mock_write.call_args.kwargs["default_department"] == "lending"

    def test_no_write_on_validation_failure(self, authorized_client):
        """Nothing is written (and nothing logged) when validation fails."""
        conn = _conn()
        payload = _current_payload()
        payload["roles"][0]["name"] = "bad"
        with patch("app.auth.governance.write_config") as mock_write:
            with patch("app.db.postgres.session.acquire", return_value=conn):
                response = authorized_client(ADMIN_USER).put(
                    "/api/v1/admin/governance", json=payload
                )
        assert response.status_code == 422
        mock_write.assert_not_called()
        calls = [a.args[0] for a in conn.cursor.return_value.execute.call_args_list]
        assert not any("INSERT INTO audit_log" in c for c in calls)


class TestGetGovernance:
    def test_roles_include_capabilities(self, authorized_client):
        conn = _conn()
        with patch("app.db.postgres.session.acquire", return_value=conn):
            response = authorized_client(ADMIN_USER).get("/api/v1/admin/governance")
        assert response.status_code == 200
        for role in response.json()["roles"]:
            assert "capabilities" in role
