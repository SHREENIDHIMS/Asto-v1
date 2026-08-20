"""JWT token creation and verification.

Uses HS256 (symmetric) — sufficient for a single-host deployment where
the same backend verifies what the auth endpoint issued. If the API
ever scales to multiple hosts or needs third-party verification, migrate
to RS256 (asymmetric) and add JWKS endpoint support.
"""

from __future__ import annotations

import hashlib
import secrets
import time

import jwt

from app.config import settings


def create_token(
    subject: str,
    role: str = "loan_officer",
    department: str = "general",
    allowed_departments: list[str] | None = None,
    audience: str = "staff",
    client_id: int | None = None,
    name: str | None = None,
) -> str:
    """Create a signed JWT for the given user or client.

    The token carries RBAC-relevant claims used by metadata_filters.py
    at search time: user role, primary department, the full list of
    departments the user may query, the audience ("staff" or "client"),
    and — for the client audience — their own client_id.

    The client_id claim is trusted only for identity; row-level scoping
    is re-resolved from the DB at query time (CLAUDE.md rule #1).
    """
    now = int(time.time())
    payload = {
        "jti": secrets.token_urlsafe(16),
        "sub": subject,
        "role": role,
        "department": department,
        "allowed_departments": allowed_departments or [],
        "audience": audience,
        "iat": now,
        "exp": now + (settings.jwt_expiry_minutes * 60),
    }
    if name:
        payload["name"] = name
    if audience == "client" and client_id is not None:
        payload["client_id"] = client_id
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_token(token: str) -> dict | None:
    """Verify a JWT and return its payload, or None if invalid/expired."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    except Exception:
        return None


def create_2fa_token(subject: str, ttl_minutes: int) -> str:
    """Short-lived, single-use JWT for the 2FA login step (H4).

    Carries ``purpose: "2fa"`` so /auth/2fa cannot be fed a regular access
    JWT, and a fresh ``jti`` that is recorded in ``revoked_jtis`` on use so
    the token can be consumed exactly once.
    """
    now = int(time.time())
    payload = {
        "jti": secrets.token_urlsafe(16),
        "purpose": "2fa",
        "sub": subject,
        "audience": "staff",
        "iat": now,
        "exp": now + (ttl_minutes * 60),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def new_refresh_token() -> str:
    """Generate an opaque, unguessable refresh token (never a JWT)."""
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """SHA-256 hash of an opaque token, stored in place of the raw value.

    Shared by refresh tokens (H1) and password-reset tokens (H2): only the
    hash is persisted so a database compromise cannot be replayed to
    refresh a session or reset a password. The raw token travels only in
    the HttpOnly cookie or the emailed reset link.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_refresh_token(token: str) -> str:
    """Backwards-compatible alias of :func:`hash_token`."""
    return hash_token(token)
