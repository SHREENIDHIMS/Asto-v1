"""Document approval workflow API (Phase B3).

Admin-only endpoints implementing the Pending/Approved/Rejected state
machine with a full reviewer audit trail (approval_log):

- GET  /admin/documents/pending  — list documents awaiting review
- POST /admin/documents/{id}/approve — set approved (writes approval_log)
- POST /admin/documents/{id}/reject  — set rejected (writes approval_log)
- GET  /admin/documents/{id}/history — approval audit trail for a document

State changes are transactional: the document AND all its chunks move
together, so a partially-approved document can never leak into search.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.permissions import require_role
from app.dependencies import require_auth
from app.db.postgres.session import acquire

router = APIRouter()

VALID_STATUSES = {"pending", "approved", "rejected"}


def _apply_document_status(document_id: int, to_status: str, reviewer_id: int, reason: str | None) -> None:
    """Transition a document + its chunks to a new approval status."""
    if to_status not in VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status '{to_status}'",
        )

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT approval_status FROM documents WHERE id = %s",
                (document_id,),
            )
            row = cur.fetchone()

        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document {document_id} not found",
            )
        from_status = row["approval_status"]

        is_approved = to_status == "approved"
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE documents
                   SET approval_status = %s, is_approved = %s,
                       approved_by = %s, approved_at = now()
                 WHERE id = %s
                """,
                (to_status, is_approved, reviewer_id, document_id),
            )
            cur.execute(
                """
                UPDATE document_chunks
                   SET approval_status = %s, is_approved = %s,
                       approved_by = %s, approved_at = now()
                 WHERE document_id = %s
                """,
                (to_status, is_approved, reviewer_id, document_id),
            )
            cur.execute(
                """
                INSERT INTO approval_log (document_id, reviewed_by, from_status, to_status, reason)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (document_id, reviewer_id, from_status, to_status, reason),
            )
        conn.commit()


@router.get("/documents/pending")
async def list_pending_documents(
    user: dict = Depends(require_auth),
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """List documents awaiting approval. Requires admin role."""
    require_role(user, "admin")

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, doc_type, department, client_id,
                       approval_status, source_path, version, created_at
                FROM documents
                WHERE approval_status = 'pending'
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            documents = [dict(row) for row in cur.fetchall()]

    return {"documents": documents}


@router.post("/documents/{document_id}/approve")
async def approve_document(
    document_id: int,
    user: dict = Depends(require_auth),
) -> dict:
    """Approve a pending document and its chunks. Requires admin role."""
    require_role(user, "admin")
    _apply_document_status(document_id=document_id, to_status="approved", reviewer_id=user["id"], reason=None)
    return {"message": f"Document {document_id} approved"}


@router.post("/documents/{document_id}/reject")
async def reject_document(
    document_id: int,
    user: dict = Depends(require_auth),
) -> dict:
    """Reject a pending document and its chunks. Requires admin role."""
    require_role(user, "admin")
    _apply_document_status(document_id=document_id, to_status="rejected", reviewer_id=user["id"], reason=None)
    return {"message": f"Document {document_id} rejected"}


@router.get("/documents/{document_id}/history")
async def approval_history(
    document_id: int,
    user: dict = Depends(require_auth),
) -> dict:
    """Return the approval audit trail for a document. Requires admin role."""
    require_role(user, "admin")

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT l.id, l.document_id, l.from_status, l.to_status,
                       l.reason, l.created_at,
                       u.email AS reviewed_by_email
                FROM approval_log l
                LEFT JOIN users u ON u.id = l.reviewed_by
                WHERE l.document_id = %s
                ORDER BY l.created_at DESC
                """,
                (document_id,),
            )
            history = [dict(row) for row in cur.fetchall()]

    return {"document_id": document_id, "history": history}
