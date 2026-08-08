"""Admin endpoints for user and client management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from passlib.hash import bcrypt
from pydantic import BaseModel

from app.auth.permissions import require_role
from app.dependencies import require_auth
from app.db.postgres.session import acquire

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

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, full_name, role, department, allowed_departments, "
                "is_active, created_at FROM users ORDER BY id"
            )
            users = [dict(row) for row in cur.fetchall()]

    return {"users": users}


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    request: CreateUserRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """Create a staff user. Requires admin role."""
    require_role(user, "admin")

    with acquire() as conn:
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

    with acquire() as conn:
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

    with acquire() as conn:
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

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO staff_client_assignments (user_id, client_id) "
                "VALUES (%s, %s) "
                "ON CONFLICT (user_id, client_id) DO NOTHING",
                (request.user_id, request.client_id),
            )
        conn.commit()

    return {"message": "Staff assigned to client"}
