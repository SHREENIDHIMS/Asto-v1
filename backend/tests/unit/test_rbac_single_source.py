"""Unit tests for the single-source-of-truth RBAC fix (audit #17).

``require_role`` and ``rbac.is_admin`` previously hardcoded their own
copies of the hierarchy/admin-roles, so ``PUT /admin/governance`` (which
rewrites + reloads ``roles_config.py``) changed what the admin UI
rendered but NOT what enforcement did — a false control. Enforcement now
reads roles_config at call time, so a simulated reload changes behavior.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.auth import permissions, rbac, roles_config


@pytest.fixture()
def restore_roles_config():
    """Snapshot roles_config constants; restore after the test."""
    saved = (
        list(roles_config.ROLE_HIERARCHY),
        set(roles_config.ADMIN_ROLES),
        dict(roles_config.ROLE_DEPARTMENTS),
        roles_config.DEFAULT_DEPARTMENT,
    )
    yield
    (
        roles_config.ROLE_HIERARCHY,
        roles_config.ADMIN_ROLES,
        roles_config.ROLE_DEPARTMENTS,
        roles_config.DEFAULT_DEPARTMENT,
    ) = saved


STAFF = {"id": 2, "audience": "staff", "role": "loan_officer",
         "department": "general", "allowed_departments": []}


class TestRequireRoleUsesConfigHierarchy:
    def test_default_hierarchy_enforced(self):
        # loan_officer cannot act as admin under the default hierarchy.
        with pytest.raises(HTTPException) as exc:
            permissions.require_role(STAFF, "admin")
        assert exc.value.status_code == 403

    def test_hierarchy_edit_changes_enforcement(self, restore_roles_config):
        # Simulate a governance edit promoting loan_officer above admin.
        roles_config.ROLE_HIERARCHY[:] = [
            "compliance", "underwriter", "admin", "loan_officer", "super_admin",
        ]
        # No exception now — enforcement followed the config edit.
        permissions.require_role(STAFF, "admin")

    def test_unknown_role_fails_closed(self, restore_roles_config):
        roles_config.ROLE_HIERARCHY[:] = ["admin", "super_admin"]
        with pytest.raises(HTTPException) as exc:
            permissions.require_role(STAFF, "admin")
        assert exc.value.status_code == 403

    def test_client_token_always_denied(self):
        client = {"id": 7, "audience": "client", "role": "client"}
        with pytest.raises(HTTPException) as exc:
            permissions.require_role(client, "loan_officer")
        assert exc.value.status_code == 403


class TestRbacReadsConfig:
    def test_admin_roles_edit_changes_is_admin(self, restore_roles_config):
        assert rbac.is_admin(STAFF) is False
        # Governance edit grants loan_officer admin bypass.
        roles_config.ADMIN_ROLES.add("loan_officer")
        assert rbac.is_admin(STAFF) is True

    def test_default_department_edit_changes_resolution(self, restore_roles_config):
        user = {"id": 2, "audience": "staff", "role": "loan_officer",
                "allowed_departments": []}
        roles_config.DEFAULT_DEPARTMENT = "underwriting"
        assert rbac.resolve_user_departments(user) == ["underwriting"]
