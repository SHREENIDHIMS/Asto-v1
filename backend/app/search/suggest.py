"""Query-suggestion service (J4).

Returns prefix-matched suggestions from past successful queries, scoped to
the caller (CLAUDE.md rule #1 — the scope is enforced in the SQL WHERE, not
as a post-hoc filter):

- admin / super_admin → all successful queries
- client audience     → only the caller's own past queries
- staff               → only queries from users whose department is within
  the caller's resolved department scope

The source is ``audit_log`` rows whose outcome was ``answer`` or
``partial`` (queries that actually retrieved something). Suggestions are
distinct, ranked by frequency then recency, capped at a small limit. No LLM
anywhere — this is a deterministic SQL prefix match.
"""

from __future__ import annotations

import re

import psycopg

from app.auth.rbac import is_admin, resolve_user_departments

DEFAULT_LIMIT = 8

_LIKE_ESCAPE_RE = re.compile(r"[%_\\]")


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards so user input is matched literally."""
    return _LIKE_ESCAPE_RE.sub(lambda m: f"\\{m.group(0)}", value)


def _scope_clause(user: dict | None) -> tuple[str, list]:
    """Build the RBAC scope fragment for the suggestion query.

    The audit_log's ``user_id`` alone is ambiguous across audiences (a
    staff member and a client can both have id 1), so scoping also keys on
    the ``audience`` column recorded at log time (J4). Rows written before
    the audience column existed carry NULL and are only visible to admins.
    """
    if user is None or is_admin(user):
        return "TRUE", []

    if user.get("audience") == "client":
        client_id = user.get("client_id") or user.get("id")
        if not client_id:
            return "1=0", []
        return "user_id = %s AND audience = 'client'", [client_id]

    departments = resolve_user_departments(user)
    if not departments:
        return "1=0", []

    placeholders = ", ".join(["%s"] * len(departments))
    clause = (
        "user_id IN (SELECT id FROM users WHERE department = "
        f"ANY(ARRAY[{placeholders}]::text[]))"
        " AND (audience IS NULL OR audience != 'client')"
    )
    return clause, departments


def suggest_queries(
    conn: psycopg.Connection,
    prefix: str,
    user: dict | None,
    limit: int = DEFAULT_LIMIT,
) -> list[str]:
    """Return distinct successful past queries that start with ``prefix``.

    Case-insensitive prefix match, scoped to the caller's access. Empty or
    whitespace-only prefixes always return an empty list.
    """
    query_text = (prefix or "").strip()
    if not query_text:
        return []

    scope_clause, scope_params = _scope_clause(user)
    escaped = _escape_like(query_text)

    sql = f"""
    SELECT query, COUNT(*) AS uses, MAX(created_at) AS last_used
    FROM audit_log
    WHERE outcome IN ('answer', 'partial')
      AND lower(query) LIKE lower(%s) ESCAPE '\\'
      AND {scope_clause}
    GROUP BY query
    ORDER BY uses DESC, last_used DESC
    LIMIT %s
    """
    params: list = [f"{escaped}%", *scope_params, limit]

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [str(r["query"]) for r in rows]
