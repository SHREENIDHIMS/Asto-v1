"""Document management API endpoints.

Per CLAUDE.md rule 5: the upload endpoint lives in upload.py.
This file only contains the list endpoint for admin review.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from app.auth.permissions import require_role
from app.dependencies import require_auth
from app.db.postgres import session
from app.documents.file_serve import resolve_stored_file

router = APIRouter()


@router.get("/")
async def list_documents(
    user: dict = Depends(require_auth),
    offset: int = 0,
    limit: int = 100,
    tag: str | None = None,
) -> dict:
    """List documents (requires admin role).

    ``?tag=name`` narrows the result to documents carrying that tag (I8).
    """
    require_role(user, "admin")

    params: list = [limit, offset]
    tag_clause = ""
    if tag is not None:
        tag = tag.strip().lower()
        params.insert(0, tag)
        tag_clause = "AND %s = ANY(d.tags) "

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT d.id, d.title, d.source_path, d.doc_type, d.department, "
                "d.client_id, d.approval_status, d.approved_by, d.approved_at, "
                "d.is_active, d.is_approved, d.version, d.created_at, d.tags, "
                "d.uploaded_by, u.email AS uploaded_by_email "
                "FROM documents d "
                "LEFT JOIN users u ON u.id = d.uploaded_by "
                f"WHERE 1=1 {tag_clause}"
                "ORDER BY d.created_at DESC LIMIT %s OFFSET %s",
                params,
            )
            documents = [dict(row) for row in cur.fetchall()]

    return {"documents": documents}


@router.get("/{document_id}/file")
async def get_document_file(
    document_id: int,
    version: int | None = None,
    user: dict = Depends(require_auth),
) -> FileResponse:
    """Serve a stored document file (requires admin role).

    With ``?version=N``, serves the file for the given version within the
    document's family (title/department/client/property) instead of the
    current row.
    """
    require_role(user, "admin")

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT title, department, client_id, property_id, source_path "
                "FROM documents WHERE id = %s",
                (document_id,),
            )
            anchor = cur.fetchone()

            if anchor is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Document not found",
                )

            if version is None:
                row = anchor
            else:
                cur.execute(
                    "SELECT source_path, title FROM documents "
                    "WHERE title = %s AND department = %s "
                    "AND client_id IS NOT DISTINCT FROM %s "
                    "AND property_id IS NOT DISTINCT FROM %s "
                    "AND version = %s",
                    (
                        anchor["title"],
                        anchor["department"],
                        anchor["client_id"],
                        anchor["property_id"],
                        version,
                    ),
                )
                row = cur.fetchone()
                if row is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Version {version} not found",
                    )

    file_path = resolve_stored_file(row["source_path"])
    return FileResponse(
        file_path,
        filename=row["title"] or file_path.name,
    )
