"""Document review scheduling (compliance staleness signals).

Admins set ``documents.review_due`` per document. This module answers two
questions:

1. ``stale_source_titles`` — which of the documents cited by a search
   response are past their review date, so the response can carry a
   "source pending review" warning.
2. ``overdue_review_documents`` — the admin worklist of active approved
   documents whose review date has passed.

Read-only helpers; callers own the transaction.
"""

from __future__ import annotations


def stale_source_titles(conn, document_ids: list[int]) -> list[str]:
    """Titles of the given documents with review_due < today (deduped,
    in the order given). Empty/None ids are ignored; no ids → []."""
    ids = sorted({int(d) for d in document_ids if d})
    if not ids:
        return []
    placeholders = ", ".join(["%s"] * len(ids))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, title FROM documents "
            f"WHERE id IN ({placeholders}) "
            "AND review_due IS NOT NULL AND review_due < CURRENT_DATE",
            ids,
        )
        title_by_id = {r["id"]: r["title"] for r in cur.fetchall()}
    # Preserve retrieval order, dedupe titles.
    seen: set[str] = set()
    ordered: list[str] = []
    for doc_id in document_ids:
        title = title_by_id.get(int(doc_id)) if doc_id else None
        if title and title not in seen:
            seen.add(title)
            ordered.append(title)
    return ordered


def overdue_review_documents(conn, limit: int = 100) -> list[dict]:
    """Active approved documents past their review date, most overdue first."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, title, department, doc_type, version, review_due, "
            "(CURRENT_DATE - review_due) AS days_overdue "
            "FROM documents "
            "WHERE is_active = true AND approval_status = 'approved' "
            "AND review_due IS NOT NULL AND review_due < CURRENT_DATE "
            "ORDER BY review_due ASC LIMIT %s",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]
