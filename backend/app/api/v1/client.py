"""Client-scoped self-service endpoints (external audience, Phase C).

A client can only ever see their OWN data:
- their own profile (/client/me)
- their own properties (/client/properties)
- their own cases/mortgages (/client/cases)
- their own approved documents (/client/documents)

Scoping is enforced by ``client_id`` from the JWT identity resolution
(dependencies.get_current_user) — never taken from a request body.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from app.db.postgres.session import acquire
from app.dependencies import require_auth
from app.db.postgres.models import client_row_to_dict, case_row_to_dict
from app.documents.file_serve import resolve_stored_file

router = APIRouter()


def _require_client(user: dict) -> None:
    """Reject staff tokens on client-only endpoints."""
    if user.get("audience") != "client":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is for client accounts only",
        )


@router.get("/me")
async def client_me(user: dict = Depends(require_auth)) -> dict:
    """Return the authenticated client's profile."""
    _require_client(user)
    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, full_name, is_active, created_at "
                "FROM clients WHERE id = %s",
                (user["client_id"],),
            )
            row = cur.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found",
        )
    return {"client": client_row_to_dict(dict(row))}


@router.get("/properties")
async def client_properties(user: dict = Depends(require_auth)) -> dict:
    """Return the client's own properties."""
    _require_client(user)
    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, client_id, address, city, state, postal_code, "
                "property_type, is_active, created_at "
                "FROM properties WHERE client_id = %s AND is_active = true "
                "ORDER BY id",
                (user["client_id"],),
            )
            properties = [dict(row) for row in cur.fetchall()]

    return {"properties": properties}


@router.get("/cases")
async def client_cases(user: dict = Depends(require_auth)) -> dict:
    """Return the client's own cases/mortgages."""
    _require_client(user)
    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, case_number, client_id, property_id, loan_amount, "
                "status, is_active, created_at "
                "FROM cases WHERE client_id = %s AND is_active = true "
                "ORDER BY id",
                (user["client_id"],),
            )
            cases = [dict(row) for row in cur.fetchall()]

    return {"cases": [case_row_to_dict(dict(r)) for r in cases]}


@router.get("/documents")
async def client_documents(user: dict = Depends(require_auth)) -> dict:
    """Return the client's own approved documents (never pending/rejected)."""
    _require_client(user)
    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, title, source_path, doc_type, department, version, "
                "created_at "
                "FROM documents "
                "WHERE client_id = %s AND is_active = true AND is_approved = true "
                "ORDER BY created_at DESC",
                (user["client_id"],),
            )
            documents = [dict(row) for row in cur.fetchall()]

    return {"documents": documents}


@router.get("/documents/{document_id}/file")
async def client_document_file(
    document_id: int,
    user: dict = Depends(require_auth),
) -> FileResponse:
    """Serve a client's own approved document file (never pending/rejected).

    Scoping is enforced by ``client_id`` from the JWT — the document
    must belong to the authenticated client AND be approved.
    """
    _require_client(user)
    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_path, title FROM documents "
                "WHERE id = %s AND client_id = %s "
                "AND is_active = true AND is_approved = true",
                (document_id, user["client_id"]),
            )
            row = cur.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or not accessible",
        )

    file_path = resolve_stored_file(row["source_path"])
    return FileResponse(
        file_path,
        filename=row["title"] or file_path.name,
    )
