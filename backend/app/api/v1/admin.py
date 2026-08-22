"""Admin endpoints for user and client management."""

from __future__ import annotations

import csv
import io
import json as jsonlib
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Query,
    Response,
    status,
)
from fastapi.responses import JSONResponse, StreamingResponse
from passlib.hash import bcrypt
from pydantic import BaseModel

from app.auth.permissions import require_manage_governance, require_role
from app.dependencies import require_auth
from app.db.postgres.models import (
    audit_row_to_dict,
    sop_request_row_to_dict,
    sop_row_to_dict,
)
from app.db.postgres import session
from app.search.hybrid_orchestrator import invalidate_synonyms_cache

router = APIRouter()


class CreateUserRequest(BaseModel):
    email: str
    password: str
    full_name: str | None = None
    role: str = "loan_officer"
    department: str = "general"
    allowed_departments: list[str] = []


class CreateClientRequest(BaseModel):
    email: str
    password: str
    full_name: str | None = None


class AssignClientRequest(BaseModel):
    client_id: int
    user_id: int


# --- H4: admin 2FA (TOTP) ---


class TwoFaSetupResponse(BaseModel):
    otpauth_uri: str
    secret: str


class TwoFaVerifyRequest(BaseModel):
    code: str


class TwoFaDisableRequest(BaseModel):
    current_password: str


class TwoFaStatusResponse(BaseModel):
    enabled: bool


@router.get("/2fa/status", response_model=TwoFaStatusResponse)
async def two_fa_status(user: dict = Depends(require_auth)) -> TwoFaStatusResponse:
    """Whether the authenticated admin has 2FA enabled."""
    require_role(user, "admin")

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT totp_enabled FROM users WHERE id = %s",
                (int(user["id"]),),
            )
            row = cur.fetchone()
    return TwoFaStatusResponse(enabled=bool(row and row["totp_enabled"]))


@router.post("/2fa/setup", response_model=TwoFaSetupResponse)
async def two_fa_setup(user: dict = Depends(require_auth)) -> TwoFaSetupResponse:
    """Start 2FA enrollment: return a fresh TOTP secret + otpauth URI.

    The secret is stored encrypted on the user row but 2FA stays disabled
    until /admin/2fa/verify confirms the user scanned it with a valid code.
    Re-running setup overwrites the pending secret; a fully-enabled account
    must be disabled first.
    """
    require_role(user, "admin")
    user_id = int(user["id"])

    from app.auth.totp import encrypt_secret, new_secret, provisioning_uri

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT totp_enabled FROM users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if row and row["totp_enabled"]:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="2FA is already enabled; disable it first to re-enroll",
                )

            secret = new_secret()
            cur.execute(
                "UPDATE users SET totp_secret = %s, totp_enabled = false WHERE id = %s",
                (encrypt_secret(secret), user_id),
            )
        conn.commit()

    return TwoFaSetupResponse(
        otpauth_uri=provisioning_uri(secret, user["email"]),
        secret=secret,
    )


@router.post("/2fa/verify", response_model=TwoFaStatusResponse)
async def two_fa_verify(
    request: TwoFaVerifyRequest,
    user: dict = Depends(require_auth),
) -> TwoFaStatusResponse:
    """Confirm enrollment by checking the code against the pending secret.

    On a valid code the account's 2FA is enabled (the stored secret becomes
    live for /auth/login). Wrong code -> 401.
    """
    require_role(user, "admin")
    user_id = int(user["id"])

    from app.auth.totp import decrypt_secret, verify_code

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT totp_secret, totp_enabled FROM users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()

            if row is None or not row["totp_secret"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No pending 2FA setup; call /admin/2fa/setup first",
                )
            if row["totp_enabled"]:
                return TwoFaStatusResponse(enabled=True)

            secret = decrypt_secret(row["totp_secret"])
            if secret is None or not verify_code(secret, request.code):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid 2FA code",
                )

            cur.execute(
                "UPDATE users SET totp_enabled = true WHERE id = %s",
                (user_id,),
            )
        conn.commit()

    return TwoFaStatusResponse(enabled=True)


@router.post("/2fa/disable", response_model=TwoFaStatusResponse)
async def two_fa_disable(
    request: TwoFaDisableRequest,
    user: dict = Depends(require_auth),
) -> TwoFaStatusResponse:
    """Disable 2FA. Requires the account's current password (H4)."""
    require_role(user, "admin")
    user_id = int(user["id"])

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT password_hash FROM users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Account not found",
                )
            if not bcrypt.verify(request.current_password, row["password_hash"]):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Current password is incorrect",
                )

            cur.execute(
                "UPDATE users SET totp_secret = NULL, totp_enabled = false WHERE id = %s",
                (user_id,),
            )
        conn.commit()

    return TwoFaStatusResponse(enabled=False)


@router.get("/users")
async def list_users(user: dict = Depends(require_auth)) -> dict:
    """List users. Requires admin role."""
    require_role(user, "admin")

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, full_name, role, department, allowed_departments, "
                "is_active, created_at FROM users ORDER BY id"
            )
            users = [dict(row) for row in cur.fetchall()]

    return {"users": users}


@router.get("/summary")
async def admin_summary(user: dict = Depends(require_auth)) -> dict:
    """Aggregate counts for the admin dashboard stat cards."""
    require_role(user, "admin")

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM documents WHERE approval_status = 'pending'"
            )
            pending_approvals = cur.fetchone()["n"] or 0

            cur.execute(
                "SELECT COUNT(*) AS n FROM documents "
                "WHERE approval_status = 'pending' AND created_at < now() - interval '7 days'"
            )
            stale_pending_approvals = cur.fetchone()["n"] or 0

            cur.execute("SELECT COUNT(*) AS n FROM documents")
            total_documents = cur.fetchone()["n"] or 0

            cur.execute("SELECT COUNT(*) AS n FROM users")
            total_users = cur.fetchone()["n"] or 0

            cur.execute("SELECT COUNT(*) AS n FROM clients")
            total_clients = cur.fetchone()["n"] or 0

            cur.execute("SELECT COUNT(*) AS n FROM cases WHERE is_active = true")
            active_cases = cur.fetchone()["n"] or 0

            cur.execute("SELECT COUNT(*) AS n FROM knowledge_gaps")
            total_gaps = cur.fetchone()["n"] or 0

            cur.execute(
                "SELECT COUNT(*) AS n FROM sop_access_requests WHERE status = 'pending'"
            )
            pending_sop_requests = cur.fetchone()["n"] or 0

            cur.execute(
                "SELECT COUNT(*) AS n FROM documents "
                "WHERE is_active = true AND approval_status = 'approved' "
                "AND review_due IS NOT NULL AND review_due < CURRENT_DATE"
            )
            documents_review_overdue = cur.fetchone()["n"] or 0

    return {
        "pending_approvals": pending_approvals,
        "stale_pending_approvals": stale_pending_approvals,
        "total_documents": total_documents,
        "total_users": total_users,
        "total_clients": total_clients,
        "active_cases": active_cases,
        "total_gaps": total_gaps,
        "pending_sop_requests": pending_sop_requests,
        "documents_review_overdue": documents_review_overdue,
    }


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    request: CreateUserRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """Create a staff user. Requires admin role."""
    require_role(user, "admin")

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM users WHERE email = %s",
                (request.email,),
            )
            if cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"User with email '{request.email}' already exists",
                )

            cur.execute(
                "INSERT INTO users (email, password_hash, full_name, role, department, allowed_departments) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    request.email,
                    bcrypt.hash(request.password),
                    request.full_name,
                    request.role,
                    request.department,
                    request.allowed_departments,
                ),
            )
            new_id = cur.fetchone()["id"]
        conn.commit()

    return {"message": "User created", "user_id": new_id}


@router.get("/clients")
async def list_clients(user: dict = Depends(require_auth)) -> dict:
    """List clients. Requires admin role."""
    require_role(user, "admin")

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, full_name, is_active, created_at "
                "FROM clients ORDER BY id"
            )
            clients = [dict(row) for row in cur.fetchall()]

    return {"clients": clients}


@router.post("/clients", status_code=status.HTTP_201_CREATED)
async def create_client(
    request: CreateClientRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """Create an external client account. Requires admin role."""
    require_role(user, "admin")

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM clients WHERE email = %s",
                (request.email,),
            )
            if cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Client with email '{request.email}' already exists",
                )

            cur.execute(
                "INSERT INTO clients (email, password_hash, full_name) "
                "VALUES (%s, %s, %s) RETURNING id",
                (request.email, bcrypt.hash(request.password), request.full_name),
            )
            new_id = cur.fetchone()["id"]
        conn.commit()

    return {"message": "Client created", "client_id": new_id}


@router.post("/assignments", status_code=status.HTTP_201_CREATED)
async def assign_staff_to_client(
    request: AssignClientRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """Assign a staff user to a client (scopes staff search to that client)."""
    require_role(user, "admin")

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO staff_client_assignments (user_id, client_id) "
                "VALUES (%s, %s) "
                "ON CONFLICT (user_id, client_id) DO NOTHING",
                (request.user_id, request.client_id),
            )
        conn.commit()

    return {"message": "Staff assigned to client"}


@router.get("/users/{user_id}/sessions")
async def list_user_sessions(
    user_id: int,
    user: dict = Depends(require_auth),
) -> dict:
    """List a staff user's active (non-revoked, unexpired) refresh sessions.

    H5 session revocation: lets an admin see how many devices/sessions a
    user has before killing them. Only active rows count; identities are
    resolved from the ``users`` table.
    """
    require_role(user, "admin")

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
            if cur.fetchone() is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found",
                )
            cur.execute(
                "SELECT id, audience, expires_at, created_at "
                "FROM refresh_tokens "
                "WHERE user_id = %s AND revoked_at IS NULL AND expires_at > now() "
                "ORDER BY created_at DESC",
                (user_id,),
            )
            sessions = [dict(row) for row in cur.fetchall()]

    return {
        "user_id": user_id,
        "active_sessions": len(sessions),
        "sessions": sessions,
    }


@router.post("/users/{user_id}/sessions/revoke")
async def revoke_user_sessions(
    user_id: int,
    user: dict = Depends(require_auth),
) -> dict:
    """Kill every refresh session for a staff user (H5 admin session-kill).

    Revokes all of the user's un-expired refresh-token rows, so their
    cookies can no longer be exchanged for new access JWTs. Already-issued
    access JWTs remain valid until expiry (documented trade-off).
    """
    require_role(user, "admin")

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
            if cur.fetchone() is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found",
                )
            cur.execute(
                "UPDATE refresh_tokens SET revoked_at = now() "
                "WHERE user_id = %s AND revoked_at IS NULL",
                (user_id,),
            )
            revoked = cur.rowcount
        conn.commit()

    return {"user_id": user_id, "revoked_sessions": revoked}


@router.get("/clients/{client_id}/sessions")
async def list_client_sessions(
    client_id: int,
    user: dict = Depends(require_auth),
) -> dict:
    """List an external client's active refresh sessions (H5)."""
    require_role(user, "admin")

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM clients WHERE id = %s", (client_id,))
            if cur.fetchone() is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Client not found",
                )
            cur.execute(
                "SELECT id, audience, expires_at, created_at "
                "FROM refresh_tokens "
                "WHERE client_id = %s AND revoked_at IS NULL AND expires_at > now() "
                "ORDER BY created_at DESC",
                (client_id,),
            )
            sessions = [dict(row) for row in cur.fetchall()]

    return {
        "client_id": client_id,
        "active_sessions": len(sessions),
        "sessions": sessions,
    }


@router.post("/clients/{client_id}/sessions/revoke")
async def revoke_client_sessions(
    client_id: int,
    user: dict = Depends(require_auth),
) -> dict:
    """Kill every refresh session for a client account (H5 admin session-kill)."""
    require_role(user, "admin")

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM clients WHERE id = %s", (client_id,))
            if cur.fetchone() is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Client not found",
                )
            cur.execute(
                "UPDATE refresh_tokens SET revoked_at = now() "
                "WHERE client_id = %s AND revoked_at IS NULL",
                (client_id,),
            )
            revoked = cur.rowcount
        conn.commit()

    return {"client_id": client_id, "revoked_sessions": revoked}


@router.get("/clients/{client_id}/export")
async def admin_client_export(
    client_id: int,
    user: dict = Depends(require_auth),
) -> JSONResponse:
    """Admin GDPR-style export of a client's personal data (M5).

    Same shape as the client self-serve export. Admin-only and audit-logged.
    """
    require_role(user, "admin")
    from app.audit.audit_logger import AuditLogEntry, log_query
    from app.clients.export import build_client_export, json_safe

    payload = json_safe(build_client_export(client_id))
    if not payload["exists"]:
        raise HTTPException(status_code=404, detail="Client not found")

    log_query(
        AuditLogEntry(
            user_id=int(user["id"]),
            query="admin client data export",
            outcome=f"client_id={client_id}",
        )
    )
    return JSONResponse(
        payload,
        headers={
            "Content-Disposition": f'attachment; filename="client_{client_id}_data.json"',
            "Content-Type": "application/json",
        },
    )


class ReviewSopAccessRequest(BaseModel):
    decision: str
    reason: str | None = None


@router.get("/sop-access-requests")
async def list_sop_access_requests(
    status_filter: str | None = None,
    user: dict = Depends(require_auth),
) -> dict:
    """List SOP access requests (optionally filtered by status)."""
    require_role(user, "admin")
    with session.acquire() as conn:
        with conn.cursor() as cur:
            if status_filter:
                cur.execute(
                    "SELECT r.*, u.email AS requester_email "
                    "FROM sop_access_requests r JOIN users u ON u.id = r.user_id "
                    "WHERE r.status = %s ORDER BY r.created_at DESC",
                    (status_filter,),
                )
            else:
                cur.execute(
                    "SELECT r.*, u.email AS requester_email "
                    "FROM sop_access_requests r JOIN users u ON u.id = r.user_id "
                    "ORDER BY r.created_at DESC"
                )
            requests = [dict(row) for row in cur.fetchall()]
    return {"requests": [sop_request_row_to_dict(dict(r)) for r in requests]}


@router.post("/sop-access-requests/{request_id}/review")
async def review_sop_access_request(
    request_id: int,
    request: ReviewSopAccessRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """Approve or reject an SOP access request."""
    require_role(user, "admin")
    if request.decision not in ("approved", "rejected"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Decision must be 'approved' or 'rejected'",
        )
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM sop_access_requests WHERE id = %s",
                (request_id,),
            )
            if cur.fetchone() is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="SOP access request not found",
                )
            cur.execute(
                "UPDATE sop_access_requests SET status = %s, reason = COALESCE(%s, reason), "
                "reviewed_by = %s, reviewed_at = now() WHERE id = %s",
                (request.decision, request.reason, user["id"], request_id),
            )
        conn.commit()
    return {"message": f"Request {request.decision}", "request_id": request_id}


# ---------------------------------------------------------------------------
# Synonym / alias management (J8: domain aliases improve recall)
# ---------------------------------------------------------------------------


class SynonymEntry(BaseModel):
    canonical: str
    alias: str


class SynonymCreate(SynonymEntry):
    pass


@router.get("/synonyms", response_model=list[SynonymEntry])
async def list_synonyms(user: dict = Depends(require_auth)) -> list[SynonymEntry]:
    """List all canonical/alias pairs. Admin only."""
    require_role(user, "admin")
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT canonical, alias FROM synonyms ORDER BY canonical, alias"
            )
            rows = cur.fetchall()
    return [SynonymEntry(canonical=row["canonical"], alias=row["alias"]) for row in rows]


@router.post("/synonyms", status_code=status.HTTP_201_CREATED, response_model=SynonymEntry)
async def create_synonym(
    entry: SynonymCreate,
    user: dict = Depends(require_auth),
) -> SynonymEntry:
    """Create a canonical/alias pair. Admin only."""
    require_role(user, "admin")
    with session.acquire() as conn:
        with conn.cursor() as cur:
            # Check if already exists first
            cur.execute(
                "SELECT id FROM synonyms WHERE canonical = %s AND alias = %s",
                (entry.canonical, entry.alias),
            )
            if cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Synonym already exists: '{entry.alias}' for canonical '{entry.canonical}'",
                )
            cur.execute(
                "INSERT INTO synonyms (canonical, alias) VALUES (%s, %s) RETURNING canonical, alias",
                (entry.canonical, entry.alias),
            )
            new_row = cur.fetchone()
        conn.commit()
    invalidate_synonyms_cache()
    return SynonymEntry(canonical=new_row["canonical"], alias=new_row["alias"])


@router.delete("/synonyms/{canonical}/{alias}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_synonym(
    canonical: str,
    alias: str,
    user: dict = Depends(require_auth),
) -> None:
    """Delete a canonical/alias pair. Admin only."""
    require_role(user, "admin")
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM synonyms WHERE canonical = %s AND alias = %s",
                (canonical, alias),
            )
            if cur.rowcount == 0:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Synonym not found",
                )
        conn.commit()
    invalidate_synonyms_cache()
    return None


# Alias expansion in query text (for diagnostics)
@router.get("/synonyms/expand/{text}")
async def expand_query_synonyms(text: str, user: dict = Depends(require_auth)) -> dict:
    """Return the text with database synonyms expanded (added as extra terms).
    Admin only. Pulls from the database synonyms table."""
    require_role(user, "admin")
    with session.acquire() as conn:
        with conn.cursor() as cur:
            # Find aliases that appear in the text
            cur.execute(
                "SELECT canonical, alias FROM synonyms WHERE alias ILIKE %s OR canonical ILIKE %s",
                (f"%{text}%", f"%{text}%"),
            )
            matches = cur.fetchall()
    expanded_parts: list[str] = [text]
    seen: set[str] = set()
    for row in matches:
        canonical, alias = row["canonical"], row["alias"]
        if alias.lower() in text.lower() and canonical not in seen:
            seen.add(canonical)
            expanded_parts.append(canonical)
    expanded = " ".join(expanded_parts).strip()
    return {"original": text, "expanded": expanded if expanded != text else text}


# ---------------------------------------------------------------------------
# Knowledge Base browse (read-only) + governance views (Phase F3)
# ---------------------------------------------------------------------------


@router.get("/documents/{document_id}/chunks")
async def list_document_chunks(
    document_id: int,
    user: dict = Depends(require_auth),
) -> dict:
    """Read-only chunk list for a document (Knowledge Base browse)."""
    require_role(user, "admin")

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM documents WHERE id = %s", (document_id,))
            if cur.fetchone() is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Document not found",
                )
            cur.execute(
                "SELECT id, section, chunk_type, department, content, "
                "approval_status, is_approved, created_at "
                "FROM document_chunks WHERE document_id = %s "
                "ORDER BY id",
                (document_id,),
            )
            chunks = [dict(row) for row in cur.fetchall()]

    return {"document_id": document_id, "chunks": chunks}


@router.get("/sops")
async def list_all_sops(user: dict = Depends(require_auth)) -> dict:
    """List all SOPs across every department (admin read-all)."""
    require_role(user, "admin")

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM sops WHERE is_active = true "
                "ORDER BY department, updated_at DESC"
            )
            sops = [dict(row) for row in cur.fetchall()]

    return {"sops": [sop_row_to_dict(dict(r)) for r in sops]}


@router.get("/governance")
async def get_governance(user: dict = Depends(require_auth)) -> dict:
    """Config-driven roles + departments for the admin governance views."""
    require_role(user, "admin")

    from app.auth.roles_config import (
        DEPARTMENTS,
        ROLE_CAPABILITIES,
        ROLE_HIERARCHY,
        ROLES,
    )

    roles = []
    for role in ROLES:
        item = dict(role)
        item.setdefault("capabilities", list(ROLE_CAPABILITIES.get(role["name"], [])))
        roles.append(item)

    return {
        "roles": roles,
        "departments": DEPARTMENTS,
        "role_hierarchy": ROLE_HIERARCHY,
    }


class GovernanceRoleInput(BaseModel):
    name: str
    label: str
    description: str = ""
    access: list[str] | str = []
    capabilities: list[str] = []


class GovernanceDepartmentInput(BaseModel):
    name: str
    label: str
    description: str = ""


class GovernanceUpdateRequest(BaseModel):
    roles: list[GovernanceRoleInput]
    departments: list[GovernanceDepartmentInput]
    role_hierarchy: list[str] | None = None


def _apply_department_renames(renames: dict[str, str]) -> None:
    """Migrate every table that stores a department name (H7 rename)."""
    if not renames:
        return
    with session.acquire() as conn:
        with conn.cursor() as cur:
            for old, new in renames.items():
                cur.execute(
                    "UPDATE users SET department = %s WHERE department = %s",
                    (new, old),
                )
                cur.execute(
                    "UPDATE users SET allowed_departments = "
                    "array_replace(allowed_departments, %s, %s) "
                    "WHERE %s = ANY(allowed_departments)",
                    (old, new, old),
                )
                cur.execute(
                    "UPDATE documents SET department = %s WHERE department = %s",
                    (new, old),
                )
                cur.execute(
                    "UPDATE document_chunks SET department = %s WHERE department = %s",
                    (new, old),
                )
                cur.execute(
                    "UPDATE sops SET department = %s WHERE department = %s",
                    (new, old),
                )
                cur.execute(
                    "UPDATE sop_access_requests SET department = %s WHERE department = %s",
                    (new, old),
                )
                cur.execute(
                    "UPDATE workflows SET department = %s WHERE department = %s",
                    (new, old),
                )
        conn.commit()


@router.put("/governance")
async def update_governance(
    request: GovernanceUpdateRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """Write back the roles/departments config (H7, ROADMAP Option A).

    The Python config file stays the source of truth; this endpoint
    validates the payload, atomically rewrites ``roles_config.py``, reloads
    it (so running handlers pick it up), migrates any renamed departments in
    the DB, and audit-logs the change.
    """
    require_manage_governance(user)

    from app.auth import governance as governance_writer
    from app.auth.roles_config import (
        DEPARTMENTS as CURRENT_DEPARTMENTS,
        ROLE_HIERARCHY as CURRENT_HIERARCHY,
        ROLES as CURRENT_ROLES,
    )

    current_role_names = {r["name"] for r in CURRENT_ROLES}
    submitted_role_names = {r.name for r in request.roles}
    if submitted_role_names != current_role_names:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Roles cannot be added or removed; edit the existing role set",
        )

    dept_names = [d.name for d in request.departments]
    if len(dept_names) != len(set(dept_names)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Department names must be unique",
        )
    for dept in request.departments:
        if not governance_writer.DEPT_NAME_RE.match(dept.name):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid department name '{dept.name}'",
            )
        if not dept.label.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Department labels cannot be empty",
            )

    known_capabilities = governance_writer.KNOWN_CAPABILITIES
    dept_name_set = set(dept_names)
    for role in request.roles:
        if not role.label.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Role '{role.name}' needs a non-empty label",
            )
        unknown = set(role.capabilities) - known_capabilities
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown capability(s): {', '.join(sorted(unknown))}",
            )
        access = role.access
        access_list = [] if access == "all" else list(access)
        for dept in access_list:
            if dept not in dept_name_set:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Role '{role.name}' references unknown department '{dept}'",
                )

    hierarchy = request.role_hierarchy or CURRENT_HIERARCHY
    if set(hierarchy) != current_role_names:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Role hierarchy must contain exactly the known roles",
        )

    roles_out = []
    for role in request.roles:
        roles_out.append(
            {
                "name": role.name,
                "label": role.label,
                "description": role.description or "",
                "access": "all" if role.access == "all" else list(role.access),
                "capabilities": list(role.capabilities),
            }
        )
    departments_out = [
        {"name": d.name, "label": d.label, "description": d.description or ""}
        for d in request.departments
    ]

    # Departments are matched positionally: the UI keeps the list order stable
    # and appends new departments at the end, so an index change is a rename.
    old_dept_names = [d["name"] for d in CURRENT_DEPARTMENTS]
    renames = {}
    for i, new_dept in enumerate(request.departments):
        if i < len(old_dept_names) and old_dept_names[i] != new_dept.name:
            renames[old_dept_names[i]] = new_dept.name

    default_department = renames.get("general", "general")

    _apply_department_renames(renames)
    try:
        governance_writer.write_config(
            roles=roles_out,
            departments=departments_out,
            role_hierarchy=list(hierarchy),
            default_department=default_department,
        )
    except Exception:
        # Keep config and DB consistent: roll the renamed rows back.
        _apply_department_renames({new: old for old, new in renames.items()})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist governance configuration",
        )

    from app.audit.audit_logger import AuditLogEntry, log_query

    log_query(
        AuditLogEntry(
            user_id=int(user["id"]),
            query="governance update",
            outcome="roles/departments config written back",
        )
    )

    return {
        "roles": roles_out,
        "departments": departments_out,
        "role_hierarchy": list(hierarchy),
    }


# ---------------------------------------------------------------------------
# Feature flags (M8: ship half-built features safely)
# ---------------------------------------------------------------------------


class FeatureFlagSetRequest(BaseModel):
    name: str
    enabled: bool


@router.get("/flags")
async def list_feature_flags(user: dict = Depends(require_auth)) -> dict:
    """List all known feature flags with their effective value and source.

    ``source`` is ``table`` when a DB row overrides the compiled-in default,
    ``default`` otherwise. Admin-only.
    """
    require_role(user, "admin")
    from app import feature_flags

    return {"flags": feature_flags.get_all_flags()}


@router.post("/flags")
async def set_feature_flag(
    body: FeatureFlagSetRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """Toggle a feature flag (upsert). The change is audit-logged. Admin-only."""
    require_role(user, "admin")
    from app import feature_flags

    result = feature_flags.set_flag(body.name, body.enabled)

    from app.audit.audit_logger import AuditLogEntry, log_query

    log_query(
        AuditLogEntry(
            user_id=int(user["id"]),
            query=f"feature flag {body.name}",
            outcome=f"enabled={body.enabled}",
        )
    )
    return result


@router.get("/audit")
async def get_audit_log(    user: dict = Depends(require_auth),
    q: str | None = Query(default=None, max_length=200),
    actor: str | None = Query(default=None, max_length=200),
    outcome: str | None = Query(default=None, max_length=50),
    date_from: str | None = Query(default=None, alias="from", max_length=30),
    date_to: str | None = Query(default=None, alias="to", max_length=30),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Filterable, paginated audit log (Phase F7).

    Filters (all optional, combined with AND):
    - ``q``: free-text search over the query text.
    - ``actor``: matches the querying user's email OR full name (staff or
      client audience — audit rows carry no audience tag, so the actor is
      resolved by LEFT JOINing both tables; the filter scans both).
    - ``outcome``: exact outcome (e.g. ``answer``, ``partial``,
      ``no_answer``, ``no_sub_queries``, ``validation_failed:...``).
    - ``from``/``to``: ISO date range on ``created_at`` (inclusive).
    - ``limit``/``offset``: pagination.
    Returns ``entries`` plus the total match count for the current filter.
    """
    require_role(user, "admin")

    where_sql, params = _audit_filter_clause(q, actor, outcome, date_from, date_to)

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM audit_log a "
                "LEFT JOIN users u ON u.id = a.user_id "
                "LEFT JOIN clients c ON c.id = a.user_id "
                f"{where_sql}",
                params,
            )
            total = cur.fetchone()["n"] or 0

            cur.execute(
                "SELECT a.id, a.user_id, a.query, a.sub_queries, a.retrieved_ids, "
                "a.confidence, a.response_id, a.outcome, a.latency_ms, a.created_at, "
                "COALESCE(u.full_name, c.full_name) AS actor, "
                "COALESCE(u.email, c.email) AS actor_email "
                "FROM audit_log a "
                "LEFT JOIN users u ON u.id = a.user_id "
                "LEFT JOIN clients c ON c.id = a.user_id "
                f"{where_sql} "
                "ORDER BY a.created_at DESC, a.id DESC "
                "LIMIT %s OFFSET %s",
                [*params, limit, offset],
            )
            rows = [dict(row) for row in cur.fetchall()]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "entries": [audit_row_to_dict(r) for r in rows],
    }


def _audit_filter_clause(
    q: str | None,
    actor: str | None,
    outcome: str | None,
    date_from: str | None,
    date_to: str | None,
) -> tuple[str, list]:
    """Build the shared audit-log WHERE clause (used by /audit and /audit/export).

    Returns ``(where_sql, params)``. All filters optional and ANDed.
    """
    where: list[str] = []
    params: list = []

    if q:
        where.append("a.query ILIKE %s")
        params.append(f"%{q}%")
    if actor:
        where.append(
            "(u.email ILIKE %s OR u.full_name ILIKE %s OR c.email ILIKE %s OR c.full_name ILIKE %s)"
        )
        like = f"%{actor}%"
        params.extend([like, like, like, like])
    if outcome:
        where.append("a.outcome = %s")
        params.append(outcome)
    if date_from:
        where.append("a.created_at >= %s")
        params.append(date_from)
    if date_to:
        where.append("a.created_at <= %s")
        params.append(date_to)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    return where_sql, params


AUDIT_EXPORT_COLUMNS = [
    "id",
    "user_id",
    "actor",
    "actor_email",
    "query",
    "sub_queries",
    "retrieved_ids",
    "confidence",
    "response_id",
    "outcome",
    "latency_ms",
    "created_at",
]


def _audit_export_row(row: dict) -> dict:
    """Serialize a raw audit row for CSV/JSON export.

    Array/JSONB columns become JSON strings for CSV round-tripping.
    """
    out = {key: row.get(key) for key in AUDIT_EXPORT_COLUMNS}
    if out["sub_queries"] is not None:
        out["sub_queries"] = jsonlib.dumps(out["sub_queries"])
    if out["retrieved_ids"] is not None:
        out["retrieved_ids"] = jsonlib.dumps(out["retrieved_ids"])
    return out


@router.get("/audit/export")
async def export_audit_log(
    user: dict = Depends(require_auth),
    q: str | None = Query(default=None, max_length=200),
    actor: str | None = Query(default=None, max_length=200),
    outcome: str | None = Query(default=None, max_length=50),
    date_from: str | None = Query(default=None, alias="from", max_length=30),
    date_to: str | None = Query(default=None, alias="to", max_length=30),
    format: str = Query(default="csv", pattern="^(csv|json)$"),
) -> Response:
    """Stream the filtered audit log as CSV (default) or JSON (Phase M1).

    Applies exactly the same filters as ``GET /admin/audit`` but exports
    every matching row (no pagination). Admin-only and itself audit-logged.
    Gated behind the ``audit_export`` feature flag (M8).
    """
    require_role(user, "admin")
    from app import feature_flags

    if not feature_flags.is_enabled("audit_export"):
        raise HTTPException(status_code=403, detail="Feature disabled")
    where_sql, params = _audit_filter_clause(q, actor, outcome, date_from, date_to)

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT a.id, a.user_id, a.query, a.sub_queries, a.retrieved_ids, "
                "a.confidence, a.response_id, a.outcome, a.latency_ms, a.created_at, "
                "COALESCE(u.full_name, c.full_name) AS actor, "
                "COALESCE(u.email, c.email) AS actor_email "
                "FROM audit_log a "
                "LEFT JOIN users u ON u.id = a.user_id "
                "LEFT JOIN clients c ON c.id = a.user_id "
                f"{where_sql} "
                "ORDER BY a.created_at DESC, a.id DESC",
                params,
            )
            rows = [dict(r) for r in cur.fetchall()]

    from app.audit.audit_logger import AuditLogEntry, log_query

    log_query(
        AuditLogEntry(
            user_id=int(user["id"]),
            query="audit export",
            outcome=f"format={format}",
        )
    )

    if format == "json":
        return JSONResponse(
            content={"entries": [dict(r) for r in rows], "count": len(rows)}
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    def _stream_csv():
        buf = io.StringIO()
        buf.write("\ufeff")  # UTF-8 BOM so Excel detects the encoding
        writer = csv.DictWriter(buf, fieldnames=AUDIT_EXPORT_COLUMNS)
        writer.writeheader()
        yield buf.getvalue()
        for r in rows:
            buf.seek(0)
            buf.truncate(0)
            writer.writerow(_audit_export_row(r))
            yield buf.getvalue()

    return StreamingResponse(
        _stream_csv(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="audit_log_{stamp}.csv"'
        },
    )


# ---------------------------------------------------------------------------
# Case document requirements (K1: document checklist)
# ---------------------------------------------------------------------------


class RequirementCreate:
    """Request body for creating a requirement definition."""
    def __init__(self, name: str, description: str = "", case_type: str = "purchase"):
        self.name = name
        self.description = description
        self.case_type = case_type


@router.get("/case-requirements/default/{case_type}")
async def get_default_requirements(
    case_type: str,
    user: dict = Depends(require_auth),
) -> dict:
    """Return the default requirement list for a case type (admin only)."""
    require_role(user, "admin")
    requirements = DEFAULT_REQUIREMENTS.get(case_type, [])
    return {"case_type": case_type, "requirements": requirements}


@router.post("/case-requirements/seed/{case_type}")
async def seed_case_requirements(
    case_type: str,
    user: dict = Depends(require_auth),
) -> dict:
    """Seed default requirements into the DB for a case type (admin only).

    Idempotent: skips rows that already exist.
    """
    require_role(user, "admin")
    from app.documents.requirements import seed_default_requirements

    with session.acquire() as conn:
        count = seed_default_requirements(conn, case_type)
    return {"case_type": case_type, "inserted": count}


@router.get("/case-requirements/{case_id}")
async def get_case_checklist(
    case_id: int,
    user: dict = Depends(require_auth),
) -> dict:
    """Derive the document checklist for a case.

    Returns the list of requirements with status: required/pending/received/approved.
    Staff can see all cases; client sees only their own.
    """
    require_role(user, "admin")
    from app.documents.requirements import derive_case_checklist

    with session.acquire() as conn:
        checklist = derive_case_checklist(conn, case_id)
    return {"case_id": case_id, "checklist": checklist}


# ---------------------------------------------------------------------------
# Signature requests (K5: e-sign / document request)
# ---------------------------------------------------------------------------


class SignatureRequestCreate(BaseModel):
    case_id: int
    document_id: int
    requested_from: str  # e.g. "client", "staff"


def _email_signature_request(recipient: dict) -> bool:
    """Best-effort email telling the client a document awaits their signature.

    The raw signing token is deliberately NOT included — clients sign through
    the authenticated portal (/client), so the message carries no credential.
    Uses the shared mailer, which falls back to INFO logging when SMTP is
    unconfigured and never raises (G3).
    """
    from app.email.mailer import send_email

    email = recipient.get("email")
    if not email:
        return False

    name = recipient.get("full_name") or "there"
    doc_title = recipient.get("document_title") or "a document"
    subject = "Signature requested"
    text = (
        f"Hello {name},\n\n"
        f"A signature is requested for the document \"{doc_title}\".\n"
        "Please log in to your client portal to review and sign it.\n\n"
        "— Asto"
    )
    html = (
        f"<p>Hello {name},</p>"
        f"<p>A signature is requested for the document "
        f"<strong>{doc_title}</strong>.</p>"
        '<p>Please log in to your client portal to review and sign it.</p>'
        "<p>— Asto</p>"
    )
    return send_email(email, subject, html, text)


@router.post("/signature-requests", status_code=status.HTTP_201_CREATED)
async def create_signature_request(
    request: SignatureRequestCreate,
    user: dict = Depends(require_auth),
) -> dict:
    """Staff creates a signature request for a document.

    The document must belong to a case the staff member's client is assigned to.
    A unique token is generated; the client receives a notification to sign.
    """
    require_role(user, "admin")
    import uuid
    from datetime import datetime, timezone

    token = uuid.uuid4().hex
    signed_at = None
    request_status = "pending"

    with session.acquire() as conn:
        with conn.cursor() as cur:
            # Verify the document belongs to a case assigned to the staff's client
            cur.execute(
                "SELECT id, client_id FROM documents WHERE id = %s AND is_active = true AND approval_status = 'approved'",
                (request.document_id,),
            )
            doc = cur.fetchone()
            if doc is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Document not found or not approved",
                )

            # Resolve the case's client + document title for the G3 notice
            cur.execute(
                "SELECT cl.email, cl.full_name, d.title AS document_title "
                "FROM cases cs "
                "JOIN clients cl ON cl.id = cs.client_id "
                "JOIN documents d ON d.id = %s "
                "WHERE cs.id = %s",
                (request.document_id, request.case_id),
            )
            recipient = cur.fetchone()
            if recipient is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Case not found",
                )

            cur.execute(
                "INSERT INTO signature_requests (case_id, document_id, requested_from, token, status) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id, token, status, created_at",
                (request.case_id, request.document_id, request.requested_from, token, request_status),
            )
            row = dict(cur.fetchone())
        conn.commit()

    _email_signature_request(recipient)

    return {"signature_request_id": row["id"], "token": row["token"], "status": row["status"]}


@router.get("/signature-requests")
async def list_signature_requests(
    user: dict = Depends(require_auth),
) -> dict:
    """List all signature requests (admin only)."""
    require_role(user, "admin")
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, case_id, document_id, requested_from, token, status, signed_at, created_at "
                "FROM signature_requests ORDER BY created_at DESC"
            )
            rows = cur.fetchall()
    return {"signature_requests": [{"id": r["id"], "case_id": r["case_id"], "document_id": r["document_id"],
                                     "requested_from": r["requested_from"], "token": r["token"],
                                     "status": r["status"], "signed_at": str(r["signed_at"]) if r["signed_at"] else None,
                                     "created_at": str(r["created_at"])} for r in rows]}


@router.post("/signature-requests/{request_id}/sign")
async def sign_signature_request(
    request_id: int,
    signed_name: str = Form(...),
    consent: bool = Form(...),
    user: dict = Depends(require_auth),
) -> dict:
    """Staff (on behalf of a client) signs a signature request.

    The request is marked signed with the signer's name and consent, and
    the document is version-bumped. No notification is sent yet (G3).
    """
    require_role(user, "admin")

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, case_id, document_id, status FROM signature_requests WHERE id = %s",
                (request_id,),
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
            if not consent:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Consent is required to sign",
                )

            signed_at = datetime.now(timezone.utc)
            cur.execute(
                "UPDATE signature_requests SET status = 'signed', signed_name = %s, consent = true, signed_at = %s, updated_at = now() WHERE id = %s",
                (signed_name.strip(), signed_at, request_id),
            )

            doc_id = row["document_id"]
            if doc_id is not None:
                cur.execute(
                    "UPDATE documents SET approval_status = 'approved', is_approved = true, version = version + 1 WHERE id = %s",
                    (doc_id,),
                )
            conn.commit()

    return {
        "message": "Document signed and approved",
        "document_id": doc_id,
        "signed_at": signed_at.isoformat(),
    }
