"""Structured-fact answer orchestrator (multi-turn dual-track pathway).

Decides whether a processed query should take the structured-fact path
(typed SQL on the operational schema) or fall through to the document
path (vector + BM25).

Flow (per docs/architecture/dual_path_assistant.md §3/§4):

1. Multi-question split has already produced ``plan.sub_queries``; each
   sub-question is classified independently via ``route_fact_intent``
   (exact phrase first, then asymmetric-soft matching — see fact_router).
2. No intent match anywhere and no clarification needed → return ``None``
   (document path).
2b. No intent match, but the query reads personally/about the caller's
   case → return a ``no_answer`` package with the deterministic clarifying
   prompt instead of guessing an intent.
3. Intent(s) match but no case context → return ``None`` so the query
   falls through instead of emitting a misleading empty answer. (For a
   client audience we auto-resolve their most recent active case.)
4. Resolve facts for every matched intent via
   ``fact_resolvers.resolve_fact`` (RLS bound in SQL).
5. Merge the facts for all matched intents into ONE ``ResponsePackage``
   with ``retrieval_path="structured_fact"``, confidence = mean per-intent
   completeness, routing via the existing confidence thresholds.

The single-bubble ``answer`` is AN EXPLICITLY SANCTIONED deterministic
assembly (documented in docs/architecture/dual_path_assistant.md §9 /
CLAUDE.md "revisit on demand"). It is NOT an LLM and it never paraphrases
or invents content: it inserts each fact's ``value`` VERBATIM into fixed,
per-intent sentence templates (e.g. "Case {Case number} is currently
{Status}."). Every value still carries its source row (``cases#204``),
shown under the bubble. If a template slot has no fact, the sentence is
omitted — no placeholder text is emitted.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import OrderedDict

import psycopg

from app.query_processing.case_resolver import (
    CaseCandidate,
    _accessible_case_rows,
    resolve_case_from_query,
)
from app.query_processing.fact_router import route_fact_intent
from app.query_processing.fact_resolvers import (
    FactContext,
    FactRecord,
    FactResult,
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


def _fact_map(facts: list[FactRecord]) -> dict[str, str | int | float | None]:
    """First value per label (labels are unique within one resolver result)."""
    out: dict[str, str | int | float | None] = {}
    for f in facts:
        out.setdefault(f.label, f.value)
    return out


def _sentence(parts: list[str]) -> str:
    """Join non-empty template fragments without placeholder text."""
    joined = " ".join(p for p in parts if p)
    return joined.strip().rstrip(".;,") + "."


def _sentences_for_intent(intent: str, result: FactResult) -> list[str]:
    """Deterministic per-intent answer sentences.

    Only slots that have an actual fact are emitted — there are NO
    placeholder sentences, NO paraphrase, and NO invented content. Every
    inserted value is the verbatim stored value (see module docstring).
    """
    if not result.accessible or not result.facts:
        return []
    m = _fact_map(result.facts)

    def get(label: str) -> str:
        v = m.get(label)
        return "" if v is None or v == "" else str(v)

    if intent == "case_status":
        return [
            _sentence([
                "Your case",
                get("Case number"),
                "is currently",
                get("Status") + "." if get("Status") else "",
                f"Latest update: {get('Latest update')}." if get("Latest update") else "",
                f'The latest note reads: "{get("Latest note")}".' if get("Latest note") else "",
            ])
        ]
    if intent == "case_next_step":
        return [
            _sentence([
                "You are waiting on the following",
                get("Workflow"),
                "which is currently",
                get("Workflow status") + ".",
                f'Latest note: {get("Latest update")}.' if get("Latest update") else "",
            ])
        ]
    if intent == "missing_documents":
        pending = [f.value for f in result.facts if f.kind == "document"]
        if not pending:
            return ["There are no missing documents on your case right now."]
        count = get("Pending documents")
        return [
            _sentence([
                "Your case still needs",
                f"{len(pending)} {'document' if len(pending) == 1 else 'documents'}",
                "before it can proceed:",
                "; ".join(str(p) for p in pending) + ".",
            ])
        ]
    if intent == "case_documents":
        docs = [f.value for f in result.facts if f.kind == "document"]
        if not docs:
            return ["No approved documents are attached to your case."]
        return [
            _sentence([
                "These approved documents are on file for your case:",
                "; ".join(str(d) for d in docs) + ".",
            ])
        ]
    if intent == "case_property":
        address = get("Property address")
        ptype = get("Property type")
        if not address:
            return []
        parts = ["The property on this case is", address + "."]
        if ptype:
            parts.append(f"Its property type is {ptype}.")
        return [_sentence(parts)]
    if intent == "case_timeline":
        events = [f.value for f in result.facts if f.kind == "event"]
        if not events:
            return ["There are no recorded events on this case yet."]
        return [
            _sentence([
                "Here is the history of your case:",
                "; ".join(str(e) for e in events) + ".",
            ])
        ]
    if intent == "workflow_step":
        return [
            _sentence([
                "Your file currently sits at workflow",
                get("Workflow"),
                "with status",
                get("Workflow status") + ".",
            ])
        ]
    if intent == "client_financials":
        amount = get("Loan amount")
        return [
            _sentence(["The loan amount on this case is", f"{amount} dollars."])
            if amount else []
        ]
    return []


def _assemble_answer(intents: list[str], results: dict[str, FactResult]) -> str:
    """Combine the per-intent sentences into one readable bubble.

    Sentences appear in the same order the intents were fired in. This is
    deterministic template composition over verbatim facts — no LLM.
    """
    parts: list[str] = []
    for intent in intents:
        result = results.get(intent)
        if result is None:
            continue
        parts.extend(_sentences_for_intent(intent, result))
    return " ".join(parts).strip()


def _merge_related_questions(intents: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for intent in intents:
        for q in RELATED_QUESTIONS_BY_INTENT.get(intent, []):
            if q not in seen:
                seen.add(q)
                merged.append(q)
    return merged


def _resolve_case_id(
    conn: psycopg.Connection,
    user: dict,
    case_id: int | None,
    query_text: str = "",
) -> tuple[int | None, list]:
    """Return ``(case_id, candidates)`` for the conversation.

    Resolution order (all RLS-scoped, see case_resolver.py):
    1. An entity mention in the query text wins over the persistent
       dropdown. A unique match → that case. An ambiguous match that
       includes the selected case → the selected case (the dropdown
       disambiguates). An ambiguous match without the selected case →
       ``candidates`` for the caller to clarify.
    2. No resolvable mention → explicit ``case_id`` (the dropdown).
    3. No mention and no selection → answer anyway when the caller can:
       exactly one accessible active case → auto-resolve to it; several →
       ``candidates`` suggestion chips; none → ``(None, [])``.
    4. Client audience → most recent active case (legacy auto-resolve).
    5. Otherwise → ``(None, [])`` (caller falls through or asks).

    The mention-first order is deliberate: the dropdown is a default
    context, but the user's current text ("what's the loan on 456 oak
    ave?") names the case they mean *now*, and the candidate-case chips
    re-ask with a case number appended — both would be silently overridden
    if an explicit ``case_id`` always won.
    """
    resolution = None
    if query_text.strip():
        resolution = resolve_case_from_query(conn, user, query_text)
    if resolution is not None and resolution.case_id is not None:
        return resolution.case_id, []
    if resolution is not None and resolution.candidates:
        candidate_ids = {c.case_id for c in resolution.candidates}
        if case_id is not None and case_id in candidate_ids:
            return case_id, []
        return None, resolution.candidates
    if case_id is not None:
        return case_id, []
    if user.get("audience") != "client":
        # Answer anyway when the caller can, instead of a dead-end. With a
        # single accessible active case there is nothing to disambiguate;
        # with several, offer them as suggestion chips (same RLS scope —
        # never widens access).
        rows = _accessible_case_rows(conn, user)
        if len(rows) == 1:
            return rows[0]["case_id"], []
        if len(rows) > 1:
            candidates = [
                CaseCandidate(
                    case_id=r["case_id"],
                    case_number=r["case_number"],
                    client_name=r.get("client_name"),
                    address=r.get("address"),
                )
                for r in rows
            ]
            return None, candidates
        return None, []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM cases WHERE client_id = %s AND is_active = true "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (user.get("client_id"),),
        )
        row = cur.fetchone()
    return (row["id"] if row else None), []


def _completeness(intent: str, facts: list[FactRecord]) -> float:
    target = COMPLETENESS_TARGETS.get(intent, 1)
    if target <= 0:
        return 0.0
    return min(1.0, len(facts) / target)


def _build_fact_package(
    intents: list[str],
    results: dict[str, FactResult],
    query_text: str,
) -> ResponsePackage:
    """Merge per-intent facts into ONE answer bubble + fact list.

    Confidence = mean of per-intent completeness (1.0 = all targets met).
    Routing still goes through the shared confidence thresholds so a fully
    answered question stays ``answer`` and a partially answered one gets
    ``partial`` — never a blanket reject.
    """
    if not intents:
        return _no_answer_package("No supported question was found in your message.", query_text)

    all_facts: list[FactRecord] = []
    ordered: list[tuple[str, FactResult]] = []
    for intent in intents:
        result = results.get(intent)
        if result is None or not result.accessible:
            continue
        ordered.append((intent, result))
        all_facts.extend(result.facts)

    answer = _assemble_answer(intents, results)

    completeness_scores = [
        _completeness(intent, results[intent].facts)
        for intent in intents
        if results.get(intent) is not None
    ]
    confidence = round(sum(completeness_scores) / len(completeness_scores) * 100.0, 1) if completeness_scores else 0.0
    routing = route_by_confidence(confidence)

    title = "Summary" if len(intents) > 1 else {
        "case_status": "Case Status",
        "case_next_step": "Next Steps",
        "missing_documents": "Missing Documents",
        "case_documents": "Your Documents",
        "case_property": "Case Property",
        "case_timeline": "Case Timeline",
        "workflow_step": "Workflow Position",
        "client_financials": "Loan Details",
    }.get(intents[0], "Case Details")

    response_id = hashlib.sha256(
        f"fact:{'+'.join(intents)}:{query_text}:{uuid.uuid4()}".encode()
    ).hexdigest()[:16]

    # Deduplicate identical fact rows across resolvers (same label/value/source).
    seen_facts: set[tuple[str, str, str]] = set()
    unique_facts: list[FactRecord] = []
    for f in all_facts:
        key = (str(f.label), str(f.value), f.source)
        if key not in seen_facts:
            seen_facts.add(key)
            unique_facts.append(f)

    package = ResponsePackage(
        response_id=response_id,
        title=title,
        answer=answer,
        confidence=confidence,
        routing=routing,
        related_questions=_merge_related_questions(intents),
    )
    package.facts = unique_facts
    package.retrieval_path = "structured_fact"
    return package


def _no_answer_package(reason: str, query_text: str) -> ResponsePackage:
    package = ResponsePackage(
        response_id=hashlib.sha256(
            f"fact:no:{query_text}:{uuid.uuid4()}".encode()
        ).hexdigest()[:16],
        title="No Answer",
        answer="",
        confidence=0.0,
        routing="no_answer",
        related_questions=[],
    )
    package.retrieval_path = "structured_fact"
    package.no_answer_reason = reason
    return package


# Deterministic clarifying prompt (design decision 2026-08-09). When a query
# reads like a personal case question but no single intent cleared the soft
# routing bar, we ask rather than best-guess. The prompt is a FIXED string —
# no template slots, no generated text — and carries the intent example
# chips so the client can click-to-ask.
CLARIFY_PROMPT = (
    "I'm not sure which detail of your case you're asking about. "
    "Can you rephrase your question? For example: your case status, "
    "what documents are still needed, or your loan details."
)


def _clarify_package(query_text: str) -> ResponsePackage:
    """A no-answer package that asks the user to rephrase instead of guessing.

    ``related_questions`` doubles as the click-to-ask example chips the
    frontend already renders (no new UI plumbing needed).
    """
    package = ResponsePackage(
        response_id=hashlib.sha256(
            f"fact:clarify:{query_text}:{uuid.uuid4()}".encode()
        ).hexdigest()[:16],
        title="Could you rephrase?",
        answer="",
        confidence=0.0,
        routing="no_answer",
        related_questions=[
            "What is the current status of my case?",
            "What documents are still missing?",
            "What is the loan amount on this case?",
        ],
    )
    package.retrieval_path = "structured_fact"
    package.no_answer_reason = CLARIFY_PROMPT
    return package


def _candidate_cases_package(
    query_text: str,
    candidates: list,
) -> ResponsePackage:
    """A no-answer package asking which case was meant.

    The related-question chips re-ask the SAME question with the candidate
    case number appended, so clicking one re-enters mention resolution
    (case-number mention beats property/client) and resolves
    deterministically. Chips are deterministic template strings — every
    value is a stored case number.
    """
    base = query_text.strip().rstrip("?.! ")
    package = ResponsePackage(
        response_id=hashlib.sha256(
            f"fact:candidates:{query_text}:{uuid.uuid4()}".encode()
        ).hexdigest()[:16],
        title="Which case?",
        answer="",
        confidence=0.0,
        routing="no_answer",
        related_questions=[
            f"{base} for case {c.case_number}" for c in candidates[:4]
        ],
    )
    package.retrieval_path = "structured_fact"
    package.no_answer_reason = (
        "I found a few cases matching your question. "
        "Which case did you mean?"
    )
    return package


def run_fact_path(
    conn: psycopg.Connection,
    normalized_query: str,
    sub_queries: list[str] | None = None,
    user: dict | None = None,
    case_id: int | None = None,
    query_text: str = "",
) -> ResponsePackage | None:
    """Run the structured-fact path for a whole message, or return ``None``.

    ``sub_queries`` (optional, from ``plan.sub_queries``) drives per-part
    intent classification so a compound message like "what's my status?
    what's missing?" resolves BOTH intents and merges their facts into one
    bubble. When ``sub_queries`` is ``None`` (legacy single-query callers
    and tests), the whole ``normalized_query`` is classified directly.

    ``None`` means: no supported fact intent at all — the caller should
    run the document path instead. A ``no_answer`` package with the
    clarifying prompt is returned when the query reads personally/about the
    caller's case but no intent cleared the soft routing bar (we ask rather
    than best-guess — design decision 2026-08-09).

    Case context is resolved via ``_resolve_case_id``: explicit ``case_id``
    wins, then an entity mention in the query (case number / property /
    client name — see case_resolver.py) for a unique match or candidate
    chips, then client auto-resolution. Mention resolution is RLS-scoped,
    never widening access.
    """
    if sub_queries is None:
        parts = [normalized_query]
    else:
        parts = [p for p in sub_queries if p and p.strip()]
        if not parts:
            return None

    # Soft-match each sub-question independently, preserving first-match
    # order and dropping duplicates so "status? also status?" stays one.
    intents: list[str] = []
    seen: set[str] = set()
    needs_clarification = False
    for part in parts:
        route = route_fact_intent(part)
        if route.needs_clarification:
            needs_clarification = True
            continue
        if route.intent is not None and route.intent not in seen:
            seen.add(route.intent)
            intents.append(route.intent)

    if not intents:
        if needs_clarification:
            return _clarify_package(query_text)
        return None

    resolved_case_id, case_candidates = _resolve_case_id(
        conn, user, case_id, query_text=query_text
    )
    if case_candidates:
        return _candidate_cases_package(query_text, case_candidates)
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

    results: dict[str, FactResult] = {}
    for intent in intents:
        result = resolve_fact(conn, intent, ctx)
        results[intent] = result
        if not result.accessible:
            # Any inaccessible sub-question poisons the whole bubble rather
            # than silently dropping part of what was asked.
            return _no_answer_package(result.reason or "This case is not accessible.", query_text)

    if not any(r.facts for r in results.values()):
        return _no_answer_package("No facts could be retrieved for that question.", query_text)

    return _build_fact_package(intents, results, query_text)
