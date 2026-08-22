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
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, Response
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
from app.documents.validation import (
    read_upload,
    validate_content_magic,
    validate_upload,
)
from app.documents.watermark import watermark_bytes

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
                "SELECT id, email, full_name, is_active, created_at, notification_prefs "
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


@router.get("/me/export")
async def client_me_export(user: dict = Depends(require_auth)) -> JSONResponse:
    """GDPR-style export of the authenticated client's personal data (M5).

    Returns their profile, properties, cases, documents (with content),
    conversations and their own messages, feedback, and query audit
    history as a downloadable JSON document. Access is audit-logged.
    """
    _require_client(user)
    from app.audit.audit_logger import AuditLogEntry, log_query
    from app.clients.export import build_client_export, json_safe

    payload = json_safe(build_client_export(int(user["client_id"])))

    log_query(
        AuditLogEntry(
            user_id=int(user["client_id"]),
            query="client data export",
            outcome="self-serve GDPR export",
        )
    )
    return JSONResponse(
        payload,
        headers={
            "Content-Disposition": 'attachment; filename="my-data.json"',
            "Content-Type": "application/json",
        },
    )


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
async def client_documents(
    user: dict = Depends(require_auth),
    tag: str | None = None,
) -> dict:
    """Return the client's own approved documents (never pending/rejected).

    ``?tag=name`` narrows to documents carrying that tag (I8).
    """
    _require_client(user)
    tag_clause = ""
    params: list = [user["client_id"]]
    if tag is not None:
        tag = tag.strip().lower()
        params.append(tag)
        tag_clause = "AND %s = ANY(tags) "
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, title, source_path, doc_type, department, "
                "version, property_id, created_at, tags "
                "FROM documents "
                "WHERE client_id = %s AND is_active = true AND is_approved = true "
                f"{tag_clause}"
                "ORDER BY created_at DESC",
                params,
            )
            documents = [dict(row) for row in cur.fetchall()]

    return {"documents": documents}


@router.get("/documents/rejected")
async def client_rejected_documents(user: dict = Depends(require_auth)) -> dict:
    """Return the client's rejected documents with the latest rejection reason.

    Rejected docs are hidden from the approved list (and from search) but
    must stay visible to the uploader so they can see why and upload a
    corrected version (I3). The latest rejection reason is embedded per doc.
    """
    _require_client(user)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.id, d.title, d.source_path, d.doc_type, d.department,
                       d.version, d.property_id, d.created_at,
                       r.reason AS rejection_reason,
                       r.created_at AS rejected_at
                FROM documents d
                LEFT JOIN LATERAL (
                    SELECT al.reason, al.created_at
                    FROM approval_log al
                    WHERE al.document_id = d.id AND al.to_status = 'rejected'
                    ORDER BY al.id DESC
                    LIMIT 1
                ) r ON true
                WHERE d.client_id = %s
                  AND d.is_active = true
                  AND d.approval_status = 'rejected'
                ORDER BY d.created_at DESC
                """,
                (user["client_id"],),
            )
            documents = [dict(row) for row in cur.fetchall()]

    return {"documents": documents}


@router.get("/documents/{document_id}/rejections")
async def client_document_rejections(
    document_id: int,
    user: dict = Depends(require_auth),
) -> dict:
    """Return the full rejection history for one of the client's own documents.

    Scoping is enforced in the SQL WHERE clause (CLAUDE.md rule 1): the
    document must belong to the authenticated client.
    """
    _require_client(user)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM documents WHERE id = %s AND client_id = %s",
                (document_id, user["client_id"]),
            )
            if cur.fetchone() is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Document not found",
                )
            cur.execute(
                """
                SELECT al.id, al.reason, al.created_at, u.email AS reviewed_by_email
                FROM approval_log al
                LEFT JOIN users u ON u.id = al.reviewed_by
                WHERE al.document_id = %s AND al.to_status = 'rejected'
                ORDER BY al.id DESC
                """,
                (document_id,),
            )
            rejections = [dict(row) for row in cur.fetchall()]

    return {"document_id": document_id, "rejections": rejections}


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
    doc_type: str = Form(default="policy"),
    title: str = Form(...),
    property_id: int | None = None,
    user: dict = Depends(require_auth),
) -> dict:
    """Accept a client's document upload.

    Per CLAUDE.md rule 5: validates and writes to ``storage/pending/``
    only â€” ingestion runs separately. A ``<uuid>.meta.json`` sidecar
    carries the ``client_id``/``property_id``/``doc_type``/``title`` so the
    batch ingestion can scope the indexed document. The document enters the
    approval queue as pending and is searchable only after an admin approves it.

    ``doc_type`` and ``title`` are required; ``property_id`` is optional and
    must reference a property the client owns.
    """
    _require_client(user)

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided",
        )

    if property_id is not None:
        _assert_owns_property(user, property_id)

    # Validate required metadata fields
    if not doc_type.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="doc_type is required and must not be empty",
        )
    if not title.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="title is required and must not be empty",
        )

    file_size, content = await read_upload(file)

    result = validate_upload(file.filename, file_size)
    if not result.valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.error,
        )

    content_error = validate_content_magic(result.filename, content)
    if content_error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=content_error,
        )

    pending_dir = Path(settings.storage_pending_dir)
    pending_dir.mkdir(parents=True, exist_ok=True)

    token = uuid.uuid4().hex
    unique_name = f"{token}_{result.filename}"
    dest = pending_dir / unique_name
    dest.write_bytes(content)

    sidecar = pending_dir / f"{token}.meta.json"
    sidecar.write_text(
        json.dumps(
            {
                "client_id": user["client_id"],
                "property_id": property_id,
                "doc_type": doc_type.strip(),
                "title": title.strip(),
            }
        ),
        encoding="utf-8",
    )

    return {
        "message": "File uploaded successfully and queued for indexing",
        "filename": result.filename,
        "stored_as": str(dest),
        "size_bytes": file_size,
        "doc_type": doc_type.strip(),
        "title": title.strip(),
        "property_id": property_id,
    }


@router.get("/documents/{document_id}/file")
async def client_document_file(
    document_id: int,
    user: dict = Depends(require_auth),
) -> FileResponse:
    """Serve a client's own approved document file (never pending/rejected).

    Scoping is enforced by ``client_id`` from the JWT â€” the document
    must belong to the authenticated client AND be approved. The served
    copy is stamped with a "Viewed by {client} on {date}" watermark (I5);
    staff/admin file endpoints are untouched.
    """
    _require_client(user)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_path, title, version FROM documents "
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

    viewer_name = user.get("full_name")
    if not viewer_name:
        with session.acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT full_name FROM clients WHERE id = %s",
                    (user["client_id"],),
                )
                client_row = cur.fetchone()
        viewer_name = client_row["full_name"] if client_row else "the client"

    from app.documents.watermark_cache import (
        load_cached,
        should_watermark,
        store_cached,
    )

    file_path = resolve_stored_file(row["source_path"])
    raw = file_path.read_bytes()
    version = row.get("version")

    # Hardened request path (audit #13): reuse today's cached watermark for
    # this (document, version, viewer); skip watermarking oversized files
    # entirely so pypdf/PIL can't threaten the worker's memory cap.
    watermarked: bytes | None = None
    size_skipped = not should_watermark(len(raw))
    if not size_skipped:
        watermarked = load_cached(document_id, version, viewer_name)
        if watermarked is None:
            watermarked = watermark_bytes(raw, file_path.name, viewer_name)
            store_cached(document_id, version, viewer_name, watermarked)

    # Rule #8: document access is audit-logged. A raw-bytes pass-through
    # (unsupported type, a watermarking failure, or the size guard) is
    # recorded explicitly so the compliance bypass is never invisible.
    from app.audit.audit_logger import AuditLogEntry, log_query

    bypassed = watermarked is None or watermarked == raw
    outcome = "document_view"
    if size_skipped:
        outcome = "document_view_unwatermarked_oversize"
    elif bypassed:
        outcome = "document_view_unwatermarked"
    log_query(AuditLogEntry(
        user_id=int(user["client_id"]),
        query=f"document file: {document_id}",
        retrieved_ids=[document_id],
        outcome=outcome,
        audience="client",
    ))

    if bypassed:
        # No watermark could be applied (unsupported type, failure, or the
        # size guard): serve as an explicit attachment download rather than
        # silently presenting raw bytes inline as if watermarked. The
        # bypass is audit-logged above.
        return FileResponse(
            file_path,
            filename=row["title"] or file_path.name,
            content_disposition_type="attachment",
        )

    media_type = "application/pdf" if file_path.name.lower().endswith(".pdf") else None
    return Response(
        content=watermarked,
        media_type=media_type,
        headers={
            "Content-Disposition": f'inline; filename="{row["title"] or file_path.name}"'
        },
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


# ---------------------------------------------------------------------------
# Case checklist (K1: Document checklist derived from case type)
# ---------------------------------------------------------------------------

CASE_CHECKLIST_DEFAULTS: dict[str, list[str]] = {
    "mortgage": [
        "Income verification",
        "Property appraisal",
        "Title search",
        "DTI ratio calculation",
        "Down payment documentation",
    ],
    "refinance": [
        "Current mortgage statement",
        "Income verification",
        "Credit report",
        "Property appraisal",
        "Closing disclosure",
    ],
    "home equity": [
        "Income verification",
        "Credit report",
        "Appraisal",
        "Loan-to-value calculation",
        "Title search",
    ],
}


def _derive_case_checklist(case_number: str | None) -> list[str]:
    """Derive checklist items from the case number prefix (case type)."""
    if not case_number:
        return []
    prefix = case_number.split("-")[0].lower() if "-" in case_number else case_number.lower()
    return CASE_CHECKLIST_DEFAULTS.get(prefix, [])


@router.get("/cases/{case_id}/checklist")
async def client_case_checklist(
    case_id: int,
    user: dict = Depends(require_auth),
) -> dict:
    """Return the document checklist for one of the client's own cases.

    Derives required items from the case type (case number prefix),
    then checks which have been satisfied by approved documents.
    Scoping is enforced in the SQL WHERE clause (CLAUDE.md rule 1).
    """
    _require_client(user)
    _assert_owns_case(user, case_id)

    with session.acquire() as conn:
        with conn.cursor() as cur:
            # Get case number to determine checklist type
            cur.execute(
                "SELECT case_number FROM cases WHERE id = %s AND client_id = %s",
                (case_id, user["client_id"]),
            )
            case_row = cur.fetchone()
            if not case_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Case not found",
                )

            case_number = case_row[0]
            required_items = _derive_case_checklist(case_number)

            # Check which items are satisfied by approved documents matching
            # the item as doc_type (case-insensitive).
            if required_items:
                cur.execute(
                    """
                    SELECT reqs.item,
                           EXISTS(
                               SELECT 1 FROM documents d
                               WHERE d.client_id = %s
                                 AND d.is_active = true
                                 AND d.approval_status = 'approved'
                                 AND LOWER(d.doc_type) = LOWER(reqs.item)
                           ) AS satisfied
                    FROM (SELECT UNNEST(%s::text[]) AS item) AS reqs
                    ORDER BY reqs.item
                    """,
                    (user["client_id"], required_items),
                )
                items = [
                    {"item": row["item"], "satisfied": bool(row["satisfied"])}
                    for row in cur.fetchall()
                ]
            else:
                items = []

    return {"case_id": case_id, "checklist": items}


@router.get("/cases/{case_id}/timeline")
async def client_case_timeline(
    case_id: int,
    user: dict = Depends(require_auth),
) -> dict:
    """Return the ordered status timeline for one of the client's own cases.

    Events are fetched from the ``case_events`` table, sorted by ``created_at``
    ascending, so the UI can render a vertical timeline of case progress.
    Scoping is enforced in the SQL WHERE clause (CLAUDE.md rule 1).
    """
    _require_client(user)
    _assert_owns_case(user, case_id)

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, case_id, status, note, created_at "
                "FROM case_events WHERE case_id = %s ORDER BY created_at ASC, id ASC",
                (case_id,),
            )
            events = [dict(row) for row in cur.fetchall()]

    return {"case_id": case_id, "timeline": events}


# ---------------------------------------------------------------------------
# Client profile settings (K4: change contact details + notification prefs)
# ---------------------------------------------------------------------------


class ProfileUpdate(BaseModel):
    full_name: str | None = None
    notification_prefs: list[str] | None = None


@router.patch("/me")
async def client_profile_update(
    profile: ProfileUpdate,
    user: dict = Depends(require_auth),
) -> dict:
    """Update the authenticated client's profile (contact details + notification prefs)."""
    _require_client(user)

    with session.acquire() as conn:
        with conn.cursor() as cur:
            # Build the update dynamically from provided fields
            set_parts: list[str] = []
            params: list = []

            if profile.full_name is not None:
                set_parts.append("full_name = %s")
                params.append(profile.full_name.strip())

            if profile.notification_prefs is not None:
                # Validate notification prefs are valid types
                valid_types = {"info", "warning", "error", "success"}
                prefs = [p.strip() for p in profile.notification_prefs if p.strip() in valid_types]
                set_parts.append("notification_prefs = %s")
                params.append(json.dumps(prefs))

            if not set_parts:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="At least one field to update must be provided",
                )

            params.append(user["client_id"])
            set_clause = ", ".join(set_parts)

            cur.execute(
                f"UPDATE clients SET {set_clause} WHERE id = %s RETURNING id, email, full_name, is_active, created_at, notification_prefs",
                params,
            )
            row = cur.fetchone()
            conn.commit()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found",
        )

    return {"client": client_row_to_dict(dict(row))}


# ---------------------------------------------------------------------------
# E-sign (K5: client views and signs signature requests on their own cases)
# ---------------------------------------------------------------------------


@router.get("/signature-requests")
async def client_signature_requests(
    user: dict = Depends(require_auth),
) -> dict:
    """List the client's signature requests (across their own cases).

    Scoping is enforced in the SQL WHERE clause (CLAUDE.md rule 1): requests
    must belong to a case owned by the authenticated client.
    """
    _require_client(user)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT sr.id, sr.case_id, sr.document_id, sr.status, "
                "sr.signed_name, sr.signed_at, sr.created_at, "
                "d.title AS document_title "
                "FROM signature_requests sr "
                "JOIN cases c ON c.id = sr.case_id "
                "LEFT JOIN documents d ON d.id = sr.document_id "
                "WHERE c.client_id = %s "
                "ORDER BY sr.created_at DESC",
                (user["client_id"],),
            )
            requests = [dict(row) for row in cur.fetchall()]

    return {"signature_requests": requests}


class SignatureSignRequest(BaseModel):
    signed_name: str = Field(min_length=1, max_length=200)
    consent: bool = True


@router.post("/signature-requests/{request_id}/sign")
async def client_sign_signature_request(
    request_id: int,
    payload: SignatureSignRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """Client signs a pending signature request on one of their own cases.

    Only the client who owns the case may sign. The request must be pending.
    """
    _require_client(user)

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT sr.id, sr.document_id, sr.status "
                "FROM signature_requests sr "
                "JOIN cases c ON c.id = sr.case_id "
                "WHERE sr.id = %s AND c.client_id = %s",
                (request_id, user["client_id"]),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Signature request not found",
                )
            if row["status"] != "pending":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Signature request is not in pending state",
                )
            if not payload.consent:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Consent is required to sign",
                )

            signed_at = datetime.now(timezone.utc)
            cur.execute(
                "UPDATE signature_requests SET status = 'signed', "
                "signed_name = %s, consent = true, signed_at = %s, "
                "updated_at = now() WHERE id = %s",
                (payload.signed_name.strip(), signed_at, request_id),
            )

            doc_id = row["document_id"]
            if doc_id is not None:
                cur.execute(
                    "UPDATE documents SET approval_status = 'approved', "
                    "is_approved = true, version = version + 1 WHERE id = %s",
                    (doc_id,),
                )
            conn.commit()

        # G3: tell staff the document has been signed (best-effort, after
        # the signing transaction committed so notifications never roll back
        # with it).
        from app.api.v1.notifications import notify_admins

        with session.acquire() as conn:
            notify_admins(
                conn,
                "signature_signed",
                "Document signed",
                f"Signature request #{request_id} was signed"
                + (f" by {payload.signed_name.strip()}" if payload.signed_name else ""),
                link="/admin",
            )
            conn.commit()

    return {
        "message": "Document signed",
        "document_id": doc_id,
        "signed_at": signed_at.isoformat(),
    }
