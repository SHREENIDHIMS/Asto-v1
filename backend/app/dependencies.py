"""FastAPI dependency injection.

Provides:
- ``get_db`` â€” yields a pooled Postgres connection per request
- ``get_current_user`` â€” extracts and verifies JWT, returns the user row
- ``require_department_access`` â€” RBAC scope resolver from the JWT

Authentication is enforced backend-side. The frontend (static export) has
no server-side auth layer â€” it stores the JWT client-side and sends it
per-request via the Authorization header.
"""

from __future__ import annotations

from typing import Annotated, Optional

import psycopg
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.jwt_handler import verify_token
from app.config import settings
from app.db.postgres import session

bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> psycopg.Connection:
    """Yield a pooled Postgres connection for a single request."""
    with session.acquire() as conn:
        yield conn


async def get_current_user(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(bearer_scheme)] = None,
) -> dict | None:
    """Extract and verify JWT from the Authorization header.

    Resolves identity for BOTH audiences:
    - staff audience â†’ the ``users`` row
    - client audience â†’ the ``clients`` row, tagged ``audience="client"``
      and carrying ``client_id`` so metadata_filters.py can scope search.

    Returns the user dict if valid, None if no token provided
    (callers can decide whether auth is required).
    """
    if credentials is None:
        return None

    token = credentials.credentials
    payload = verify_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    subject = payload.get("sub")
    if subject is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing subject",
            headers={"WWW-Authenticate": "Bearer"},
        )

    audience = payload.get("audience", "staff")
    jti = payload.get("jti")

    if audience == "client":
        with session.acquire() as conn:
            with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                cur.execute(
                    "SELECT id, email, full_name, is_active, "
                    "       (EXISTS (SELECT 1 FROM revoked_jtis WHERE jti = %s)) AS token_revoked "
                    "FROM clients WHERE id = %s AND is_active = true",
                    (jti, subject),
                )
                row = cur.fetchone()

        if row is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Client not found or inactive",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if row["token_revoked"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return {
            **dict(row),
            "audience": "client",
            "client_id": int(row["id"]),
            "role": "client",
            "department": None,
            "allowed_departments": [],
            "jti": jti,
        }

    with session.acquire() as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                "SELECT id, email, full_name, role, department, allowed_departments, is_active, "
                "       (EXISTS (SELECT 1 FROM revoked_jtis WHERE jti = %s)) AS token_revoked "
                "FROM users WHERE id = %s AND is_active = true",
                (jti, subject),
            )
            row = cur.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if row["token_revoked"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {**dict(row), "audience": "staff", "jti": jti}


async def require_auth(
    user: Annotated[dict | None, Depends(get_current_user)] = None,
) -> dict:
    """Dependency that requires a valid authenticated user."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_user_departments(user: dict) -> list[str]:
    """Resolve the full department access scope for a user.

    A user always has access to their own department, plus any
    departments in their allowed_departments list. Used as the RBAC
    pre-filter in the search WHERE clause.
    """
    departments = {user["department"]}
    departments.update(user.get("allowed_departments") or [])
    return list(departments)
