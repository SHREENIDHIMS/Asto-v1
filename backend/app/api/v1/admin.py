"""Admin endpoints for user and client management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
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

    return {
        "pending_approvals": pending_approvals,
        "stale_pending_approvals": stale_pending_approvals,
        "total_documents": total_documents,
        "total_users": total_users,
        "total_clients": total_clients,
        "active_cases": active_cases,
        "total_gaps": total_gaps,
        "pending_sop_requests": pending_sop_requests,
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


@router.get("/audit")
async def get_audit_log(
    user: dict = Depends(require_auth),
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
