"""Auth endpoints (JWT login, verification).

Password storage: bcrypt via passlib. This is the production-grade
password hashing scheme â€” resistant to brute-force and GPU-accelerated
cracking attacks.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.hash import bcrypt
from pydantic import BaseModel, field_validator


from app.auth.jwt_handler import create_token, verify_token
from app.config import settings
from app.db.postgres import session
from app.dependencies import require_auth

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


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class ChangePasswordResponse(BaseModel):
    updated: bool


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest) -> LoginResponse:
    """Authenticate with email + password, return a JWT.

    Single sign-in for both audiences: resolves the identity from the
    ``users`` table first (staff), then the ``clients`` table (external
    clients), so the frontend needs no Staff/Client selector. The JWT is
    scoped by the resolved audience (staff -> role/department claims,
    client -> audience="client" + client_id) and the client is routed by
    those claims after login.

    An email present in both tables resolves as staff (deterministic).
    A failed match on both tables raises a single generic 401 so the
    response does not reveal which table an email belongs to.
    """
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, password_hash, role, department, "
                "allowed_departments FROM users "
                "WHERE email = %s AND is_active = true",
                (request.email,),
            )
            row = cur.fetchone()

    if row is not None and bcrypt.verify(request.password, row["password_hash"]):
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

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, password_hash FROM clients "
                "WHERE email = %s AND is_active = true",
                (request.email,),
            )
            row = cur.fetchone()

    if row is not None and bcrypt.verify(request.password, row["password_hash"]):
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

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
    )


@router.post("/client-login", response_model=LoginResponse)
async def client_login(request: LoginRequest) -> LoginResponse:
    """Authenticate an external client (clients table), return a JWT.

    The client token is tagged audience="client" with their client_id so
    search is scoped to their own documents at the SQL WHERE clause.
    """
    with session.acquire() as conn:
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


@router.post("/change-password", response_model=ChangePasswordResponse)
async def change_password(
    request: ChangePasswordRequest,
    user: dict = Depends(require_auth),
) -> ChangePasswordResponse:
    """Change the password for the currently authenticated user/client.

    The identity table is resolved from the verified JWT audience
    (staff -> ``users``, client -> ``clients``). The table name is never
    user-supplied, so interpolating it here is safe.
    """
    table = "clients" if user.get("audience") == "client" else "users"
    user_id = int(user["id"])

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT password_hash FROM {table} WHERE id = %s",
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

        new_hash = bcrypt.hash(request.new_password)
        cur = conn.cursor()
        try:
            cur.execute(
                f"UPDATE {table} SET password_hash = %s WHERE id = %s",
                (new_hash, user_id),
            )
            conn.commit()
        finally:
            cur.close()

    return ChangePasswordResponse(updated=True)
