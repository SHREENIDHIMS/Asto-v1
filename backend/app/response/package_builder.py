"""Response package builder.

Assembles retrieved chunks into the ResponsePackage shape. Excerpts trace
back verbatim or near-verbatim to a source chunk. A best-effort extractive
summary (Sumy TextRank) selects the most salient sentences verbatim from
the top excerpts — no abstractive synthesis (CLAUDE.md doctrine).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field

from app.config import settings
from app.ranking.rrf import RRF_K, RankedCandidate
from app.response.summarizer import SummarySentence, summarize_excerpts
from app.search.matched_terms import matched_terms


def _normalize_rrf_score(rrf_score: float) -> float:
    """Normalize an RRF score to a 0-100 confidence scale.

    The maximum possible RRF score is 2/(K+1) when a candidate ranks
    first in both the BM25 and vector lists. We normalize against
    that theoretical maximum and cap at 100.
    """
    max_rrf = 2.0 / (RRF_K + 1)
    if max_rrf <= 0:
        return 0.0
    return min((rrf_score / max_rrf) * 100.0, 100.0)


@dataclass
class Source:
    chunk_id: int
    document_id: int
    title: str
    section: str | None
    chunk_type: str
    is_approved: bool
    document_version: int
    department: str | None = None
    client_id: int | None = None
    page_number: int | None = None


@dataclass
class Excerpt:
    text: str
    source: Source
    confidence: float
    bm25_score: float
    vec_score: float
    matched_terms: list[str] = field(default_factory=list)


@dataclass
class ResponsePackage:
    response_id: str
    title: str
    answer: str = ""                          # fact-path assembled bubble (verbatim facts, templates)
    excerpts: list[Excerpt] = field(default_factory=list)
    summary: list[SummarySentence] = field(default_factory=list)
    related_questions: list[str] = field(default_factory=list)
    confidence: float = 0.0
    routing: str = "answer"
    max_excerpt_chars: int = 600
    facts: list = field(default_factory=list)          # list[FactRecord]
    retrieval_path: str = "document"                   # "document" | "structured_fact"
    no_answer_reason: str | None = None


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 3] + "..."


def build_response_package(
    candidates: list[RankedCandidate],
    query_text: str,
    user_departments: list[str] | None = None,
) -> ResponsePackage:
    """Build a ResponsePackage from ranked candidates.

    - Takes top-N candidates (max_evicence_docs from config)
    - Truncates excerpts to max_excerpt_chars
    - Computes confidence from top candidate's RRF score (0-100)
    - Extracts related questions from query entities
    """
    max_docs = settings.max_evidence_docs
    top = candidates[:max_docs]

    excerpts: list[Excerpt] = []
    for c in top:
        confidence = round(_normalize_rrf_score(c.rrf_score), 1)
        excerpts.append(Excerpt(
            text=_truncate(c.content, settings.max_excerpt_chars),
            source=Source(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                title=c.title,
                section=c.section,
                chunk_type=c.chunk_type,
                is_approved=c.is_approved,
                document_version=c.document_version,
                department=c.department,
                client_id=c.client_id,
            ),
            confidence=round(confidence, 1),
            bm25_score=round(c.bm25_score, 4),
            vec_score=round(c.vec_score, 4),
            matched_terms=matched_terms(query_text, c.content),
        ))

    # Response title from the most relevant document
    title = excerpts[0].source.title if excerpts else "No Results Found"

    # Confidence from the top candidate
    top_confidence = excerpts[0].confidence if excerpts else 0.0

    # Best-effort extractive summary of the top excerpts (never raises)
    summary = summarize_excerpts(excerpts, query_text=query_text)

    # Generate response_id for audit tracing
    response_id = hashlib.sha256(
        f"{query_text}:{top_confidence}:{uuid.uuid4()}".encode()
    ).hexdigest()[:16]

    return ResponsePackage(
        response_id=response_id,
        title=title,
        excerpts=excerpts,
        summary=summary,
        confidence=top_confidence,
        max_excerpt_chars=settings.max_excerpt_chars,
    )
