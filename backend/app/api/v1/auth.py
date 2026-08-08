"""Auth endpoints (JWT login, verification).

Password storage: bcrypt via passlib. This is the production-grade
password hashing scheme — resistant to brute-force and GPU-accelerated
cracking attacks.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.hash import bcrypt
from pydantic import BaseModel

from app.auth.jwt_handler import create_token, verify_token
from app.config import settings
from app.db.postgres.session import acquire

router = APIRouter()

bearer_scheme = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenVerifyResponse(BaseModel):
    valid: bool
    user_id: int | None = None
    email: str | None = None


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest) -> LoginResponse:
    """Authenticate with email + password, return a JWT."""
    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, password_hash, role, department, "
                "allowed_departments FROM users "
                "WHERE email = %s AND is_active = true",
                (request.email,),
            )
            row = cur.fetchone()

    if row is None or not bcrypt.verify(request.password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    token = create_token(
        subject=str(row["id"]),
        role=row["role"],
        department=row["department"],
        allowed_departments=list(row["allowed_departments"] or []),
        audience="staff",
    )

    return LoginResponse(
        access_token=token,
        expires_in=settings.jwt_expiry_minutes * 60,
    )


@router.post("/client-login", response_model=LoginResponse)
async def client_login(request: LoginRequest) -> LoginResponse:
    """Authenticate an external client (clients table), return a JWT.

    The client token is tagged audience="client" with their client_id so
    search is scoped to their own documents at the SQL WHERE clause.
    """
    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, password_hash, full_name FROM clients "
                "WHERE email = %s AND is_active = true",
                (request.email,),
            )
            row = cur.fetchone()

    if row is None or not bcrypt.verify(request.password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    token = create_token(
        subject=str(row["id"]),
        role="client",
        audience="client",
        client_id=int(row["id"]),
    )

    return LoginResponse(
        access_token=token,
        expires_in=settings.jwt_expiry_minutes * 60,
    )


@router.post("/verify", response_model=TokenVerifyResponse)
async def verify(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> TokenVerifyResponse:
    """Verify a bearer JWT token's validity."""
    if credentials is None:
        return TokenVerifyResponse(valid=False)

    payload = verify_token(credentials.credentials)
    if payload is None:
        return TokenVerifyResponse(valid=False)

    return TokenVerifyResponse(
        valid=True,
        user_id=int(payload["sub"]) if payload.get("sub") else None,
        email=payload.get("email"),
    )
