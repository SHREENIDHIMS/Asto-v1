"""Staff portal endpoints (internal audience, Â§1B).

Role-tailored hub: a dashboard of the staff member's assigned client
cases, their department's active workflows, and official SOPs, plus
collaboration notes on cases, workflow status triggers, SOP access
requests, and (for staff with an approved request) SOP authoring.

Scoping rules:
- Cases are visible only for clients the staff member is assigned to
  (admins see all).
- Workflows and SOPs are scoped to the staff member's departments
  (``department`` + ``allowed_departments``); admins see all.
- Case notes follow case visibility.
- Creating/editing SOPs requires an approved ``sop_access_requests``
  row (any action) for the staff's own department scope, or admin role.

All checks live here on read/write; search-time RBAC is unaffected.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.auth.rbac import is_admin
from app.db.postgres.models import (
    case_note_row_to_dict,
    sop_request_row_to_dict,
    sop_row_to_dict,
    workflow_row_to_dict,
)
from app.db.postgres import session
from app.dependencies import require_auth

router = APIRouter()


class NoteRequest(BaseModel):
    body: str = Field(min_length=1, max_length=2000)

    @field_validator("body")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Note cannot be empty")
        return v


class WorkflowAdvanceResponse(BaseModel):
    workflow_id: int
    status: str


class SopRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    department: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=20000)

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title cannot be empty")
        return v


class SopAccessRequest(BaseModel):
    action: str
    department: str = Field(min_length=1, max_length=100)
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("action")
    @classmethod
    def _valid_action(cls, v: str) -> str:
        if v not in ("create", "edit"):
            raise ValueError("Action must be 'create' or 'edit'")
        return v


class SopAccessRequestResponse(BaseModel):
    id: int
    status: str


def _require_staff(user: dict) -> None:
    """Reject client tokens on staff-only endpoints."""
    if user.get("audience") == "client":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client accounts cannot access staff endpoints",
        )


def _user_departments(user: dict) -> list[str]:
    """Full department scope for a staff member (own + allowed)."""
    depts = {user.get("department", "general")}
    depts.update(user.get("allowed_departments") or [])
    return list(depts)


def _assigned_client_ids(cur, user: dict) -> list[int] | None:
    """Assigned client ids, or None when the user is an admin (all clients)."""
    if is_admin(user):
        return None
    cur.execute(
        "SELECT client_id FROM staff_client_assignments WHERE user_id = %s",
        (user["id"],),
    )
    return [r["client_id"] for r in cur.fetchall()]


def _assert_case_access(user: dict, case_id: int) -> None:
    """403/404 unless the user is admin or assigned to the case's client."""
    if is_admin(user):
        return
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM cases c "
                "JOIN staff_client_assignments sca ON sca.client_id = c.client_id "
                "WHERE c.id = %s AND sca.user_id = %s AND c.is_active = true",
                (case_id, user["id"]),
            )
            allowed = cur.fetchone()
    if allowed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found or not assigned to you",
        )


def _assert_sop_author(user: dict) -> None:
    """Raise 403 unless admin or the user has an approved SOP-access request."""
    if is_admin(user):
        return
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM sop_access_requests "
                "WHERE user_id = %s AND status = 'approved' LIMIT 1",
                (user["id"],),
            )
            approved = cur.fetchone()
    if approved is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Approved SOP access request required to author SOPs",
        )


@router.get("/dashboard")
async def staff_dashboard(user: dict = Depends(require_auth)) -> dict:
    """One-call dashboard: assigned cases, dept workflows, dept SOPs."""
    _require_staff(user)
    depts = _user_departments(user)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            assigned = _assigned_client_ids(cur, user)

            # Cases for assigned clients (admin: all).
            if assigned is None:
                cur.execute(
                    "SELECT c.id, c.case_number, c.client_id, c.loan_amount, "
                    "c.status, c.created_at, cl.full_name AS client_name, "
                    "p.address, p.city, p.state "
                    "FROM cases c "
                    "JOIN clients cl ON cl.id = c.client_id "
                    "LEFT JOIN properties p ON p.id = c.property_id "
                    "WHERE c.is_active = true ORDER BY c.id"
                )
            elif assigned:
                cur.execute(
                    "SELECT c.id, c.case_number, c.client_id, c.loan_amount, "
                    "c.status, c.created_at, cl.full_name AS client_name, "
                    "p.address, p.city, p.state "
                    "FROM cases c "
                    "JOIN clients cl ON cl.id = c.client_id "
                    "LEFT JOIN properties p ON p.id = c.property_id "
                    "WHERE c.is_active = true AND c.client_id = ANY(%s) "
                    "ORDER BY c.id",
                    (assigned,),
                )
            else:
                cur.execute("SELECT * FROM cases WHERE false")
            cases = [dict(row) for row in cur.fetchall()]

            # Active workflows for the staff member's departments (admin: all).
            if is_admin(user):
                cur.execute(
                    "SELECT w.*, ca.case_number FROM workflows w "
                    "LEFT JOIN cases ca ON ca.id = w.case_id "
                    "WHERE w.status <> 'done' ORDER BY w.updated_at DESC"
                )
            else:
                cur.execute(
                    "SELECT w.*, ca.case_number FROM workflows w "
                    "LEFT JOIN cases ca ON ca.id = w.case_id "
                    "WHERE w.department = ANY(%s) AND w.status <> 'done' "
                    "ORDER BY w.updated_at DESC",
                    (depts,),
                )
            workflows = [dict(row) for row in cur.fetchall()]

            # SOPs for the staff member's departments (admin: all).
            if is_admin(user):
                cur.execute(
                    "SELECT * FROM sops WHERE is_active = true "
                    "ORDER BY updated_at DESC"
                )
            else:
                cur.execute(
                    "SELECT * FROM sops WHERE is_active = true "
                    "AND department = ANY(%s) ORDER BY updated_at DESC",
                    (depts,),
                )
            sops = [dict(row) for row in cur.fetchall()]

            # Whether the user may author SOPs.
            cur.execute(
                "SELECT 1 FROM sop_access_requests "
                "WHERE user_id = %s AND status = 'approved' LIMIT 1",
                (user["id"],),
            )
            sop_access = cur.fetchone() is not None

    return {
        "cases": [dict(r) for r in cases],
        "workflows": [workflow_row_to_dict(dict(r)) for r in workflows],
        "sops": [sop_row_to_dict(dict(r)) for r in sops],
        "sop_access": sop_access or is_admin(user),
    }


# ---------------------------------------------------------------------------
# Case collaboration notes
# ---------------------------------------------------------------------------


@router.get("/cases/{case_id}/notes")
async def list_case_notes(
    case_id: int,
    user: dict = Depends(require_auth),
) -> dict:
    """Return collaboration notes for a case the user can access."""
    _require_staff(user)
    _assert_case_access(user, case_id)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT n.id, n.case_id, n.user_id, n.body, n.created_at, "
                "u.full_name AS author_name "
                "FROM case_notes n JOIN users u ON u.id = n.user_id "
                "WHERE n.case_id = %s ORDER BY n.created_at ASC, n.id ASC",
                (case_id,),
            )
            notes = [dict(row) for row in cur.fetchall()]
    return {"notes": [case_note_row_to_dict(dict(r)) for r in notes]}


@router.post("/cases/{case_id}/notes", status_code=status.HTTP_201_CREATED)
async def add_case_note(
    case_id: int,
    request: NoteRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """Add a collaboration note to a case the user can access."""
    _require_staff(user)
    _assert_case_access(user, case_id)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO case_notes (case_id, user_id, body) "
                "VALUES (%s, %s, %s) RETURNING id, case_id, user_id, body, created_at",
                (case_id, user["id"], request.body),
            )
            note = dict(cur.fetchone())
        conn.commit()
    return {"note": case_note_row_to_dict({**note, "author_name": user.get("full_name")})}


# ---------------------------------------------------------------------------
# Workflow triggers
# ---------------------------------------------------------------------------

WORKFLOW_STAGES = {"in_progress": "review", "review": "done", "done": "done"}


@router.post("/workflows/{workflow_id}/advance")
async def advance_workflow(
    workflow_id: int,
    user: dict = Depends(require_auth),
) -> WorkflowAdvanceResponse:
    """Advance a workflow one stage: in_progress â†’ review â†’ done.

    Only staff whose department scope includes the workflow's department
    (or admins) may trigger the transition.
    """
    _require_staff(user)
    depts = _user_departments(user)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            if is_admin(user):
                cur.execute(
                    "SELECT id, status FROM workflows WHERE id = %s",
                    (workflow_id,),
                )
            else:
                cur.execute(
                    "SELECT id, status FROM workflows "
                    "WHERE id = %s AND department = ANY(%s)",
                    (workflow_id, depts),
                )
            row = cur.fetchone()

            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Workflow not found",
                )

            next_status = WORKFLOW_STAGES[row["status"]]
            if next_status == row["status"]:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Workflow is already complete",
                )

            cur.execute(
                "UPDATE workflows SET status = %s, updated_at = now() WHERE id = %s",
                (next_status, workflow_id),
            )
        conn.commit()

    return WorkflowAdvanceResponse(workflow_id=workflow_id, status=next_status)


# ---------------------------------------------------------------------------
# SOPs (view for all staff; authoring requires an approved request)
# ---------------------------------------------------------------------------


@router.get("/sops")
async def list_sops(user: dict = Depends(require_auth)) -> dict:
    """List SOPs scoped to the staff member's departments (admin: all)."""
    _require_staff(user)
    depts = _user_departments(user)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            if is_admin(user):
                cur.execute(
                    "SELECT * FROM sops WHERE is_active = true "
                    "ORDER BY updated_at DESC"
                )
            else:
                cur.execute(
                    "SELECT * FROM sops WHERE is_active = true "
                    "AND department = ANY(%s) ORDER BY updated_at DESC",
                    (depts,),
                )
            sops = [dict(row) for row in cur.fetchall()]
    return {"sops": [sop_row_to_dict(dict(r)) for r in sops]}


@router.post("/sops", status_code=status.HTTP_201_CREATED)
async def create_sop(
    request: SopRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """Create an SOP. Requires an approved SOP-access request or admin."""
    _require_staff(user)
    _assert_sop_author(user)
    if not is_admin(user):
        _assert_department_in_scope(user, request.department)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sops (title, department, body, version, created_by) "
                "VALUES (%s, %s, %s, 1, %s) RETURNING id",
                (request.title, request.department, request.body, user["id"]),
            )
            new_id = cur.fetchone()["id"]
        conn.commit()
    return {"message": "SOP created", "sop_id": new_id}


@router.put("/sops/{sop_id}")
async def update_sop(
    sop_id: int,
    request: SopRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """Edit an SOP, bumping its version. Requires approved request or admin."""
    _require_staff(user)
    _assert_sop_author(user)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            if is_admin(user):
                cur.execute(
                    "SELECT id, department, version FROM sops WHERE id = %s AND is_active = true",
                    (sop_id,),
                )
            else:
                cur.execute(
                    "SELECT id, department, version FROM sops "
                    "WHERE id = %s AND is_active = true AND department = ANY(%s)",
                    (sop_id, _user_departments(user)),
                )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="SOP not found",
                )
            if not is_admin(user):
                _assert_department_in_scope(user, request.department)

            cur.execute(
                "UPDATE sops SET title = %s, department = %s, body = %s, "
                "version = %s, updated_at = now() WHERE id = %s",
                (
                    request.title,
                    request.department,
                    request.body,
                    row["version"] + 1,
                    sop_id,
                ),
            )
        conn.commit()
    return {"message": "SOP updated", "sop_id": sop_id}


def _assert_department_in_scope(user: dict, department: str) -> None:
    """Raise 403 unless the department is within the staff member's scope."""
    if department not in _user_departments(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cannot author SOPs for department '{department}'",
        )


# ---------------------------------------------------------------------------
# SOP access requests
# ---------------------------------------------------------------------------


@router.get("/sop-access-requests")
async def list_my_sop_requests(user: dict = Depends(require_auth)) -> dict:
    """Return the staff member's own SOP-access requests."""
    _require_staff(user)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM sop_access_requests WHERE user_id = %s "
                "ORDER BY created_at DESC",
                (user["id"],),
            )
            requests = [dict(row) for row in cur.fetchall()]
    return {"requests": [sop_request_row_to_dict(dict(r)) for r in requests]}


@router.post("/sop-access-requests", status_code=status.HTTP_201_CREATED)
async def create_sop_access_request(
    request: SopAccessRequest,
    user: dict = Depends(require_auth),
) -> SopAccessRequestResponse:
    """Request permission to create/edit SOPs. Admins review it."""
    _require_staff(user)
    if is_admin(user):
        return SopAccessRequestResponse(id=0, status="approved")
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM sop_access_requests "
                "WHERE user_id = %s AND action = %s AND department = %s "
                "AND status = 'pending' LIMIT 1",
                (user["id"], request.action, request.department),
            )
            if cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A pending request for this action already exists",
                )
            cur.execute(
                "INSERT INTO sop_access_requests (user_id, action, department, reason) "
                "VALUES (%s, %s, %s, %s) RETURNING id, status",
                (user["id"], request.action, request.department, request.reason),
            )
            row = dict(cur.fetchone())
        conn.commit()
    return SopAccessRequestResponse(id=row["id"], status=row["status"])
