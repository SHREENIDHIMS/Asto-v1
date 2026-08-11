"""Config-driven source of truth for roles, departments, and permissions.

Admin-editable in concept (Phase F3), but read-only for now: this module is
the single source of truth that ``app/auth/rbac.py`` enforcement is derived
from. Changes here change what the admin Roles & Permissions / Departments
views render, and should stay in sync with any permission changes in
``rbac.py`` / ``permissions.py``.

Kept as Python (not YAML) to avoid a new runtime dependency; the shape is
plain data so it could be swapped to YAML/DB later without callers changing.
"""

from __future__ import annotations

# Role -> departments they can access. [] means "all departments".
# Mirrors ROLE_DEPARTMENTS in app/auth/rbac.py.
ROLE_DEPARTMENTS: dict[str, list[str]] = {
    "super_admin": [],
    "admin": [],
    "loan_officer": ["general"],
    "underwriter": ["general"],
    "compliance": ["general"],
}

# Roles that bypass department filtering entirely (rbac.ADMIN_ROLES).
ADMIN_ROLES: set[str] = {"super_admin", "admin"}

# Role hierarchy, lowest -> highest (permissions.require_role).
ROLE_HIERARCHY: list[str] = [
    "compliance",
    "underwriter",
    "loan_officer",
    "admin",
    "super_admin",
]

DEFAULT_DEPARTMENT: str = "general"

# Action-level capabilities per role (Phase Session 9, decision #2).
# Additive on top of department access. An empty list means the role has no
# special capabilities beyond its department scope.
ROLE_CAPABILITIES: dict[str, list[str]] = {
    "super_admin": ["onboard_clients"],
    "admin": ["onboard_clients"],
    "loan_officer": ["onboard_clients"],
    "underwriter": [],
    "compliance": [],
}


def can(role: str, capability: str) -> bool:
    """Whether a role has an action-level capability.

    Admins/super_admins always satisfy any capability check; otherwise the
    capability must be listed for the role. This is the single lookup used
    by the onboarding endpoint so a future CRM-driven workflow can stay
    config-driven.
    """
    if role in ADMIN_ROLES:
        return True
    return capability in ROLE_CAPABILITIES.get(role, [])


# Human-facing labels + descriptions for the admin governance views.
ROLES: list[dict] = [
    {
        "name": "super_admin",
        "label": "Super Admin",
        "description": "Full access to every department and all admin actions.",
        "access": "all",
    },
    {
        "name": "admin",
        "label": "Admin",
        "description": "Administrative actions; sees documents in all departments.",
        "access": "all",
    },
    {
        "name": "loan_officer",
        "label": "Loan Officer",
        "description": "General department knowledge, case work, and client onboarding.",
        "access": ["general"],
    },
    {
        "name": "underwriter",
        "label": "Underwriter",
        "description": "General department knowledge and case work.",
        "access": ["general"],
    },
    {
        "name": "compliance",
        "label": "Compliance",
        "description": "General department knowledge and compliance review.",
        "access": ["general"],
    },
]

# Departments that exist across the system. Free-string today; this is the
# display list for the admin Departments view.
DEPARTMENTS: list[dict] = [
    {"name": "general", "label": "General", "description": "Default department for most documents and users."},
    {"name": "underwriting", "label": "Underwriting", "description": "Loan underwriting policy and guidelines."},
    {"name": "compliance", "label": "Compliance", "description": "Regulatory and internal compliance documents."},
]


def role_access(role: str) -> list[str] | None:
    """Return accessible departments for a role, or None if all."""
    depts = ROLE_DEPARTMENTS.get(role)
    if depts is None:
        return None
    return depts if depts else None
