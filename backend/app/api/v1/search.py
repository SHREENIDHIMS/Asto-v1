"""Search endpoint â€” full pipeline implementation.

Pipeline (no LLM anywhere in the serving path):
  query_processing.process_query â†’
  search.hybrid_orchestrator.search_knowledge_base â†’
  ranking.rrf.rank_fusion â†’
  ranking.reranker.rerank (optional, cross-encoder) â†’
  response.package_builder.build_response_package â†’
  response.validation.validate_package â†’
  audit.audit_logger.log_query

Every response field traces back verbatim to a source chunk.

``POST /search/``  â€” plain JSON request/response.
``POST /search/stream`` â€” SSE (text/event-stream) version that emits
content as it is produced: ``status`` events as the pipeline advances,
``fact`` events per resolved fact row (fact path), ``sentence`` events per
extractive summary sentence (document path), then one ``result`` event with
the same payload as the sync endpoint.

This is "true" streaming in the sense that content is pushed progressively
as it becomes available (a client can render each fact/sentence as it
arrives), not a single buffered payload. There is still no LLM and no
generated text: every streamed item is a verbatim retrieved value.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Annotated, Callable

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.audit.audit_logger import AuditLogEntry, log_query
from app.auth.rbac import is_admin, resolve_user_departments
from app.config import settings
from app.db.postgres import session
from app.dependencies import require_auth
from app.knowledge_gap.gap_detector import detect_and_log
from app.query_processing.fact_path import run_fact_path
from app.query_processing.pipeline import process_query
from app.ranking.reranker import rerank
from app.ranking.rrf import rank_fusion
from app.ranking.scoring import apply_linear_reorder
from app.llm.citations import maybe_apply_citation_mode
from app.response.confidence_thresholds import route_by_confidence
from app.response.package_builder import build_response_package
from app.response.pinned_answers import find_pinned_answer, pinned_payload
from app.response.validation import validate_package
from app.search.hybrid_orchestrator import search_knowledge_base
from app.search.metadata_filters import _assigned_client_ids
from app.search.suggest import suggest_queries

router = APIRouter()

STAGES = ["processing", "searching", "ranking", "packaging", "done"]


class SearchFilters(BaseModel):
    """Optional faceted filters folded into the document-path SQL WHERE.

    Each filter narrows the candidate set at query time alongside the RBAC
    clause (CLAUDE.md rule #1) — a filter can only ever restrict, never
    widen, the user's scope. ``client_id`` is additionally bounded by the
    staff/assigned-client RBAC clause, so staff can't filter to clients
    they aren't assigned.
    """

    departments: list[str] | None = None
    doc_types: list[str] | None = None
    date_from: str | None = None
    date_to: str | None = None
    client_id: int | None = None


class SearchRequest(BaseModel):
    query: str = Field(..., max_length=settings.max_query_length)
    case_id: int | None = None
    filters: SearchFilters | None = None


class SuggestResponse(BaseModel):
    suggestions: list[str]


class SearchResponse(BaseModel):
    response_id: str
    title: str
    answer: str = ""
    excerpts: list[dict]
    summary: list[dict]
    confidence: float
    routing: str
    related_questions: list[str]
    facts: list[dict] = []
    retrieval_path: str = "document"
    no_answer_reason: str | None = None
    citations: list[dict] = []
    pinned: bool = False
    pinned_from_query: str | None = None


def _serialize(package) -> dict:
    """Convert a ResponsePackage into the public SearchResponse shape."""
    payload = {
        "response_id": package.response_id,
        "title": package.title,
        "answer": package.answer,
        "excerpts": [
            {
                "text": e.text,
                "source": {
                    "title": e.source.title,
                    "section": e.source.section,
                    "chunk_type": e.source.chunk_type,
                },
                "confidence": e.confidence,
                "matched_terms": e.matched_terms,
            }
            for e in package.excerpts
        ],
        "summary": [
            {
                "text": s.text,
                "source": {
                    "title": s.source_title,
                    "section": s.source_section,
                    "chunk_type": s.chunk_type,
                },
                "matched_terms": s.matched_terms,
            }
            for s in package.summary
        ],
        "confidence": package.confidence,
        "routing": package.routing,
        "related_questions": package.related_questions or [],
        "facts": [
            {
                "label": f.label,
                "value": f.value,
                "source": f.source,
                "kind": f.kind,
                "retrieved_at": f.retrieved_at,
            }
            for f in package.facts
        ],
        "retrieval_path": package.retrieval_path,
        "no_answer_reason": package.no_answer_reason,
        "citations": package.citations,
    }
    return payload


def _no_sub_queries_response(
    user_id, query: str, start_ms: float, audience: str | None = None
) -> SearchResponse:
    log_query(AuditLogEntry(
        user_id=user_id,
        query=query,
        sub_queries=[],
        retrieved_ids=[],
        confidence=0.0,
        response_id="",
        outcome="no_sub_queries",
        latency_ms=time.time() * 1000 - start_ms,
        audience=audience,
    ))
    return SearchResponse(
        response_id="",
        title="No Results",
        answer="",
        excerpts=[],
        summary=[],
        confidence=0.0,
        routing="no_answer",
        related_questions=[],
        retrieval_path="document",
        no_answer_reason=None,
    )


def _fact_audit_ids(package) -> list[int]:
    """Collect SQL row ids touched by a fact package for the audit trail."""
    ids: list[int] = []
    for f in package.facts:
        src = f.source
        if "#" in src:
            tail = src.rsplit("#", 1)[-1]
            try:
                ids.append(int(tail))
            except ValueError:
                pass
    return ids


def _log_audit(
    user_id: int | None,
    query: str,
    sub_query_displays: list[str],
    retrieved_ids: list[int],
    confidence: float,
    response_id: str,
    outcome: str,
    latency_ms: float,
    audience: str | None = None,
) -> None:
    log_query(AuditLogEntry(
        user_id=user_id,
        query=query,
        sub_queries=sub_query_displays,
        retrieved_ids=retrieved_ids,
        confidence=confidence,
        response_id=response_id,
        outcome=outcome,
        latency_ms=latency_ms,
        audience=audience,
    ))


def _run_pipeline(
    query: str,
    user: dict,
    case_id: int | None = None,
    filters: SearchFilters | None = None,
    emit: Callable[[str, dict], None] | None = None,
) -> SearchResponse:
    """Execute the full search pipeline and return a SearchResponse.

    ``emit`` (optional) is called with ``(event_type, data)`` at each
    pipeline phase and for each produced fact/summary sentence so the
    streaming endpoint can push content progressively:

    - ``("status", {"stage": ...})`` as the pipeline advances
    - ``("fact", {label, value, source, kind, retrieved_at})`` per fact row
      on the structured-fact path
    - ``("sentence", {text, source})`` per extractive summary sentence on
      the document path
    - ``("done", {})`` when packaging is complete

    The structured-fact path (if the query matches a fact intent and a
    case context exists) short-circuits the document search â€” see
    docs/architecture/dual_path_assistant.md Â§3.
    """
    start_ms = time.time() * 1000

    def status(stage: str) -> None:
        if emit:
            emit("status", {"stage": stage})

    status("processing")
    plan = process_query(query)

    if not plan.sub_queries:
        return _no_sub_queries_response(
            user["id"], query, start_ms, audience=user.get("audience")
        )

    sub_query_texts = [sq.expanded for sq in plan.sub_queries]
    sub_query_displays = [sq.display for sq in plan.sub_queries]

    # Pinned-answer path — exact normalized match on an admin-curated
    # response package (originating from a real audited search). Served
    # verbatim before any retrieval; audience scoping is in the SQL WHERE
    # clause (rule 1). Near-misses fall through to the normal pipeline.
    status("searching")
    with session.acquire() as conn:
        pinned_row = find_pinned_answer(conn, query, user.get("audience"))
    if pinned_row is not None:
        payload = pinned_payload(pinned_row, query)
        latency_ms = time.time() * 1000 - start_ms
        _log_audit(
            user_id=user["id"],
            query=query,
            sub_query_displays=sub_query_displays,
            retrieved_ids=[],
            confidence=round(payload["confidence"], 1),
            response_id=payload["response_id"],
            outcome="pinned",
            latency_ms=round(latency_ms, 1),
            audience=user.get("audience"),
        )
        status("done")
        return SearchResponse(**payload)

    # Structured-fact path â€” deterministic SQL, no vector search. Falls
    # through to the document path when run_fact_path returns None.
    status("searching")
    with session.acquire() as conn:
        fact_package = run_fact_path(
            conn=conn,
            normalized_query=plan.normalized,
            sub_queries=[sq.display for sq in plan.sub_queries],
            user=user,
            case_id=case_id,
            query_text=query,
        )

    if fact_package is not None:
        status("packaging")

        latency_ms = time.time() * 1000 - start_ms
        _log_audit(
            user_id=user["id"],
            query=query,
            sub_query_displays=sub_query_displays,
            retrieved_ids=_fact_audit_ids(fact_package),
            confidence=round(fact_package.confidence, 1),
            response_id=fact_package.response_id,
            outcome=fact_package.routing,
            latency_ms=round(latency_ms, 1),
            audience=user.get("audience"),
        )

        payload = _serialize(fact_package)
        for f in payload["facts"]:
            if emit:
                emit("fact", f)
        status("done")
        return SearchResponse(**payload)

    with session.acquire() as conn:
        result = search_knowledge_base(
            conn=conn,
            sub_queries=sub_query_texts,
            user=user,
            filters=filters,
        )

    chunk_lookup = {c.chunk_id: c.__dict__ for c in result.candidates}

    bm25_ranked = sorted(
        [(c.chunk_id, c.bm25_score) for c in result.candidates],
        key=lambda x: x[1],
        reverse=True,
    )
    vector_ranked = sorted(
        [(c.chunk_id, c.vec_score) for c in result.candidates],
        key=lambda x: x[1],
        reverse=True,
    )

    status("ranking")
    ranked = rank_fusion(
        bm25_ranked=bm25_ranked,
        vector_ranked=vector_ranked,
        chunk_lookup=chunk_lookup,
    )

    # Final order = benchmark-verified weighted linear combination
    # (evaluation/compare_rankings.py). RRF score stays intact for
    # confidence/routing; only the list order changes.
    ranked = apply_linear_reorder(ranked)

    if settings.rerank_enabled and ranked:
        rerank_candidates = [
            {"chunk_id": c.chunk_id, "content": c.content}
            for c in ranked[: settings.bm25_limit]
        ]
        rerank_result = rerank(
            query=query,
            candidates=rerank_candidates,
            top_k=min(10, len(rerank_candidates)),
        )
        rerank_order = {c["chunk_id"]: i for i, c in enumerate(rerank_result)}
        ranked.sort(
            key=lambda c: rerank_order.get(c.chunk_id, len(rerank_order)),
        )

    status("packaging")
    user_depts = resolve_user_departments(user)
    package = build_response_package(
        candidates=ranked,
        query_text=query,
        user_departments=user_depts,
    )

    # Extractively assembled bubble for the document path (verbatim
    # summary sentences only — no synthesis). Mirrors the fact-path bubble.
    package.answer = " ".join(
        s.text for s in package.summary if s.text.strip()
    ).strip()

    package.routing = route_by_confidence(package.confidence)

    # DEC-1 cite-with-LLM hook: a strict no-op while settings.llm_enabled is
    # false (the default) — the package comes back unchanged and no LLM is
    # ever called. A future DEC-1 flip activates synthesis with citations.
    package = maybe_apply_citation_mode(package, query_text=query)

    intent = plan.sub_queries[0].intent if plan.sub_queries else "general"
    if package.routing in ("no_answer", "partial"):
        detect_and_log(
            query=query,
            intent=intent,
            confidence=package.confidence,
        )

    # Re-check the staff client-assignment leg of the SQL scope as a safety
    # net (rule #1 re-check). Clients and admins need no assignment list.
    assigned_client_ids = None
    if user.get("audience") != "client" and not is_admin(user):
        with session.acquire() as conn:
            assigned_client_ids = _assigned_client_ids(conn, int(user["id"]))

    valid, reason = validate_package(package, user, assigned_client_ids=assigned_client_ids)
    if not valid:
        log_query(AuditLogEntry(
            user_id=user["id"],
            query=query,
            sub_queries=[sq.display for sq in plan.sub_queries],
            retrieved_ids=[],
            confidence=0.0,
            response_id=package.response_id,
            outcome=f"validation_failed:{reason}",
            latency_ms=time.time() * 1000 - start_ms,
            audience=user.get("audience"),
        ))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Response validation failed: {reason}",
        )

    latency_ms = time.time() * 1000 - start_ms
    _log_audit(
        user_id=user["id"],
        query=query,
        sub_query_displays=[sq.display for sq in plan.sub_queries],
        retrieved_ids=[c.document_id for c in ranked[:25]],
        confidence=round(package.confidence, 1),
        response_id=package.response_id,
        outcome=package.routing,
        latency_ms=round(latency_ms, 1),
        audience=user.get("audience"),
    )

    if not package.related_questions:
        package.related_questions = (
            [sq.display for sq in plan.sub_queries[:3]] if plan.sub_queries else []
        )

    payload = _serialize(package)

    for s in payload["summary"]:
        if emit:
            emit("sentence", {"text": s["text"], "source": s.get("source"), "matched_terms": s.get("matched_terms", [])})
    status("done")
    return SearchResponse(**payload)


@router.post("/", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    user: Annotated[dict, Depends(require_auth)],
) -> SearchResponse:
    """Search the knowledge base for the user's query (sync, JSON)."""
    return _run_pipeline(request.query, user, case_id=request.case_id, filters=request.filters)


@router.get("/suggest", response_model=SuggestResponse)
async def suggest(
    q: str,
    user: Annotated[dict, Depends(require_auth)],
) -> SuggestResponse:
    """Return prefix-matched suggestions from past successful queries.

    Scoped to the caller (J4): clients see their own queries, staff see
    queries from their department scope, admins see all. Empty prefix
    returns an empty list.
    """
    with session.acquire() as conn:
        suggestions = suggest_queries(conn=conn, prefix=q, user=user)
    # Rule #8: suggestion lookups are queries against production data and are
    # audit-logged like any other search.
    log_query(AuditLogEntry(
        user_id=user.get("id"),
        query=q,
        sub_queries=[],
        retrieved_ids=[],
        confidence=None,
        outcome="suggest",
        audience=user.get("audience"),
    ))
    return SuggestResponse(suggestions=suggestions)


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/stream")
async def search_stream(
    request: SearchRequest,
    user: Annotated[dict, Depends(require_auth)],
) -> StreamingResponse:
    """Search with SSE events pushed progressively as content is produced.

    Events emitted in order:
    - ``status``  — pipeline stage (``processing``, ``searching``,
      ``ranking``, ``packaging``, ``done``)
    - ``fact``    — one event per resolved fact (structured-fact path),
      payload ``{label, value, source, kind, retrieved_at}``
    - ``sentence``— one event per extractive summary sentence (document
      path), payload ``{text, source}``
    - ``result``  — the complete ``SearchResponse`` (identical payload to
      the sync endpoint)
    - ``error``   — on failure (with ``detail``)

    Content is flushed to the client as soon as each item is produced
    (progressive render, not a single buffered payload).
    """
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event_type: str, data: dict) -> None:
        queue.put_nowait((event_type, data))

    async def producer():
        try:
            # Run the synchronous pipeline in a worker thread so the event
            # loop stays free and the generator can drain the queue as each
            # event is produced (progressive flush). ``emit`` is invoked
            # from that thread; Queue.put_nowait is thread-safe.
            result = await asyncio.to_thread(
                _run_pipeline,
                request.query,
                user,
                case_id=request.case_id,
                filters=request.filters,
                emit=emit,
            )
            queue.put_nowait(("result", result))
        except HTTPException as exc:
            queue.put_nowait(("error", {"detail": exc.detail}))
        except Exception as exc:  # pragma: no cover - defensive
            queue.put_nowait(("error", {"detail": f"Search failed: {exc}"}))

    async def gen():
        task = asyncio.ensure_future(producer())
        while True:
            event_type, data = await queue.get()
            if event_type == "result":
                yield _sse_event("result", data.model_dump())
                break
            if event_type == "error":
                yield _sse_event("error", data)
                break
            yield _sse_event(event_type, data)
        task.cancel()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
