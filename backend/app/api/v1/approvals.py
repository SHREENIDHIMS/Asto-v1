"""Document approval workflow API (Phase B3).

Admin-only endpoints implementing the Pending/Approved/Rejected state
machine with a full reviewer audit trail (approval_log):

- GET  /admin/documents/pending  â€” list documents awaiting review
- POST /admin/documents/{id}/approve â€” set approved (writes approval_log)
- POST /admin/documents/{id}/reject  â€” set rejected (writes approval_log)
- GET  /admin/documents/{id}/history â€” approval audit trail for a document

State changes are transactional: the document AND all its chunks move
together, so a partially-approved document can never leak into search.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.auth.permissions import require_role
from app.dependencies import require_auth
from app.db.postgres import session
from app.api.v1.notifications import notify_user

router = APIRouter()

VALID_STATUSES = {"pending", "approved", "rejected"}


def _apply_document_status(document_id: int, to_status: str, reviewer_id: int, reason: str | None) -> None:
    """Transition a document + its chunks to a new approval status.

    Notifies the document uploader (if any) of the outcome — approval
    carries the reviewer's note, rejection carries the required reason.
    """
    if to_status not in VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status '{to_status}'",
        )

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT approval_status, title, uploaded_by FROM documents WHERE id = %s",
                (document_id,),
            )
            row = cur.fetchone()

        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document {document_id} not found",
            )
        from_status = row["approval_status"]
        doc_title = row["title"]
        uploaded_by = row["uploaded_by"]

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

        # Notify the uploader of the outcome (Phase G3). Approved →
        # include the note; rejected → include the required reason.
        if uploaded_by is not None:
            if to_status == "approved":
                notify_user(
                    conn,
                    uploaded_by,
                    "document_approved",
                    "Document approved",
                    f"'{doc_title}' was approved" + (f": {reason}" if reason else "."),
                    link="/staff?tab=clients",
                )
            elif to_status == "rejected":
                notify_user(
                    conn,
                    uploaded_by,
                    "document_rejected",
                    "Document rejected",
                    f"'{doc_title}' was rejected" + (f": {reason}" if reason else "."),
                    link="/staff?tab=clients",
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

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.id, d.title, d.doc_type, d.department, d.client_id,
                       d.approval_status, d.source_path, d.version, d.created_at,
                       d.uploaded_by, u.email AS uploaded_by_email
                FROM documents d
                LEFT JOIN users u ON u.id = d.uploaded_by
                WHERE d.approval_status = 'pending'
                ORDER BY d.created_at DESC
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


class RejectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("A reason is required when rejecting a document")
        return v


@router.post("/documents/{document_id}/reject")
async def reject_document(
    document_id: int,
    request: RejectRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """Reject a pending document and its chunks. Requires admin role.

    A reason is required — it is persisted to ``approval_log.reason``
    and shown to the uploader in their notification.
    """
    require_role(user, "admin")
    reason = request.reason.strip()
    _apply_document_status(
        document_id=document_id,
        to_status="rejected",
        reviewer_id=user["id"],
        reason=reason,
    )
    return {"message": f"Document {document_id} rejected", "reason": reason}


class MetadataUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    doc_type: str | None = Field(default=None, min_length=1, max_length=100)
    department: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("title", "doc_type", "department")
    @classmethod
    def _strip_not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("Value cannot be empty")
        return v


@router.patch("/documents/{document_id}")
async def update_document_metadata(
    document_id: int,
    request: MetadataUpdateRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """Edit a pending document's metadata (title / doc_type / department).

    Metadata-only per Session 12 decision #1 — the file itself is never
    replaced here. Only pending documents can be edited (approved/rejected
    documents are immutable to keep the audit trail honest).
    """
    require_role(user, "admin")

    updates = {}
    if request.title is not None:
        updates["title"] = request.title
    if request.doc_type is not None:
        updates["doc_type"] = request.doc_type
    if request.department is not None:
        updates["department"] = request.department

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nothing to update",
        )

    with session.acquire() as conn:
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
            if row["approval_status"] != "pending":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Only pending documents can be edited",
                )

            set_clauses = ", ".join(f"{col} = %s" for col in updates)
            cur.execute(
                f"UPDATE documents SET {set_clauses} WHERE id = %s",
                (*updates.values(), document_id),
            )
        conn.commit()

    return {"message": f"Document {document_id} updated", "updated": list(updates.keys())}


@router.get("/documents/{document_id}/history")
async def approval_history(
    document_id: int,
    user: dict = Depends(require_auth),
) -> dict:
    """Return the approval audit trail for a document. Requires admin role."""
    require_role(user, "admin")

    with session.acquire() as conn:
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
