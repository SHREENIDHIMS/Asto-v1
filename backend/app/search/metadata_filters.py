"""RBAC metadata filters: translate user scope into SQL WHERE clause.

Per CLAUDE.md rule #1: RBAC and active-version filtering happen in the
Postgres WHERE clause at query time — never as a post-hoc check only.

This is the PRIMARY enforcement point.

Dual-audience scoping (Phase B):
- super_admin / admin        → no filter ("").
- client audience            → documents where `client_id` = their own id.
- staff (loan officer, etc.) → department filter AND
    (company-wide docs `client_id IS NULL` OR docs of clients assigned to
    that staff member via staff_client_assignments).
"""

from __future__ import annotations

from typing import Any, Sequence

import psycopg


def _assigned_client_ids(conn: psycopg.Connection, user_id: int) -> list[int]:
    """Resolve the client ids assigned to a staff member at query time.

    Looked up in the DB (not the JWT) so assignment changes take effect
    immediately and revocations are honored — per CLAUDE.md rule #1.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT client_id FROM staff_client_assignments WHERE user_id = %s",
            (user_id,),
        )
        rows = cur.fetchall()
    return [int(r["client_id"]) for r in rows]


def get_search_filter(
    user: dict | None,
    conn: psycopg.Connection | None = None,
    assigned_client_ids: Sequence[int] | None = None,
) -> tuple[str, list]:
    """Build the RBAC WHERE clause fragment and parameters for search.

    Returns (clause, params). The clause is appended to the SQL query's
    WHERE clause. If the user is admin, returns ("", []) — no filtering.
    If the user has no departments, returns ("1=0", []) — deny all.

    ``conn`` is required to resolve a staff member's assigned clients; pass
    ``assigned_client_ids`` directly to skip the lookup (or if pre-resolved).
    """
    from app.auth.rbac import is_admin, resolve_user_departments

    if is_admin(user):
        return "", []

    if user is None:
        return "1=0", []  # deny all if unauthenticated

    # --- Client audience: own documents only ---
    if user.get("audience") == "client":
        client_id = user.get("client_id")
        if not client_id:
            return "1=0", []
        return "d.client_id = %s", [client_id]

    # --- Staff audience: department scope ∩ client assignments ---
    departments = resolve_user_departments(user)
    if not departments:
        return "1=0", []  # deny all if no departments resolved

    if assigned_client_ids is None and conn is not None:
        user_id = user.get("id")
        if user_id is not None:
            try:
                numeric_id = int(user_id)
            except (TypeError, ValueError):
                numeric_id = None
            if numeric_id is not None:
                assigned_client_ids = _assigned_client_ids(conn, numeric_id)

    dept_placeholders = ",".join(["%s"] * len(departments))
    dept_clause = f"d.department = ANY(ARRAY[{dept_placeholders}]::text[])"

    if assigned_client_ids:
        client_ids = [int(c) for c in assigned_client_ids]
        client_placeholders = ",".join(["%s"] * len(client_ids))
        client_clause = (
            f"(d.client_id IS NULL OR "
            f"d.client_id = ANY(ARRAY[{client_placeholders}]::bigint[]))"
        )
        clause = f"({dept_clause} AND {client_clause})"
        return clause, [*departments, *client_ids]

    # No assigned clients → staff only sees company-wide documents
    clause = f"({dept_clause} AND d.client_id IS NULL)"
    return clause, departments


def get_version_filter(is_approved: bool = True, is_active: bool = True) -> tuple[str, list]:
    """Build the active-version filter clause.

    Only returns approved + active chunks by default.
    """
    conditions: list[str] = []
    params: list = []

    if is_approved:
        conditions.append("c.is_approved = true")
    if is_active:
        conditions.append("c.is_active = true")

    clause = " AND ".join(conditions) if conditions else "(true)"
    return clause, params
