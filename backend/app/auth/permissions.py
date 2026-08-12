"""Permission helpers for role-based access control.

Defines the action/resource matrix used by admin endpoints.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.auth.rbac import ADMIN_ROLES


def require_role(user: dict | None, role: str) -> None:
    """Raise 403 if the user's role doesn't meet the minimum requirement.

    Role hierarchy (higher = more permissive):
    super_admin > admin > loan_officer > underwriter > compliance

    Fail-closed for the client audience and unknown roles: a client token
    must never satisfy a staff role check by falling through.
    """
    hierarchy = ["compliance", "underwriter", "loan_officer", "admin", "super_admin"]

    if user is None or user.get("audience") == "client":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client accounts cannot perform staff actions",
        )

    user_role = user.get("role", "loan_officer")

    try:
        user_idx = hierarchy.index(user_role)
        required_idx = hierarchy.index(role)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user_role}' cannot perform this action (requires '{role}')",
        )

    if user_idx < required_idx:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user_role}' cannot perform this action (requires '{role}')",
        )


def require_manage_governance(user: dict | None) -> None:
    """H7: only admin / super_admin may edit governance configuration.

    Implemented as a capability check so it stays config-consistent:
    ``roles_config.can`` short-circuits ``True`` for the admin roles, so a
    client or lower staff token is always denied.
    """
    from app.auth.roles_config import can as roles_can

    if user is None or not roles_can(user.get("role", ""), "manage_governance"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Role cannot manage governance configuration",
        )
