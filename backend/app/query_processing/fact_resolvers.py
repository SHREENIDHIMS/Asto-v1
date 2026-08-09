"""Structured-fact resolvers (Phase 1 dual-path assistant).

Deterministic SQL lookups against the operational schema. Every resolver
binds row-level security parameters in the SQL WHERE clause BEFORE
execution (CLAUDE.md rule #1) — never as a post-hoc filter:

- client audience → ``c.client_id = <jwt client_id>``
- staff           → case belongs to an assigned client
                    (``staff_client_assignments``)
- admin/super_admin → no client filter (still respects explicit case id)

Per docs/architecture/dual_path_assistant.md §4:
- RLS params derive from the JWT, never from the request body.
- Missing/inaccessible case → ``FactResult(accessible=False, reason=...)``,
  which the caller turns into a ``no_answer`` package — never a fabricated
  or empty value.
- Every fact carries a verbatim value + an explicit source
  (``cases#204``, ``case_events#42``), identical trust posture to document
  citations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import psycopg

from app.auth.rbac import is_admin


@dataclass
class FactContext:
    """Authorization + entity context for a fact-path query."""

    user: dict                # decoded/verified JWT claims
    case_id: int | None       # fixed per conversation (may be None)
    client_id: int | None     # from JWT for client audience


@dataclass
class FactRecord:
    """One verbatim structured fact with an explicit source."""

    label: str
    value: str | int | float | None
    source: str               # "cases#204" | "case_events#42" | ...
    kind: str                 # status | date | document | amount | note | ...
    retrieved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class FactResult:
    """Outcome of a resolver. ``accessible=False`` ⇒ no_answer package."""

    accessible: bool
    facts: list[FactRecord] = field(default_factory=list)
    reason: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fmt_amount(value) -> str:
    """Format a NUMERIC loan amount deterministically (2 decimal places)."""
    if value is None:
        return ""
    try:
        return f"{value:.2f}"
    except (TypeError, ValueError):
        return str(value)


def _case_scope(user: dict) -> tuple[str, list]:
    """Return (WHERE clause fragment, params) scoping ``c`` to the caller.

    ``c`` is the alias used for the ``cases`` table in every resolver.
    """
    if is_admin(user):
        return "true", []
    if user.get("audience") == "client":
        client_id = user.get("client_id")
        if not client_id:
            return "false", []
        return "c.client_id = %s", [client_id]
    user_id = user.get("id")
    if not user_id:
        return "false", []
    return (
        "EXISTS (SELECT 1 FROM staff_client_assignments sca "
        "WHERE sca.client_id = c.client_id AND sca.user_id = %s)",
        [user_id],
    )


def _load_case(conn: psycopg.Connection, ctx: FactContext) -> dict | None:
    """Fetch the conversation's case row scoped by RLS, or None if absent/forbidden."""
    if ctx.case_id is None:
        return None
    scope, params = _case_scope(ctx.user)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT c.id, c.case_number, c.client_id, c.property_id, "
            f"c.loan_amount, c.status, c.created_at "
            f"FROM cases c WHERE c.id = %s AND {scope} AND c.is_active = true",
            [ctx.case_id, *params],
        )
        row = cur.fetchone()
    return dict(row) if row else None


def _resolve_case_status(conn: psycopg.Connection, ctx: FactContext) -> FactResult:
    case = _load_case(conn, ctx)
    if case is None:
        return FactResult(
            accessible=False,
            reason="Case not found, not active, or you do not have access to it.",
        )
    facts: list[FactRecord] = [
        FactRecord(
            label="Case number",
            value=case["case_number"],
            source=f"cases#{case['id']}",
            kind="number",
        ),
        FactRecord(
            label="Status",
            value=case["status"],
            source=f"cases#{case['id']}",
            kind="status",
        ),
    ]
    if case["loan_amount"] is not None:
        facts.append(
            FactRecord(
                label="Loan amount",
                value=_fmt_amount(case["loan_amount"]),
                source=f"cases#{case['id']}",
                kind="amount",
            )
        )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, status, note, created_at FROM case_events "
            "WHERE case_id = %s ORDER BY created_at DESC, id DESC LIMIT 1",
            (ctx.case_id,),
        )
        ev = cur.fetchone()
    if ev is not None:
        facts.append(
            FactRecord(
                label="Latest update",
                value=ev["status"],
                source=f"case_events#{ev['id']}",
                kind="status",
            )
        )
        if ev["note"]:
            facts.append(
                FactRecord(
                    label="Latest note",
                    value=ev["note"],
                    source=f"case_events#{ev['id']}",
                    kind="note",
                )
            )
    return FactResult(accessible=True, facts=facts)


def _resolve_case_next_step(conn: psycopg.Connection, ctx: FactContext) -> FactResult:
    case = _load_case(conn, ctx)
    if case is None:
        return FactResult(
            accessible=False,
            reason="Case not found, not active, or you do not have access to it.",
        )
    facts: list[FactRecord] = []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, status, note, created_at FROM case_events "
            "WHERE case_id = %s ORDER BY created_at DESC, id DESC LIMIT 1",
            (ctx.case_id,),
        )
        ev = cur.fetchone()
        if ev is not None and ev["note"]:
            facts.append(
                FactRecord(
                    label="Latest update",
                    value=ev["note"],
                    source=f"case_events#{ev['id']}",
                    kind="note",
                )
            )
        cur.execute(
            "SELECT id, title, status FROM workflows "
            "WHERE case_id = %s ORDER BY updated_at DESC, id DESC LIMIT 1",
            (ctx.case_id,),
        )
        wf = cur.fetchone()
    if wf is not None:
        facts.append(
            FactRecord(
                label="Workflow",
                value=wf["title"],
                source=f"workflows#{wf['id']}",
                kind="workflow",
            )
        )
        facts.append(
            FactRecord(
                label="Workflow status",
                value=wf["status"],
                source=f"workflows#{wf['id']}",
                kind="status",
            )
        )
    return FactResult(accessible=True, facts=facts)


def _resolve_missing_documents(conn: psycopg.Connection, ctx: FactContext) -> FactResult:
    case = _load_case(conn, ctx)
    if case is None:
        return FactResult(
            accessible=False,
            reason="Case not found, not active, or you do not have access to it.",
        )
    facts: list[FactRecord] = []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, title, doc_type FROM documents "
            "WHERE client_id = %s AND approval_status = 'pending' "
            "AND is_active = true ORDER BY created_at DESC, id DESC",
            (case["client_id"],),
        )
        pending = cur.fetchall()
    for doc in pending:
        facts.append(
            FactRecord(
                label="Pending document",
                value=doc["title"],
                source=f"documents#{doc['id']}",
                kind="document",
            )
        )
    facts.append(
        FactRecord(
            label="Pending documents",
            value=len(pending),
            source=f"cases#{case['id']}",
            kind="count",
        )
    )
    return FactResult(accessible=True, facts=facts)


def _resolve_case_documents(conn: psycopg.Connection, ctx: FactContext) -> FactResult:
    case = _load_case(conn, ctx)
    if case is None:
        return FactResult(
            accessible=False,
            reason="Case not found, not active, or you do not have access to it.",
        )
    facts: list[FactRecord] = []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, title, doc_type FROM documents "
            "WHERE client_id = %s AND approval_status = 'approved' "
            "AND is_active = true ORDER BY created_at DESC, id DESC",
            (case["client_id"],),
        )
        approved = cur.fetchall()
    for doc in approved:
        facts.append(
            FactRecord(
                label="Document",
                value=doc["title"],
                source=f"documents#{doc['id']}",
                kind="document",
            )
        )
    facts.append(
        FactRecord(
            label="Approved documents",
            value=len(approved),
            source=f"cases#{case['id']}",
            kind="count",
        )
    )
    return FactResult(accessible=True, facts=facts)


def _resolve_case_property(conn: psycopg.Connection, ctx: FactContext) -> FactResult:
    case = _load_case(conn, ctx)
    if case is None:
        return FactResult(
            accessible=False,
            reason="Case not found, not active, or you do not have access to it.",
        )
    if case["property_id"] is None:
        return FactResult(
            accessible=True,
            facts=[
                FactRecord(
                    label="Property",
                    value="Not linked",
                    source=f"cases#{case['id']}",
                    kind="property",
                )
            ],
        )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, address, city, state, postal_code, property_type "
            "FROM properties WHERE id = %s AND is_active = true",
            (case["property_id"],),
        )
        prop = cur.fetchone()
    if prop is None:
        return FactResult(accessible=True, facts=[])
    facts = [
        FactRecord(
            label="Property address",
            value=", ".join(
                [p for p in (prop["address"], prop["city"], prop["state"], prop["postal_code"]) if p]
            ),
            source=f"properties#{prop['id']}",
            kind="property",
        )
    ]
    if prop["property_type"]:
        facts.append(
            FactRecord(
                label="Property type",
                value=prop["property_type"],
                source=f"properties#{prop['id']}",
                kind="property",
            )
        )
    return FactResult(accessible=True, facts=facts)


def _resolve_case_timeline(conn: psycopg.Connection, ctx: FactContext) -> FactResult:
    case = _load_case(conn, ctx)
    if case is None:
        return FactResult(
            accessible=False,
            reason="Case not found, not active, or you do not have access to it.",
        )
    facts: list[FactRecord] = []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, status, note, created_at FROM case_events "
            "WHERE case_id = %s ORDER BY created_at ASC, id ASC",
            (ctx.case_id,),
        )
        events = cur.fetchall()
    for ev in events:
        value = ev["status"]
        if ev["note"]:
            value = f"{value} — {ev['note']}"
        facts.append(
            FactRecord(
                label="Event",
                value=value,
                source=f"case_events#{ev['id']}",
                kind="event",
            )
        )
    return FactResult(accessible=True, facts=facts)


def _resolve_workflow_step(conn: psycopg.Connection, ctx: FactContext) -> FactResult:
    case = _load_case(conn, ctx)
    if case is None:
        return FactResult(
            accessible=False,
            reason="Case not found, not active, or you do not have access to it.",
        )
    facts: list[FactRecord] = []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, title, status, updated_at FROM workflows "
            "WHERE case_id = %s ORDER BY updated_at DESC, id DESC",
            (ctx.case_id,),
        )
        workflows = cur.fetchall()
    for wf in workflows:
        facts.append(
            FactRecord(
                label="Workflow",
                value=wf["title"],
                source=f"workflows#{wf['id']}",
                kind="workflow",
            )
        )
        facts.append(
            FactRecord(
                label="Workflow status",
                value=wf["status"],
                source=f"workflows#{wf['id']}",
                kind="status",
            )
        )
    return FactResult(accessible=True, facts=facts)


def _resolve_client_financials(conn: psycopg.Connection, ctx: FactContext) -> FactResult:
    case = _load_case(conn, ctx)
    if case is None:
        return FactResult(
            accessible=False,
            reason="Case not found, not active, or you do not have access to it.",
        )
    facts: list[FactRecord] = []
    if case["loan_amount"] is not None:
        facts.append(
            FactRecord(
                label="Loan amount",
                value=_fmt_amount(case["loan_amount"]),
                source=f"cases#{case['id']}",
                kind="amount",
            )
        )
    return FactResult(accessible=True, facts=facts)


RESOLVERS: dict[str, Callable[[psycopg.Connection, FactContext], FactResult]] = {
    "case_status": _resolve_case_status,
    "case_next_step": _resolve_case_next_step,
    "missing_documents": _resolve_missing_documents,
    "case_documents": _resolve_case_documents,
    "case_property": _resolve_case_property,
    "case_timeline": _resolve_case_timeline,
    "workflow_step": _resolve_workflow_step,
    "client_financials": _resolve_client_financials,
}


def resolve_fact(
    conn: psycopg.Connection,
    intent: str,
    ctx: FactContext,
) -> FactResult:
    """Run the resolver for ``intent`` with RLS scoped by ``ctx``."""
    resolver = RESOLVERS.get(intent)
    if resolver is None:
        return FactResult(
            accessible=False,
            reason="This question has no supported structured answer.",
        )
    return resolver(conn, ctx)
