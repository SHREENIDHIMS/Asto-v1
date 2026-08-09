"""Structured-fact path orchestrator (Phase 1 dual-path assistant).

Decides whether a processed query should take the structured-fact path
(typed SQL on the operational schema) or fall through to the document
path (vector + BM25).

Flow (per docs/architecture/dual_path_assistant.md §3/§4):

1. ``classify_fact_intent`` over the normalized query.
2. No intent match → return ``None`` (document path).
3. Intent match but no case context → return ``None`` so the query falls
   through instead of emitting a misleading empty fact package. (A
   conversation binds to a ``case_id`` at creation — §8. For a client
   audience we auto-resolve their most recent active case.)
4. Resolve facts via ``fact_resolvers.resolve_fact`` (RLS bound in SQL).
5. Build a ``ResponsePackage`` with ``retrieval_path="structured_fact"``,
   confidence = completeness-based, routing via the existing confidence
   thresholds.

This module never generates text: every ``answer``/``facts`` value is a
verbatim stored value with an explicit source (``cases#204``).
"""

from __future__ import annotations

import hashlib
import uuid

import psycopg

from app.query_processing.fact_router import classify_fact_intent
from app.query_processing.fact_resolvers import (
    FactContext,
    FactRecord,
    resolve_fact,
)
from app.response.confidence_thresholds import route_by_confidence
from app.response.package_builder import ResponsePackage

# Completeness targets per intent: how many fact rows we consider a "full"
# answer for that intent. Used to derive a 0..1 completeness → confidence.
COMPLETENESS_TARGETS: dict[str, int] = {
    "case_status": 4,
    "case_next_step": 3,
    "missing_documents": 2,
    "case_documents": 2,
    "case_property": 2,
    "case_timeline": 3,
    "workflow_step": 2,
    "client_financials": 1,
}

# Role-appropriate, context-aware follow-up suggestions per intent (§6).
RELATED_QUESTIONS_BY_INTENT: dict[str, list[str]] = {
    "case_status": [
        "What happens next?",
        "What documents are still missing?",
        "What is the loan amount on this case?",
    ],
    "case_next_step": [
        "What is the current status of my case?",
        "What documents are still missing?",
    ],
    "missing_documents": [
        "Where can I upload the missing documents?",
        "What is the current status of my case?",
    ],
    "case_documents": [
        "What documents are still missing?",
        "What is the current status of my case?",
    ],
    "case_property": [
        "What is the current status of my case?",
        "What is the loan amount on this case?",
    ],
    "case_timeline": [
        "What happens next?",
        "What is the current status of my case?",
    ],
    "workflow_step": [
        "What happens next?",
        "What is the current status of my case?",
    ],
    "client_financials": [
        "What is the current status of my case?",
        "What happens next?",
    ],
}


def _resolve_case_id(conn: psycopg.Connection, user: dict, case_id: int | None) -> int | None:
    """Return the conversation's case id, auto-resolving for client audience.

    Client audience without an explicit case_id → most recent active case
    (their case list). Staff/admin without a case_id → None (the caller
    falls through to the document path).
    """
    if case_id is not None:
        return case_id
    if user.get("audience") != "client":
        return None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM cases WHERE client_id = %s AND is_active = true "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (user.get("client_id"),),
        )
        row = cur.fetchone()
    return row["id"] if row else None


def _completeness(intent: str, facts: list[FactRecord]) -> float:
    target = COMPLETENESS_TARGETS.get(intent, 1)
    if target <= 0:
        return 0.0
    return min(1.0, len(facts) / target)


def _build_fact_package(
    intent: str,
    facts: list[FactRecord],
    query_text: str,
) -> ResponsePackage:
    confidence = round(_completeness(intent, facts) * 100.0, 1)
    routing = route_by_confidence(confidence)

    title = {
        "case_status": "Case Status",
        "case_next_step": "Next Steps",
        "missing_documents": "Missing Documents",
        "case_documents": "Your Documents",
        "case_property": "Case Property",
        "case_timeline": "Case Timeline",
        "workflow_step": "Workflow Position",
        "client_financials": "Loan Details",
    }.get(intent, "Case Details")

    response_id = hashlib.sha256(
        f"fact:{intent}:{query_text}:{uuid.uuid4()}".encode()
    ).hexdigest()[:16]

    package = ResponsePackage(
        response_id=response_id,
        title=title,
        confidence=confidence,
        routing=routing,
        related_questions=RELATED_QUESTIONS_BY_INTENT.get(intent, []),
    )
    package.facts = facts
    package.retrieval_path = "structured_fact"
    return package


def _no_answer_package(reason: str, query_text: str) -> ResponsePackage:
    package = ResponsePackage(
        response_id=hashlib.sha256(
            f"fact:no:{query_text}:{uuid.uuid4()}".encode()
        ).hexdigest()[:16],
        title="No Answer",
        confidence=0.0,
        routing="no_answer",
        related_questions=[],
    )
    package.retrieval_path = "structured_fact"
    package.no_answer_reason = reason
    return package


def run_fact_path(
    conn: psycopg.Connection,
    normalized_query: str,
    user: dict,
    case_id: int | None,
    query_text: str,
) -> ResponsePackage | None:
    """Run the structured-fact path, or return ``None`` to fall through.

    ``None`` means: no supported fact intent, or no case context to scope
    the facts — the caller should run the document path instead.
    """
    intent = classify_fact_intent(normalized_query)
    if intent is None:
        return None

    resolved_case_id = _resolve_case_id(conn, user, case_id)
    if resolved_case_id is None:
        return _no_answer_package(
            "I need a case selected to answer that.",
            query_text,
        )

    ctx = FactContext(
        user=user,
        case_id=resolved_case_id,
        client_id=user.get("client_id"),
    )
    result = resolve_fact(conn, intent, ctx)
    if not result.accessible:
        return _no_answer_package(result.reason or "This case is not accessible.", query_text)

    return _build_fact_package(intent, result.facts, query_text)
