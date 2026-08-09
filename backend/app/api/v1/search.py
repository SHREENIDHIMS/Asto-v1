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
``status`` events as the pipeline advances, then one ``result`` event
with the same payload as the sync endpoint. This is "streaming-lite":
there is no token generation in this system (answers are composed from
retrieved excerpts), so the stream is progress, not characters.
"""

from __future__ import annotations

import json
import time
from typing import Annotated, Callable

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.audit.audit_logger import AuditLogEntry, log_query
from app.auth.rbac import resolve_user_departments
from app.config import settings
from app.db.postgres import session
from app.dependencies import require_auth
from app.knowledge_gap.gap_detector import detect_and_log
from app.query_processing.fact_path import run_fact_path
from app.query_processing.pipeline import process_query
from app.ranking.reranker import rerank
from app.ranking.rrf import rank_fusion
from app.ranking.scoring import apply_linear_reorder
from app.response.confidence_thresholds import route_by_confidence
from app.response.package_builder import build_response_package
from app.response.validation import validate_package
from app.search.hybrid_orchestrator import search_knowledge_base

router = APIRouter()

STAGES = ["processing", "searching", "ranking", "packaging", "done"]


class SearchRequest(BaseModel):
    query: str
    case_id: int | None = None


class SearchResponse(BaseModel):
    response_id: str
    title: str
    excerpts: list[dict]
    summary: list[dict]
    confidence: float
    routing: str
    related_questions: list[str]
    facts: list[dict] = []
    retrieval_path: str = "document"
    no_answer_reason: str | None = None


def _serialize(package) -> dict:
    """Convert a ResponsePackage into the public SearchResponse shape."""
    payload = {
        "response_id": package.response_id,
        "title": package.title,
        "excerpts": [
            {
                "text": e.text,
                "source": {
                    "title": e.source.title,
                    "section": e.source.section,
                    "chunk_type": e.source.chunk_type,
                },
                "confidence": e.confidence,
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
    }
    return payload


def _no_sub_queries_response(user_id, query: str, start_ms: float) -> SearchResponse:
    log_query(AuditLogEntry(
        user_id=user_id,
        query=query,
        sub_queries=[],
        retrieved_ids=[],
        confidence=0.0,
        response_id="",
        outcome="no_sub_queries",
        latency_ms=time.time() * 1000 - start_ms,
    ))
    return SearchResponse(
        response_id="",
        title="No Results",
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
    ))


def _run_pipeline(
    query: str,
    user: dict,
    case_id: int | None = None,
    emit: Callable[[str], None] | None = None,
) -> SearchResponse:
    """Execute the full search pipeline and return a SearchResponse.

    ``emit`` (optional) is called with a stage name at each pipeline
    phase so the streaming endpoint can report progress.

    The structured-fact path (if the query matches a fact intent and a
    case context exists) short-circuits the document search â€” see
    docs/architecture/dual_path_assistant.md Â§3.
    """
    start_ms = time.time() * 1000

    if emit:
        emit("processing")
    plan = process_query(query)

    if not plan.sub_queries:
        return _no_sub_queries_response(user["id"], query, start_ms)

    sub_query_texts = [sq.expanded for sq in plan.sub_queries]
    sub_query_displays = [sq.display for sq in plan.sub_queries]

    # Structured-fact path â€” deterministic SQL, no vector search. Falls
    # through to the document path when run_fact_path returns None.
    if emit:
        emit("searching")
    with session.acquire() as conn:
        fact_package = run_fact_path(
            conn=conn,
            normalized_query=plan.normalized,
            user=user,
            case_id=case_id,
            query_text=query,
        )

    if fact_package is not None:
        if emit:
            emit("packaging")

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
        )

        if emit:
            emit("done")
        return SearchResponse(**_serialize(fact_package))

    with session.acquire() as conn:
        result = search_knowledge_base(
            conn=conn,
            sub_queries=sub_query_texts,
            user=user,
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

    if emit:
        emit("ranking")
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

    if emit:
        emit("packaging")
    user_depts = resolve_user_departments(user)
    package = build_response_package(
        candidates=ranked,
        query_text=query,
        user_departments=user_depts,
    )

    package.routing = route_by_confidence(package.confidence)

    intent = plan.sub_queries[0].intent if plan.sub_queries else "general"
    if package.routing in ("no_answer", "partial"):
        detect_and_log(
            query=query,
            intent=intent,
            confidence=package.confidence,
        )

    valid, reason = validate_package(package, user)
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
        retrieved_ids=[c.chunk_id for c in ranked[:25]],
        confidence=round(package.confidence, 1),
        response_id=package.response_id,
        outcome=package.routing,
        latency_ms=round(latency_ms, 1),
    )

    if not package.related_questions:
        package.related_questions = (
            [sq.display for sq in plan.sub_queries[:3]] if plan.sub_queries else []
        )

    payload = _serialize(package)

    if emit:
        emit("done")
    return SearchResponse(**payload)


@router.post("/", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    user: Annotated[dict, Depends(require_auth)],
) -> SearchResponse:
    """Search the knowledge base for the user's query (sync, JSON)."""
    return _run_pipeline(request.query, user, case_id=request.case_id)


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/stream")
async def search_stream(
    request: SearchRequest,
    user: Annotated[dict, Depends(require_auth)],
) -> StreamingResponse:
    """Search with SSE progress events, then a final ``result`` event.

    Events: ``status`` (stage), ``result`` (full package), ``error``.
    """
    stage_events: list[str] = []

    def emit(stage: str) -> None:
        stage_events.append(_sse_event("status", {"stage": stage}))

    async def gen():
        try:
            result = _run_pipeline(request.query, user, case_id=request.case_id, emit=emit)
            for event in stage_events:
                yield event
            yield _sse_event("result", result.model_dump())
        except HTTPException as exc:
            yield _sse_event("error", {"detail": exc.detail})
        except Exception as exc:  # pragma: no cover - defensive
            yield _sse_event("error", {"detail": f"Search failed: {exc}"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
