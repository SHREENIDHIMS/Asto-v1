"""Client-scoped self-service endpoints (external audience, Phase C).

A client can only ever see their OWN data:
- their own profile (/client/me)
- their own properties (/client/properties)
- their own cases/mortgages (/client/cases)
- their own approved documents (/client/documents)
- upload their own documents (/client/documents/upload, pendingâ†’approval)

Scoping is enforced by ``client_id`` from the JWT identity resolution
(dependencies.get_current_user) â€” never taken from a request body.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.db.postgres import session
from app.dependencies import require_auth
from app.db.postgres.models import (
    case_event_row_to_dict,
    client_row_to_dict,
    case_row_to_dict,
    conversation_row_to_dict,
    message_row_to_dict,
)
from app.api.v1.messaging import (
    _assert_conversation_access_client,
    _list_conversations_client,
    _list_messages,
    _touch_conversation,
)
from app.documents.file_serve import resolve_stored_file
from app.documents.validation import validate_upload

router = APIRouter()


def _require_client(user: dict) -> None:
    """Reject staff tokens on client-only endpoints."""
    if user.get("audience") != "client":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is for client accounts only",
        )


def _assert_owns_property(user: dict, property_id: int) -> None:
    """404 unless the authenticated client owns the property."""
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM properties "
                "WHERE id = %s AND client_id = %s AND is_active = true",
                (property_id, user["client_id"]),
            )
            owned = cur.fetchone()
    if owned is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Property not found",
        )


@router.get("/me")
async def client_me(user: dict = Depends(require_auth)) -> dict:
    """Return the authenticated client's profile."""
    _require_client(user)
    with session.acquire() as conn:
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
    with session.acquire() as conn:
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
    """Return the client's own cases/mortgages with property + latest status.

    Each case carries the property address (LEFT JOIN, safe for cases
    without a property) and the most recent ``case_events`` entry so the
    UI can show a current status snapshot on the list card.
    """
    _require_client(user)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT c.id, c.case_number, c.client_id, c.property_id, "
                "c.loan_amount, c.status, c.is_active, c.created_at, "
                "p.address, p.city, p.state, p.property_type "
                "FROM cases c "
                "LEFT JOIN properties p ON p.id = c.property_id "
                "WHERE c.client_id = %s AND c.is_active = true "
                "ORDER BY c.id",
                (user["client_id"],),
            )
            cases = [dict(row) for row in cur.fetchall()]

            if cases:
                cur.execute(
                    "SELECT DISTINCT ON (case_id) case_id, status, note, created_at "
                    "FROM case_events WHERE case_id = ANY(%s) "
                    "ORDER BY case_id, created_at DESC, id DESC",
                    ([c["id"] for c in cases],),
                )
                latest_by_case = {row["case_id"]: dict(row) for row in cur.fetchall()}
            else:
                latest_by_case = {}

    payload = []
    for c in cases:
        latest = latest_by_case.get(c["id"])
        payload.append(
            {
                **case_row_to_dict(c),
                "property_address": ", ".join(
                    filter(None, [c.get("address"), c.get("city"), c.get("state")])
                ) or None,
                "property_type": c.get("property_type"),
                "latest_event": (
                    {
                        "status": latest["status"],
                        "note": latest.get("note"),
                        "created_at": latest.get("created_at"),
                    }
                    if latest
                    else None
                ),
            }
        )

    return {"cases": payload}


@router.get("/cases/{case_id}")
async def client_case_detail(
    case_id: int,
    user: dict = Depends(require_auth),
) -> dict:
    """Return one of the client's own cases with its full status timeline."""
    _require_client(user)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT c.id, c.case_number, c.client_id, c.property_id, "
                "c.loan_amount, c.status, c.is_active, c.created_at, "
                "p.address, p.city, p.state, p.property_type "
                "FROM cases c "
                "LEFT JOIN properties p ON p.id = c.property_id "
                "WHERE c.id = %s AND c.client_id = %s AND c.is_active = true",
                (case_id, user["client_id"]),
            )
            row = cur.fetchone()

            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Case not found",
                )

            cur.execute(
                "SELECT id, case_id, status, note, created_at "
                "FROM case_events WHERE case_id = %s "
                "ORDER BY created_at ASC, id ASC",
                (case_id,),
            )
            events = [dict(r) for r in cur.fetchall()]

    return {
        "case": {
            **case_row_to_dict(dict(row)),
            "property_address": ", ".join(
                filter(None, [row.get("address"), row.get("city"), row.get("state")])
            ) or None,
            "property_type": row.get("property_type"),
        },
        "events": [case_event_row_to_dict(dict(e)) for e in events],
    }


@router.get("/documents")
async def client_documents(user: dict = Depends(require_auth)) -> dict:
    """Return the client's own approved documents (never pending/rejected)."""
    _require_client(user)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, title, source_path, doc_type, department, "
                "version, property_id, created_at "
                "FROM documents "
                "WHERE client_id = %s AND is_active = true AND is_approved = true "
                "ORDER BY created_at DESC",
                (user["client_id"],),
            )
            documents = [dict(row) for row in cur.fetchall()]

    return {"documents": documents}


@router.get("/properties/{property_id}/documents")
async def client_property_documents(
    property_id: int,
    user: dict = Depends(require_auth),
) -> dict:
    """Return a client's own approved documents for a specific property."""
    _require_client(user)
    _assert_owns_property(user, property_id)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, title, source_path, doc_type, department, "
                "version, property_id, created_at "
                "FROM documents "
                "WHERE client_id = %s AND property_id = %s "
                "AND is_active = true AND is_approved = true "
                "ORDER BY created_at DESC",
                (user["client_id"], property_id),
            )
            documents = [dict(row) for row in cur.fetchall()]

    return {"documents": documents}


@router.post("/documents/upload")
async def client_upload_document(
    file: UploadFile = File(...),
    property_id: int | None = None,
    user: dict = Depends(require_auth),
) -> dict:
    """Accept a client's document upload.

    Per CLAUDE.md rule 5: validates and writes to ``storage/pending/``
    only â€” ingestion runs separately. A ``<uuid>.meta.json`` sidecar
    carries the ``client_id``/``property_id`` so the batch ingestion can
    scope the indexed document. The document enters the approval queue as
    pending and is searchable only after an admin approves it.
    """
    _require_client(user)

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided",
        )

    if property_id is not None:
        _assert_owns_property(user, property_id)

    file_size = 0
    content = b""
    while chunk := await file.read(8192):
        file_size += len(chunk)
        content += chunk

    result = validate_upload(file.filename, file_size)
    if not result.valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.error,
        )

    pending_dir = Path(settings.storage_pending_dir)
    pending_dir.mkdir(parents=True, exist_ok=True)

    token = uuid.uuid4().hex
    unique_name = f"{token}_{file.filename}"
    dest = pending_dir / unique_name
    dest.write_bytes(content)

    sidecar = pending_dir / f"{token}.meta.json"
    sidecar.write_text(
        json.dumps({"client_id": user["client_id"], "property_id": property_id}),
        encoding="utf-8",
    )

    return {
        "message": "File uploaded successfully and queued for indexing",
        "filename": file.filename,
        "stored_as": str(dest),
        "size_bytes": file_size,
        "property_id": property_id,
    }


@router.get("/documents/{document_id}/file")
async def client_document_file(
    document_id: int,
    user: dict = Depends(require_auth),
) -> FileResponse:
    """Serve a client's own approved document file (never pending/rejected).

    Scoping is enforced by ``client_id`` from the JWT â€” the document
    must belong to the authenticated client AND be approved.
    """
    _require_client(user)
    with session.acquire() as conn:
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


class MessageRequest(BaseModel):
    body: str = Field(min_length=1, max_length=2000)

    @field_validator("body")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Message cannot be empty")
        return v


class ConversationRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    case_id: int | None = Field(default=None)

    @field_validator("subject")
    @classmethod
    def _subject_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Subject cannot be empty")
        return v


def _assert_owns_case(user: dict, case_id: int) -> None:
    """404 unless the authenticated client owns the case."""
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM cases "
                "WHERE id = %s AND client_id = %s AND is_active = true",
                (case_id, user["client_id"]),
            )
            owned = cur.fetchone()
    if owned is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found",
        )


@router.get("/conversations")
async def client_conversations(user: dict = Depends(require_auth)) -> dict:
    """List the client's own conversations (SQL-scoped by client_id)."""
    _require_client(user)
    with session.acquire() as conn:
        conversations = _list_conversations_client(conn, user["client_id"])
    return {
        "conversations": [
            conversation_row_to_dict(c) for c in conversations
        ]
    }


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
async def client_create_conversation(
    payload: ConversationRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """Open a new conversation with the bank's team."""
    _require_client(user)
    if payload.case_id is not None:
        _assert_owns_case(user, payload.case_id)

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO conversations (case_id, client_id, subject) "
                "VALUES (%s, %s, %s) RETURNING id, case_id, client_id, "
                "subject, created_at, updated_at",
                (payload.case_id, user["client_id"], payload.subject.strip()),
            )
            row = dict(cur.fetchone())
    return {"conversation": conversation_row_to_dict(row)}


@router.get("/conversations/{conversation_id}/messages")
async def client_conversation_messages(
    conversation_id: int,
    user: dict = Depends(require_auth),
) -> dict:
    """Return all messages in one of the client's own conversations."""
    _require_client(user)
    with session.acquire() as conn:
        _assert_conversation_access_client(conn, user["client_id"], conversation_id)
        messages = _list_messages(conn, conversation_id)
    return {"messages": [message_row_to_dict(m) for m in messages]}


@router.post(
    "/conversations/{conversation_id}/messages",
    status_code=status.HTTP_201_CREATED,
)
async def client_send_message(
    conversation_id: int,
    payload: MessageRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """Send a message to the bank's team within an owned conversation."""
    _require_client(user)
    with session.acquire() as conn:
        _assert_conversation_access_client(conn, user["client_id"], conversation_id)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO messages (conversation_id, sender_type, "
                "sender_client_id, body) VALUES (%s, 'client', %s, %s) "
                "RETURNING id, conversation_id, sender_type, sender_user_id, "
                "sender_client_id, body, created_at",
                (conversation_id, user["client_id"], payload.body.strip()),
            )
            row = dict(cur.fetchone())
        _touch_conversation(conn, conversation_id)
    return {"message": message_row_to_dict(row)}
