"""RBAC: resolve department access scope from the authenticated user.

The user's allowed departments are extracted from the JWT at request time
and passed to metadata_filters.py, which builds the WHERE clause fragment
that restricts search results to documents the user is permitted to see.

This is the PRIMARY enforcement point for RBAC — the WHERE clause in the
SQL query itself. Response validation does a redundant re-check as a
safety net (CLAUDE.md rule #1).
"""

from __future__ import annotations


# Role hierarchy: higher roles inherit lower scopes.
# Each role maps to the set of departments they can access.
# "super_admin" can access all departments.
ROLE_DEPARTMENTS: dict[str, list[str]] = {
    "super_admin": [],  # empty means "all departments"
    "admin": [],
    "loan_officer": ["general"],
    "underwriter": ["general"],
    "compliance": ["general"],
}

# Default department if none specified.
DEFAULT_DEPARTMENT: str = "general"

# Roles that bypass department filtering entirely.
ADMIN_ROLES: set[str] = {"super_admin", "admin"}


def resolve_user_departments(user: dict | None) -> list[str]:
    """Extract the full list of departments a user may access.

    A user can access:
    1. Their own department
    2. Any departments in their allowed_departments claim (from JWT)
    """
    if user is None:
        return []

    departments = {user.get("department", DEFAULT_DEPARTMENT)}
    departments.update(user.get("allowed_departments") or [])

    return sorted(departments)


def is_admin(user: dict | None) -> bool:
    """Check if the user has admin-level access (bypasses RBAC)."""
    if user is None:
        return False
    return user.get("role") in ADMIN_ROLES


def get_search_filter(user: dict | None) -> tuple[str, list[str]]:
    """Build the RBAC WHERE clause fragment and parameters for search.

    Returns (clause, params). The clause is appended to the SQL query's
    WHERE clause. If the user is admin, returns ("", []) — no filtering.
    """
    if is_admin(user):
        return "", []

    departments = resolve_user_departments(user)
    if not departments:
        return "1=0", []  # deny all if no departments resolved

    placeholders = ",".join(["%s"] * len(departments))
    clause = f"d.department = ANY(ARRAY[{placeholders}]::text[])"
    return clause, departments
