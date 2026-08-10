"""Admin endpoints for user and client management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from passlib.hash import bcrypt
from pydantic import BaseModel

from app.auth.permissions import require_role
from app.dependencies import require_auth
from app.db.postgres.models import sop_request_row_to_dict, sop_row_to_dict
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

    from app.auth.roles_config import DEPARTMENTS, ROLE_HIERARCHY, ROLES

    return {
        "roles": ROLES,
        "departments": DEPARTMENTS,
        "role_hierarchy": ROLE_HIERARCHY,
    }
