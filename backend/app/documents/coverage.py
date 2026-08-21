"""Content coverage report — where the knowledge base is thin.

Aggregates approved, searchable documents per (department, doc_type) with
their chunk counts and the last time anything was added, so admins can
see which areas of the KB are empty or going stale and prioritize
ingestion. Pure SQL aggregation — no heuristics, no generation.

Read-only; consumed by ``GET /admin/content-coverage``.
"""

from __future__ import annotations

# Doc types every mortgage operation should have content for. Used only to
# annotate gaps in the report (``expected`` flag), never to gate anything.
EXPECTED_DOC_TYPES = frozenset({
    "sop",
    "policy",
    "checklist",
    "faq",
    "rate_sheet",
    "form",
})


def coverage_by_department(conn) -> list[dict]:
    """Per (department, doc_type): approved doc count + chunk count +
    latest ingestion date, ordered by chunk volume ascending (thinnest
    first)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.department,
                   d.doc_type,
                   COUNT(DISTINCT d.id) AS documents,
                   COALESCE(SUM(chunk_counts.chunks), 0) AS chunks,
                   MAX(d.created_at)::date AS last_added
            FROM documents d
            LEFT JOIN (
                SELECT document_id, COUNT(*) AS chunks
                FROM document_chunks
                WHERE is_active = true
                GROUP BY document_id
            ) chunk_counts ON chunk_counts.document_id = d.id
            WHERE d.is_active = true AND d.approval_status = 'approved'
            GROUP BY d.department, d.doc_type
            ORDER BY chunks ASC, d.department ASC, d.doc_type ASC
            """
        )
        rows = [dict(r) for r in cur.fetchall()]

    for row in rows:
        row["documents"] = int(row["documents"] or 0)
        row["chunks"] = int(row["chunks"] or 0)
        row["expected"] = str(row["doc_type"]).lower() in EXPECTED_DOC_TYPES
    return rows


def empty_cells(conn) -> list[dict]:
    """(department, doc_type) pairs that exist somewhere in the KB but have
    zero approved documents in this department — the clearest coverage
    gaps."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT department, doc_type FROM (
                SELECT DISTINCT department, doc_type FROM documents WHERE is_active = true
                UNION
                SELECT DISTINCT department, doc_type FROM sops WHERE is_active = true
            ) all_cells
            WHERE NOT EXISTS (
                SELECT 1 FROM documents d
                WHERE d.is_active = true
                  AND d.approval_status = 'approved'
                  AND d.department = all_cells.department
                  AND d.doc_type = all_cells.doc_type
            )
            ORDER BY department, doc_type
            """
        )
        return [dict(r) for r in cur.fetchall()]


def build_coverage_report(conn) -> dict:
    """Full report payload for the admin endpoint."""
    return {
        "coverage": coverage_by_department(conn),
        "empty_cells": empty_cells(conn),
    }
