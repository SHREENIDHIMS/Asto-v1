"""Hybrid search orchestrator.

Combines BM25 (full-text) and pgvector (semantic) search into a single
PostgreSQL query. RBAC and active-version filtering are in the WHERE
clause (CLAUDE.md rule #1).

This uses the single-query pattern — vector and BM25 in the same SQL
statement, not separate round-trips to separate services.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

from psycopg import Connection

from app.search.bm25_search import build_tsquery
from app.search.metadata_filters import get_search_filter
from app.search.pgvector_search import embed_query

logger = logging.getLogger(__name__)


@dataclass
class SearchCandidate:
    chunk_id: int
    document_id: int
    title: str
    doc_type: str
    department: str
    section: str | None
    chunk_type: str
    content: str
    is_approved: bool
    document_version: int
    bm25_score: float
    vec_score: float
    client_id: int | None = None


@dataclass
class SearchResult:
    candidates: list[SearchCandidate] = field(default_factory=list)
    query_embedding: list[float] = field(default_factory=list)
    sub_query: str = ""


def search_knowledge_base(
    conn: Connection,
    sub_queries: Sequence[str],
    user: dict | None,
    bm25_limit: int = 25,
    vector_limit: int = 25,
    max_results: int = 100,
) -> SearchResult:
    """Run hybrid search for a set of sub-queries.

    Returns ranked candidates with both BM25 and vector scores.
    RBAC is applied in the WHERE clause per CLAUDE.md rule #1.
    """
    if not sub_queries:
        return SearchResult()

    primary_query = sub_queries[0]
    query_vector = embed_query(primary_query)

    combined_text = " ".join(sub_queries)
    tsquery = build_tsquery(combined_text)

    # RBAC filter — applied in WHERE clause
    rbac_clause, rbac_params = get_search_filter(user, conn=conn)

    where_parts: list[str] = [
        "c.fts @@ to_tsquery('english', %s)",
        "c.is_active = true",
        "c.is_approved = true",
        "d.is_active = true",
        "d.is_approved = true",
        "c.embedding IS NOT NULL",
    ]
    where_params: list = [tsquery]

    if rbac_clause:
        where_parts.append(rbac_clause)
        where_params.extend(rbac_params)

    where_clause = " AND ".join(where_parts)

    query = f"""
    SELECT c.id, c.document_id, d.title, d.doc_type, c.section,
           c.chunk_type, c.content, c.department, d.client_id,
           c.is_approved AS chunk_is_approved,
           d.version AS document_version,
           ts_rank_cd(c.fts, to_tsquery('english', %s)) AS bm25_score,
           1 - (c.embedding <=> %s) AS vec_score
    FROM document_chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE {where_clause}
    ORDER BY (
        ts_rank_cd(c.fts, to_tsquery('english', %s)) * 0.3 +
        (1 - (c.embedding <=> %s)) * 0.7
    ) DESC
    LIMIT %s
    """

    params: list = [
        tsquery,
        query_vector,
        tsquery,
    ]
    params.extend(where_params[1:])
    params.extend([tsquery, query_vector, max_results])

    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    candidates = []
    for row in rows:
        candidates.append(SearchCandidate(
            chunk_id=row["id"],
            document_id=row["document_id"],
            title=row["title"],
            doc_type=row["doc_type"],
            department=row["department"],
            client_id=row["client_id"],
            section=row["section"],
            chunk_type=row["chunk_type"],
            content=row["content"],
            is_approved=bool(row["chunk_is_approved"]),
            document_version=int(row["document_version"] or 1),
            bm25_score=float(row["bm25_score"] or 0.0),
            vec_score=float(row["vec_score"] or 0.0),
        ))

    logger.info(
        "Hybrid search: %d sub-queries, %d candidates returned",
        len(sub_queries), len(candidates),
    )

    return SearchResult(
        candidates=candidates,
        query_embedding=query_vector,
        sub_query=combined_text,
    )
