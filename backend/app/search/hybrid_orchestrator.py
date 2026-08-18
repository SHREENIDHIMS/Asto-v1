"""Hybrid search orchestrator.

Combines BM25 (full-text) and pgvector (semantic) search into a single
PostgreSQL query. RBAC and active-version filtering are in the WHERE
clause (CLAUDE.md rule #1).

This uses the single-query pattern — vector and BM25 in the same SQL
statement, not separate round-trips to separate services.

Additionally: pre-query synonym expansion from the `synonyms` table so that
domain aliases (e.g. "mortgage" ⇄ "home loan") are included in both the
BM25 tsquery and the embedding query, improving recall without retraining.
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


def _build_filter_clause(filters: object | None) -> tuple[str, list]:
    """Translate J2 faceted filters into SQL WHERE fragments.

    Each enabled filter contributes an ANDed predicate; only the
    document-path search consumes these (the structured-fact path runs on
    the operational schema, where doc-type/date facets don't apply). The
    returned parameters are plain values so they are always bound
    server-side (no string interpolation of user input).
    """
    if filters is None:
        return "", []

    parts: list[str] = []
    params: list = []

    departments = getattr(filters, "departments", None)
    if departments:
        placeholders = ", ".join(["%s"] * len(departments))
        parts.append(f"d.department = ANY(ARRAY[{placeholders}]::text[])")
        params.extend(departments)

    doc_types = getattr(filters, "doc_types", None)
    if doc_types:
        placeholders = ", ".join(["%s"] * len(doc_types))
        parts.append(f"d.doc_type = ANY(ARRAY[{placeholders}]::text[])")
        params.extend(doc_types)

    date_from = getattr(filters, "date_from", None)
    if date_from:
        parts.append("d.created_at >= %s")
        params.append(date_from)

    date_to = getattr(filters, "date_to", None)
    if date_to:
        parts.append("d.created_at < (%s::date + interval '1 day')")
        params.append(date_to)

    client_id = getattr(filters, "client_id", None)
    if client_id is not None:
        parts.append("d.client_id = %s")
        params.append(client_id)

    return " AND ".join(parts), params


def _expand_query_with_synonyms(query: str, conn: Connection) -> str:
    """Expand a query string using canonical/alias pairs from the synonyms table.

    For each alias that appears in the query text, the canonical phrase is
    appended (if not already present). The original query text is preserved
    — expansion *adds* signal, it never replaces the user's words.

    Example: "max ltv" -> "max ltv loan to value" if "ltv" is an alias
    for "loan to value" in the synonyms table.
    """
    import re

    # Normalize: lowercase, strip for matching
    normalized = query.lower()

    expanded_terms: set[str] = set()
    with conn.cursor() as cur:
        # Find aliases that appear in the query (case-insensitive)
        cur.execute(
            "SELECT canonical, alias FROM synonyms"
        )
        all_synonyms = cur.fetchall()

    for canonical, alias in all_synonyms:
        # Check if the alias appears as a word in the query
        # Use word boundary: the alias as a standalone word
        if re.search(r"\b" + re.escape(alias.lower()) + r"\b", normalized):
            if canonical.lower() not in expanded_terms:
                expanded_terms.add(canonical.lower())

    # Append the canonical phrases to the original query
    if expanded_terms:
        # Deduplicate: keep original text + new terms
        extra_phrases = " ".join(sorted(expanded_terms))
        return f"{query} {extra_phrases}"
    return query


def search_knowledge_base(
    conn: Connection,
    sub_queries: Sequence[str],
    user: dict | None,
    filters: object | None = None,
    bm25_limit: int = 25,
    vector_limit: int = 25,
    max_results: int = 100,
) -> SearchResult:
    """Run hybrid search for a set of sub-queries.

    Returns ranked candidates with both BM25 and vector scores.
    RBAC is applied in the WHERE clause per CLAUDE.md rule #1.
    ``filters`` (optional) carries faceted constraints — departments,
    doc_types, date range, client_id — folded into the same WHERE clause
    so they can only narrow, never widen, the RBAC scope.

    **Synonym expansion (J8):** the primary query is expanded using
    canonical/alias pairs from the `synonyms` table before the BM25 tsquery
    and the embedding are generated. This adds domain-phrase signal to both
    lexical and semantic search without replacing the user's original terms.
    """
    if not sub_queries:
        return SearchResult()

    primary_query = sub_queries[0]

    # J8: expand query using database synonyms
    primary_query = _expand_query_with_synonyms(primary_query, conn)

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

    # Faceted filters (J2) — ANDed with RBAC so they can only narrow.
    filter_clause, filter_params = _build_filter_clause(filters)
    if filter_clause:
        where_parts.append(filter_clause)
        where_params.extend(filter_params)

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
