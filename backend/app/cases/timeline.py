"""Case timeline auto-events.

Keeps the client-facing case timeline (``case_events``) current without
staff having to remember to update it: document approval/rejection and
workflow stage advances append events automatically.

Document→case resolution: a document links to a case through its
``property_id`` when set; otherwise it falls back to the owning client's
active cases (a client's docs usually belong to their single open case).

All helpers are insert-only and never raise to their caller's transaction
— they take an already-acquired connection and do NOT commit (the caller
owns the transaction), so timeline rows are atomic with the action that
produced them.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def resolve_case_ids_for_document(conn, document_id: int) -> list[int]:
    """Active case ids a document belongs to (property match first)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT client_id, property_id FROM documents WHERE id = %s",
            (document_id,),
        )
        doc = cur.fetchone()
        if doc is None or doc.get("client_id") is None:
            return []

        cur.execute(
            "SELECT id FROM cases "
            "WHERE is_active = true AND client_id = %s "
            "AND (%s::int IS NULL OR property_id = %s::int) "
            "ORDER BY (property_id = %s::int) DESC NULLS LAST, created_at DESC",
            (doc["client_id"], doc["property_id"], doc["property_id"], doc["property_id"]),
        )
        return [int(r["id"]) for r in cur.fetchall()]


def record_case_events(conn, case_ids: list[int], status: str, note: str | None) -> int:
    """Append one event per case id. Returns rows inserted. No commit."""
    inserted = 0
    with conn.cursor() as cur:
        for case_id in case_ids:
            try:
                cur.execute(
                    "INSERT INTO case_events (case_id, status, note) "
                    "VALUES (%s, %s, %s)",
                    (case_id, status, note),
                )
                inserted += 1
            except Exception:
                # Timeline bookkeeping must never break the triggering
                # action; the outer transaction still commits the action.
                logger.exception("case_events insert failed for case %s", case_id)
                conn.rollback()
    return inserted


def record_document_status_events(conn, document_id: int, to_status: str,
                                  reason: str | None = None) -> int:
    """Auto-event for a document approval-status change."""
    try:
        case_ids = resolve_case_ids_for_document(conn, document_id)
    except Exception:
        logger.exception("case resolution failed for document %s", document_id)
        return 0
    if not case_ids:
        return 0
    note = f"Document #{document_id} {to_status}"
    if reason:
        note += f": {reason}"
    return record_case_events(conn, case_ids, f"document_{to_status}", note)


def record_workflow_stage_event(conn, workflow_id: int, case_id: int | None,
                                stage: str) -> int:
    """Auto-event for a workflow stage advance (skipped without a case)."""
    if case_id is None:
        return 0
    return record_case_events(conn, [int(case_id)], f"workflow_{stage}",
                              f"Workflow #{workflow_id} moved to {stage}")
