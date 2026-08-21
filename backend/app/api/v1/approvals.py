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


def _apply_document_status(
    document_id: int,
    to_status: str,
    reviewer_id: int,
    reason: str | None,
    conn,
) -> None:
    """Transition a document + its chunks to a new approval status.

    Notifies the document uploader (if any) of the outcome — approval
    carries the reviewer's note, rejection carries the required reason.

    ``conn`` must be an already-acquired connection (via
    ``session.acquire()``); the caller owns the transaction and is
    responsible for committing (or rolling back on error).
    """
    if to_status not in VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status '{to_status}'",
        )

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
                       d.uploaded_by, d.pii_flagged, d.tags,
                       u.email AS uploaded_by_email
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
    request: ApproveRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """Approve a pending document and its chunks. Requires admin role.

    A document flagged as containing PII (``pii_flagged``) must be approved
    with an explicit ``publish_anyway=true`` confirmation â the admin review
    queue should surface that checkbox only for flagged docs.
    """
    require_role(user, "admin")
    with session.acquire() as conn:
        _check_pii_publish(document_id, request.publish_anyway, conn)
        _apply_document_status(
            document_id=document_id,
            to_status="approved",
            reviewer_id=user["id"],
            reason=None,
            conn=conn,
        )
        conn.commit()
    return {"message": f"Document {document_id} approved"}


class ApproveRequest(BaseModel):
    publish_anyway: bool = False


def _check_pii_publish(document_id: int, publish_anyway: bool, conn) -> None:
    """Raise 422 unless a PII-flagged document is explicitly published."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pii_flagged FROM documents WHERE id = %s",
            (document_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found",
        )
    if row["pii_flagged"] and not publish_anyway:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Document contains flagged PII; set publish_anyway=true to approve",
        )


def _check_pii_publish_bulk(document_ids: list[int], publish_anyway: bool, conn) -> None:
    """Raise 422 unless every PII-flagged doc in a bulk approve is confirmed."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM documents WHERE id = ANY(%s) AND pii_flagged = true",
            (document_ids,),
        )
        flagged = [row["id"] for row in cur.fetchall()]
    if flagged and not publish_anyway:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{len(flagged)} document(s) contain flagged PII; "
                "set publish_anyway=true to approve"
            ),
        )


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
    with session.acquire() as conn:
        _apply_document_status(
            document_id=document_id,
            to_status="rejected",
            reviewer_id=user["id"],
            reason=reason,
            conn=conn,
        )
        conn.commit()
    return {"message": f"Document {document_id} rejected", "reason": reason}


class BulkApproveRequest(BaseModel):
    document_ids: list[int] = Field(min_length=1, max_length=200)
    publish_anyway: bool = False

    @field_validator("document_ids")
    @classmethod
    def _ids_unique_and_positive(cls, v: list[int]) -> list[int]:
        if len(set(v)) != len(v):
            raise ValueError("document_ids must be unique")
        if any(i <= 0 for i in v):
            raise ValueError("document_ids must be positive integers")
        return v


class BulkRejectRequest(BaseModel):
    document_ids: list[int] = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("document_ids")
    @classmethod
    def _ids_unique_and_positive(cls, v: list[int]) -> list[int]:
        if len(set(v)) != len(v):
            raise ValueError("document_ids must be unique")
        if any(i <= 0 for i in v):
            raise ValueError("document_ids must be positive integers")
        return v

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("A reason is required when rejecting a document")
        return v


@router.post("/documents/bulk-approve")
async def bulk_approve_documents(
    request: BulkApproveRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """Approve multiple documents in one transaction.

    Each document moves through the same state machine as the single
    approve endpoint, one ``approval_log`` row per document, and each
    uploader is notified. An unknown/invalid id aborts the whole batch
    (404) with no partial commits. Requires admin role.
    """
    require_role(user, "admin")
    _bulk_apply_status(
        document_ids=request.document_ids,
        to_status="approved",
        reviewer_id=user["id"],
        reason=None,
        publish_anyway=request.publish_anyway,
    )
    return {"message": f"{len(request.document_ids)} documents approved"}


@router.post("/documents/bulk-reject")
async def bulk_reject_documents(
    request: BulkRejectRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """Reject multiple documents in one transaction.

    A shared reason is persisted to each document's ``approval_log`` row
    and shown to each uploader. An unknown/invalid id aborts the whole
    batch (404) with no partial commits. Requires admin role.
    """
    require_role(user, "admin")
    _bulk_apply_status(
        document_ids=request.document_ids,
        to_status="rejected",
        reviewer_id=user["id"],
        reason=request.reason.strip(),
    )
    return {"message": f"{len(request.document_ids)} documents rejected"}


def _bulk_apply_status(
    document_ids: list[int],
    to_status: str,
    reviewer_id: int,
    reason: str | None,
    publish_anyway: bool = False,
) -> None:
    """Apply a status transition to many documents inside one transaction.

    Every id is resolved up front so a missing id aborts the batch before
    any row is written (all-or-nothing). Reuses ``_apply_document_status``
    per document (sharing one connection) for the per-doc audit log +
    uploader notification, then commits once at the end.
    """
    if to_status not in VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status '{to_status}'",
        )

    with session.acquire() as conn:
        if to_status == "approved":
            _check_pii_publish_bulk(document_ids, publish_anyway, conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM documents WHERE id = ANY(%s)",
                (document_ids,),
            )
            found = {row["id"] for row in cur.fetchall()}
        missing = [d for d in document_ids if d not in found]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document(s) not found: {missing}",
            )

        for document_id in document_ids:
            _apply_document_status(
                document_id=document_id,
                to_status=to_status,
                reviewer_id=reviewer_id,
                reason=reason,
                conn=conn,
            )
        conn.commit()


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


# ---------------------------------------------------------------------------
# Review scheduling (documents.review_due)
# ---------------------------------------------------------------------------


class ReviewDueRequest(BaseModel):
    """ISO date (YYYY-MM-DD) to schedule a review; null to clear."""

    review_due: str | None = None


@router.put("/documents/{document_id}/review-due")
async def set_review_due(
    document_id: int,
    request: ReviewDueRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """Schedule (or clear) the content review date for an active document.

    Overdue documents surface in GET /admin/documents/review-overdue and
    search responses citing them carry a stale-source warning.
    """
    require_role(user, "admin")

    parsed = None
    if request.review_due is not None:
        from datetime import date

        try:
            parsed = date.fromisoformat(request.review_due)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="review_due must be an ISO date (YYYY-MM-DD)",
            )

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE documents SET review_due = %s "
                "WHERE id = %s AND is_active = true",
                (parsed, document_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Document not found",
                )
        conn.commit()

    return {
        "document_id": document_id,
        "review_due": parsed.isoformat() if parsed else None,
    }


@router.get("/documents/review-overdue")
async def list_review_overdue(
    user: dict = Depends(require_auth),
    limit: int = 100,
) -> dict:
    """Active approved documents past their review date (admin worklist)."""
    require_role(user, "admin")
    limit = max(1, min(limit, 500))

    from app.documents.review import overdue_review_documents

    with session.acquire() as conn:
        documents = overdue_review_documents(conn, limit=limit)
    return {"documents": documents}


@router.get("/documents/{document_id}/versions")
async def document_versions(
    document_id: int,
    user: dict = Depends(require_auth),
) -> dict:
    """Return every version of a document family.

    A "family" is all documents sharing the same title/department/client/
    property — the identity that ``index_document`` uses to bump versions.
    Requires admin role.
    """
    require_role(user, "admin")

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT title, department, client_id, property_id
                FROM documents WHERE id = %s
                """,
                (document_id,),
            )
            anchor = cur.fetchone()
            if anchor is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Document not found",
                )
            cur.execute(
                """
                SELECT d.id, d.title, d.source_path, d.doc_type, d.department,
                       d.client_id, d.property_id, d.approval_status,
                       d.is_active, d.is_approved, d.version, d.created_at, d.tags,
                       d.uploaded_by, u.email AS uploaded_by_email
                FROM documents d
                LEFT JOIN users u ON u.id = d.uploaded_by
                WHERE d.title = %s AND d.department = %s
                  AND d.client_id IS NOT DISTINCT FROM %s
                  AND d.property_id IS NOT DISTINCT FROM %s
                ORDER BY d.version ASC
                """,
                (
                    anchor["title"],
                    anchor["department"],
                    anchor["client_id"],
                    anchor["property_id"],
                ),
            )
            versions = [dict(row) for row in cur.fetchall()]

    return {"document_id": document_id, "versions": versions}


class TagsUpdateRequest(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        normalized: list[str] = []
        for raw in v:
            tag = raw.strip().lower()
            if not tag:
                raise ValueError("Tags cannot be empty")
            if len(tag) > 50:
                raise ValueError("Tags must be 50 characters or fewer")
            if tag in seen:
                continue
            seen.add(tag)
            normalized.append(tag)
        return normalized


@router.put("/documents/{document_id}/tags")
async def update_document_tags(
    document_id: int,
    request: TagsUpdateRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """Replace a document's tags (admin-only).

    Tags are a lightweight browse/filter taxonomy (I8) stored on the
    ``documents`` row as ``text[]``. The full list is replaced on each call;
    empty clears all tags. Tag values are lower-cased, trimmed, and
    deduplicated server-side.
    """
    require_role(user, "admin")

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM documents WHERE id = %s", (document_id,))
            row = cur.fetchone()
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Document {document_id} not found",
                )
            cur.execute(
                "UPDATE documents SET tags = %s WHERE id = %s",
                (request.tags, document_id),
            )
        conn.commit()

    return {"document_id": document_id, "tags": request.tags}


@router.get("/tags")
async def list_tags(
    user: dict = Depends(require_auth),
) -> dict:
    """Return every tag with the number of documents carrying it (admin-only).

    Used to render tag-filter chips in the admin Documents list. Only tags on
    active documents are counted.
    """
    require_role(user, "admin")

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tag, COUNT(*) AS count
                FROM documents d, unnest(d.tags) AS tag
                WHERE d.is_active = true
                GROUP BY tag
                ORDER BY count DESC, tag ASC
                """,
            )
            tags = [{"tag": row["tag"], "count": row["count"]} for row in cur.fetchall()]

    return {"tags": tags}
