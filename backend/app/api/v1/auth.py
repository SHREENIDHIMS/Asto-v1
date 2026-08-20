"""Auth endpoints (JWT login, verification).

Password storage: bcrypt via passlib. This is the production-grade
password hashing scheme â€” resistant to brute-force and GPU-accelerated
cracking attacks.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.hash import bcrypt
from pydantic import BaseModel, field_validator


from app.auth.jwt_handler import (
    create_2fa_token,
    create_token,
    hash_refresh_token,
    hash_token,
    new_refresh_token,
    verify_token,
)
from app.auth.password_reset_email import deliver_reset_link
from app.config import settings
from app.db.postgres import session
from app.dependencies import require_auth

# Real bcrypt hash of a sentinel string. When the submitted email has no
# account, we still pay one bcrypt.verify so that a wrong-password attempt on
# a real account and an attempt on an unknown account take the same time —
# otherwise login timing leaks which emails exist (account enumeration).
_DUMMY_BCRYPT_HASH = "$2b$12$uNyIa5XiTx962SSR.iYDueKFtoyonhYy0ZO2HGW6Z17SK.0NAmjh."

router = APIRouter()

bearer_scheme = HTTPBearer(auto_error=False)


# CSRF protection for cookie-authenticated endpoints (refresh/logout).
# SameSite=Lax already blocks cross-site POSTs; the custom header is
# defense-in-depth (browsers cannot attach it to cross-origin requests
# without a CORS preflight, which requires an allowed origin).
async def require_csrf(request: Request) -> None:
    if request.headers.get("X-Asto-CSRF") != "1":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF check failed",
        )


# ---------------------------------------------------------------------------
# H3: login-attempt throttle (brute-force protection)
#
# Evidence table `login_attempts` (per-email + per-IP). Before a login is
# attempted, rows older than the prune window are deleted and the recent
# failures are counted in the same transaction; if either counter is at its
# cap the request is rejected with 429. Every failed attempt is recorded;
# a successful login clears the email's failure history (counter reset).
# ---------------------------------------------------------------------------

def _client_ip(request: Request) -> str:
    """Best-effort client IP for throttling.

    Trusts ``X-Real-IP``, which both nginx configs overwrite with
    ``$remote_addr`` (the actual TCP peer), rather than ``X-Forwarded-For``
    whose leftmost hops are client-supplied and spoofable — using them let an
    attacker rotate IPs to dodge the throttle or lock out a victim. Falls back
    to the last XFF hop, then the direct peer (dev direct-to-8011 only).
    """
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if hops:
            return hops[-1]
    return request.client.host if request.client else ""


def _check_login_throttle(cur, email: str, ip: str) -> None:
    """Prune stale attempts, count recent failures, raise 429 when locked out."""
    cur.execute(
        "DELETE FROM login_attempts "
        "WHERE attempted_at < now() - make_interval(hours => %s)",
        (settings.login_attempt_prune_hours,),
    )
    cur.execute(
        "SELECT count(*) FILTER (WHERE email = %s) AS email_fails, "
        "       count(*) FILTER (WHERE ip = %s)    AS ip_fails "
        "FROM login_attempts WHERE success = false "
        "AND attempted_at >= now() - make_interval(mins => %s)",
        (email, ip, settings.login_lockout_minutes),
    )
    row = cur.fetchone()
    email_fails = row["email_fails"] if row else 0
    ip_fails = row["ip_fails"] if row else 0

    if email_fails >= settings.login_max_failures or ip_fails >= settings.login_max_ip_failures:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts. Try again later.",
            headers={"Retry-After": str(settings.login_lockout_minutes * 60),
                     "X-RateLimit-Limit": str(settings.login_max_failures),
                     "X-RateLimit-Remaining": "0"},
        )


def _record_failed_attempt(cur, email: str, ip: str) -> None:
    """Record one failed login attempt (the counter the throttle counts)."""
    cur.execute(
        "INSERT INTO login_attempts (email, ip, success) VALUES (%s, %s, false)",
        (email, ip),
    )


def _reset_attempts(cur, email: str) -> None:
    """Clear a successful login's failure history (counter reset)."""
    cur.execute("DELETE FROM login_attempts WHERE email = %s", (email,))


# Password-reset requests are throttled per source IP only, using a sentinel
# email so they can never count toward a real account's login lockout — an
# attacker must not be able to lock a victim out of /login by spamming the
# reset endpoint (lockout-DoS).
_RESET_SENTINEL_EMAIL = "__password_reset__"


def _check_reset_throttle(cur, ip: str) -> None:
    """Prune stale attempts and raise 429 when this IP has spammed resets."""
    if not ip:
        return
    cur.execute(
        "DELETE FROM login_attempts "
        "WHERE attempted_at < now() - make_interval(hours => %s)",
        (settings.login_attempt_prune_hours,),
    )
    cur.execute(
        "SELECT count(*) AS ip_fails FROM login_attempts WHERE success = false "
        "AND ip = %s AND attempted_at >= now() - make_interval(mins => %s)",
        (ip, settings.login_lockout_minutes),
    )
    row = cur.fetchone()
    ip_fails = row["ip_fails"] if row else 0
    if ip_fails >= settings.login_max_ip_failures:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Try again later.",
            headers={"Retry-After": str(settings.login_lockout_minutes * 60)},
        )


def _record_reset_attempt(cur, ip: str) -> None:
    """Record one reset request so per-IP floods are pruned and counted."""
    if not ip:
        return
    cur.execute(
        "INSERT INTO login_attempts (email, ip, success) "
        "VALUES (%s, %s, false)",
        (_RESET_SENTINEL_EMAIL, ip),
    )


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    expires_in: int = 0
    # H4: present when the account has 2FA enabled. The caller must exchange
    # ``two_fa_token`` + a TOTP code at /auth/2fa before any real credential
    # is issued (access JWT or the HttpOnly refresh cookie).
    requires_2fa: bool = False
    two_fa_token: str | None = None


class TwoFactorLoginRequest(BaseModel):
    two_fa_token: str
    code: str


class RefreshResponse(BaseModel):
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


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


def _issue_refresh(
    cur,
    audience: str,
    user_id: int | None = None,
    client_id: int | None = None,
) -> str:
    """Insert a hashed refresh-token row and return the raw token for the cookie.

    ``cur`` must belong to a connection the caller commits. The raw token is
    returned once (only ever stored in the HttpOnly cookie); the DB keeps only
    its SHA-256 hash. Rows are soft-revoked on logout/rotation/logout-all.
    """
    token = new_refresh_token()
    expires = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_ttl_days
    )
    if audience == "client":
        cur.execute(
            "INSERT INTO refresh_tokens (token_hash, client_id, audience, expires_at) "
            "VALUES (%s, %s, 'client', %s)",
            (hash_refresh_token(token), client_id, expires),
        )
    else:
        cur.execute(
            "INSERT INTO refresh_tokens (token_hash, user_id, audience, expires_at) "
            "VALUES (%s, %s, 'staff', %s)",
            (hash_refresh_token(token), user_id, expires),
        )
    return token


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.refresh_token_ttl_days * 24 * 3600,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(settings.auth_cookie_name, path="/")


def _access_token_for(audience: str, user_id: int | None, client_id: int | None) -> str:
    """Re-issue an access JWT from a refresh-token row's identity."""
    if audience == "client":
        with session.acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, email, full_name FROM clients "
                    "WHERE id = %s AND is_active = true",
                    (client_id,),
                )
                row = cur.fetchone()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Client not found or inactive",
            )
        return create_token(
            subject=str(row["id"]),
            role="client",
            audience="client",
            client_id=int(row["id"]),
            name=row["full_name"] or row["email"],
        )

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, full_name, role, department, allowed_departments "
                "FROM users WHERE id = %s AND is_active = true",
                (user_id,),
            )
            row = cur.fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return create_token(
        subject=str(row["id"]),
        role=row["role"],
        department=row["department"],
        allowed_departments=list(row["allowed_departments"] or []),
        audience="staff",
        name=row["full_name"] or row["email"],
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    response: Response,
    http_request: Request,
) -> LoginResponse:
    """Authenticate with email + password, return a JWT.

    Single sign-in for both audiences: resolves the identity from the
    ``users`` table first (staff), then the ``clients`` table (external
    clients), so the frontend needs no Staff/Client selector. The JWT is
    scoped by the resolved audience (staff -> role/department claims,
    client -> audience="client" + client_id) and the client is routed by
    those claims after login.

    In addition to the short-lived access JWT in the JSON body (kept in
    memory client-side), a long-lived refresh token is issued and stored in
    an HttpOnly ``asto_refresh`` cookie (H1). The cookie survives page
    reloads and is rotated on every refresh/logout.

    Brute-force throttling (H3): every attempt is recorded to
    ``login_attempts``; 5 recent failures for the email (or 10 for the IP)
    reject with 429 and a Retry-After header. Success clears the counter.

    Admin 2FA (H4): when the resolved staff account has TOTP enabled, no
    credential is issued yet. The response carries ``requires_2fa`` + a
    short-lived, single-use ``two_fa_token``; the caller must complete
    POST /auth/2fa with a valid TOTP code to receive the access JWT and
    the refresh cookie.
    """
    ip = _client_ip(http_request)
    refresh: str | None = None
    requires_2fa: bool = False
    two_fa_token: str | None = None
    with session.acquire() as conn:
        with conn.cursor() as cur:
            _check_login_throttle(cur, request.email, ip)

            cur.execute(
                "SELECT id, email, password_hash, role, department, "
                "full_name, allowed_departments, totp_enabled FROM users "
                "WHERE email = %s AND is_active = true",
                (request.email,),
            )
            row = cur.fetchone()

            token = None
            if row is not None:
                staff_password_ok = bcrypt.verify(
                    request.password, row["password_hash"]
                )
            else:
                # No staff account: still burn one bcrypt verify so timing
                # cannot distinguish "no account" from "wrong password".
                bcrypt.verify(request.password, _DUMMY_BCRYPT_HASH)
                staff_password_ok = False

            if staff_password_ok:
                if row["totp_enabled"]:
                    # Correct password but 2FA is on: no credentials yet.
                    requires_2fa = True
                    two_fa_token = create_2fa_token(
                        str(row["id"]),
                        settings.two_fa_token_ttl_minutes,
                    )
                else:
                    token = create_token(
                        subject=str(row["id"]),
                        role=row["role"],
                        department=row["department"],
                        allowed_departments=list(row["allowed_departments"] or []),
                        audience="staff",
                        name=row["full_name"] or row["email"],
                    )
                    refresh = _issue_refresh(cur, "staff", user_id=int(row["id"]))
                    _reset_attempts(cur, request.email)

            if token is None and not requires_2fa:
                cur.execute(
                    "SELECT id, email, password_hash, full_name FROM clients "
                    "WHERE email = %s AND is_active = true",
                    (request.email,),
                )
                row = cur.fetchone()
                if row is not None:
                    client_password_ok = bcrypt.verify(
                        request.password, row["password_hash"]
                    )
                else:
                    bcrypt.verify(request.password, _DUMMY_BCRYPT_HASH)
                    client_password_ok = False
                if client_password_ok:
                    token = create_token(
                        subject=str(row["id"]),
                        role="client",
                        audience="client",
                        client_id=int(row["id"]),
                        name=row["full_name"] or row["email"],
                    )
                    refresh = _issue_refresh(cur, "client", client_id=int(row["id"]))
                    _reset_attempts(cur, request.email)

            if token is None and not requires_2fa:
                _record_failed_attempt(cur, request.email, ip)
        conn.commit()

    if requires_2fa:
        return LoginResponse(
            requires_2fa=True,
            two_fa_token=two_fa_token,
        )

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    _set_refresh_cookie(response, refresh)
    return LoginResponse(
        access_token=token,
        expires_in=settings.jwt_expiry_minutes * 60,
    )


@router.post("/2fa", response_model=LoginResponse)
async def two_factor_login(
    request: TwoFactorLoginRequest,
    response: Response,
    http_request: Request,
) -> LoginResponse:
    """Complete an H4 2FA login: swap the short-lived token + TOTP code for real credentials.

    The ``two_fa_token`` from /auth/login is verified (purpose=2fa, unexpired,
    not already consumed). The account's stored TOTP secret is decrypted and
    the presented code checked with a ±1-window tolerance. On success the
    token's jti is recorded in ``revoked_jtis`` (single-use), the refresh
    cookie is issued, and a real access JWT returned. Wrong code -> 401.
    """
    payload = verify_token(request.two_fa_token)
    if payload is None or payload.get("purpose") != "2fa":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired 2FA token",
        )

    subject = payload.get("sub")
    if subject is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid 2FA token: missing subject",
        )

    ip = _client_ip(http_request)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            # Single-use: a consumed jti must be rejected even inside its TTL.
            if payload.get("jti"):
                cur.execute("SELECT 1 FROM revoked_jtis WHERE jti = %s", (payload["jti"],))
                if cur.fetchone() is not None:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="2FA token already used",
                    )

            cur.execute(
                "SELECT id, email, full_name, role, department, "
                "allowed_departments, totp_secret, totp_enabled FROM users "
                "WHERE id = %s AND is_active = true",
                (subject,),
            )
            row = cur.fetchone()

            if row is None or not row["totp_enabled"]:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="2FA not enabled for this account",
                )

            # TOTP brute-force guard: 6-digit codes are guessable, so run the
            # same H3 throttle here (failures are already recorded below).
            _check_login_throttle(cur, row["email"], ip)

            from app.auth.totp import decrypt_secret, verify_code

            secret = decrypt_secret(row["totp_secret"])
            if secret is None or not verify_code(secret, request.code):
                _record_failed_attempt(cur, row["email"], ip)
                conn.commit()
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid 2FA code",
                )

            # Consume the token (single-use) and issue real credentials.
            if payload.get("jti"):
                cur.execute(
                    "INSERT INTO revoked_jtis (jti) VALUES (%s) ON CONFLICT (jti) DO NOTHING",
                    (payload["jti"],),
                )
            token = create_token(
                subject=str(row["id"]),
                role=row["role"],
                department=row["department"],
                allowed_departments=list(row["allowed_departments"] or []),
                audience="staff",
                name=row["full_name"] or row["email"],
            )
            refresh = _issue_refresh(cur, "staff", user_id=int(row["id"]))
            _reset_attempts(cur, row["email"])
        conn.commit()

    _set_refresh_cookie(response, refresh)
    return LoginResponse(
        access_token=token,
        expires_in=settings.jwt_expiry_minutes * 60,
    )


@router.post("/client-login", response_model=LoginResponse)
async def client_login(
    request: LoginRequest,
    response: Response,
    http_request: Request,
) -> LoginResponse:
    """Authenticate an external client (clients table), return a JWT.

    The client token is tagged audience="client" with their client_id so
    search is scoped to their own documents at the SQL WHERE clause. Legacy
    endpoint kept for backward compatibility; also sets the HttpOnly
    refresh cookie so cookie sessions work for clients too. Shares the H3
    brute-force throttle with /login.
    """
    ip = _client_ip(http_request)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            _check_login_throttle(cur, request.email, ip)
            cur.execute(
                "SELECT id, email, password_hash, full_name FROM clients "
                "WHERE email = %s AND is_active = true",
                (request.email,),
            )
            row = cur.fetchone()

            if row is not None:
                password_ok = bcrypt.verify(request.password, row["password_hash"])
            else:
                # Unknown account: burn the same bcrypt cost so timing does
                # not reveal whether the email exists.
                bcrypt.verify(request.password, _DUMMY_BCRYPT_HASH)
                password_ok = False

            if not password_ok:
                _record_failed_attempt(cur, request.email, ip)
                conn.commit()
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
            refresh = _issue_refresh(cur, "client", client_id=int(row["id"]))
            _reset_attempts(cur, request.email)
        conn.commit()

    _set_refresh_cookie(response, refresh)
    return LoginResponse(
        access_token=token,
        expires_in=settings.jwt_expiry_minutes * 60,
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(request: Request, response: Response, _: None = Depends(require_csrf)) -> RefreshResponse:
    """Exchange the HttpOnly refresh cookie for a fresh access JWT.

    Rotates the refresh token: the presented token is revoked and a new one
    is issued (same identity), so a stolen token can be used at most once
    and older refresh rows are invalidated on H5 logout-all. Requires the
    ``X-Asto-CSRF: 1`` header (defense-in-depth on top of SameSite=Lax).
    """
    raw = request.cookies.get(settings.auth_cookie_name)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token",
        )

    token_hash = hash_refresh_token(raw)
    now = datetime.now(timezone.utc)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, client_id, audience, expires_at, revoked_at "
                "FROM refresh_tokens WHERE token_hash = %s",
                (token_hash,),
            )
            row = cur.fetchone()

            if row is None or row["revoked_at"] is not None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid refresh token",
                )
            if row["expires_at"] is None or row["expires_at"] < now:
                cur.execute(
                    "UPDATE refresh_tokens SET revoked_at = now() WHERE id = %s",
                    (row["id"],),
                )
                conn.commit()
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Refresh token expired",
                )

            # Rotate in the SAME transaction as the lookup, and only when the
            # presented token is still unrevoked. The rowcount guard closes
            # the replay race: two concurrent uses of one token can no longer
            # both pass the "not revoked" check before either revokes —
            # the loser's UPDATE matches 0 rows and is rejected.
            cur.execute(
                "UPDATE refresh_tokens SET revoked_at = now() "
                "WHERE id = %s AND revoked_at IS NULL",
                (row["id"],),
            )
            if cur.rowcount != 1:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid refresh token",
                )

            new_token = _issue_refresh(
                cur,
                row["audience"],
                user_id=row["user_id"],
                client_id=row["client_id"],
            )
        conn.commit()

    _set_refresh_cookie(response, new_token)
    access = _access_token_for(row["audience"], row["user_id"], row["client_id"])
    return RefreshResponse(
        access_token=access,
        expires_in=settings.jwt_expiry_minutes * 60,
    )


@router.post("/logout")
async def logout(request: Request, response: Response, _: None = Depends(require_csrf)) -> dict:
    """Revoke the presented refresh token and clear the HttpOnly cookie."""
    raw = request.cookies.get(settings.auth_cookie_name)
    _clear_refresh_cookie(response)
    if raw:
        with session.acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE refresh_tokens SET revoked_at = now() "
                    "WHERE token_hash = %s AND revoked_at IS NULL",
                    (hash_refresh_token(raw),),
                )
            conn.commit()
    return {"ok": True}


@router.post("/logout-all")
async def logout_all(user: dict = Depends(require_auth), response: Response = None) -> dict:
    """Revoke every refresh token belonging to the current user/client.

    The caller is authenticated with a bearer access JWT (not the cookie),
    so no CSRF header is required here. Used by the frontend "log out on all
    devices" action and available to admins to kill a user's sessions (H5).

    Also records the caller's access-token ``jti`` in ``revoked_jtis`` so
    the very token used to issue this call dies immediately (H5 emergency
    access-token kill — ``/auth/verify`` refuses revoked jtis).
    """
    _clear_refresh_cookie(response)

    with session.acquire() as conn:
        with conn.cursor() as cur:
            if user.get("jti"):
                cur.execute(
                    "INSERT INTO revoked_jtis (jti) VALUES (%s) ON CONFLICT (jti) DO NOTHING",
                    (user["jti"],),
                )
            if user.get("audience") == "client":
                cur.execute(
                    "UPDATE refresh_tokens SET revoked_at = now() "
                    "WHERE client_id = %s AND revoked_at IS NULL",
                    (user["id"],),
                )
            else:
                cur.execute(
                    "UPDATE refresh_tokens SET revoked_at = now() "
                    "WHERE user_id = %s AND revoked_at IS NULL",
                    (user["id"],),
                )
        conn.commit()
    return {"revoked": True, "audience": user.get("audience", "staff")}


@router.post("/forgot-password")
async def forgot_password(
    request: ForgotPasswordRequest,
    http_request: Request,
) -> dict:
    """Start a password reset for a staff user or client email (H2).

    Returns the same generic body whether or not the email exists,
    so the endpoint cannot be used to enumerate registered accounts.
    When the address resolves to an active user/client, a one-time reset
    token (1h expiry) is stored hashed and a reset link is delivered via
    :func:`deliver_reset_link` (currently the INFO log — DEC-3 mail
    transport pending).

    The reset token's brute-force space is 32 random bytes and the link is
    single-use; the endpoint is throttled per source IP so it can't be used
    to flood a mailbox with reset mail.
    """
    email = request.email.strip().lower()
    ip = _client_ip(http_request)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            _check_reset_throttle(cur, ip)
            _record_reset_attempt(cur, ip)
            cur.execute(
                "SELECT id, email FROM users "
                "WHERE email = %s AND is_active = true",
                (email,),
            )
            row = cur.fetchone()
            if row is not None:
                audience, identity_id, resolved_email = "staff", row["id"], row["email"].lower()
            else:
                cur.execute(
                    "SELECT id, email FROM clients "
                    "WHERE email = %s AND is_active = true",
                    (email,),
                )
                row = cur.fetchone()
                if row is not None:
                    audience, identity_id, resolved_email = "client", row["id"], row["email"].lower()
                else:
                    audience, identity_id, resolved_email = None, None, None

            if audience is not None:
                token = new_refresh_token()
                expires = datetime.now(timezone.utc) + timedelta(
                    hours=settings.password_reset_ttl_hours
                )
                cur.execute(
                    "INSERT INTO password_resets "
                    "(email, audience, identity_id, token_hash, expires_at) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (resolved_email, audience, identity_id, hash_token(token), expires),
                )
                conn.commit()
                deliver_reset_link(
                    resolved_email,
                    f"{settings.frontend_url}/login?reset={token}",
                )
    return {"ok": True, "detail": "If that email is registered, a reset link is on its way"}


@router.post("/reset-password")
async def reset_password(
    request: ResetPasswordRequest,
    http_request: Request,
) -> dict:
    """Set a new password with a one-time reset token (H2).

    The token is looked up by hash, must be unused and unexpired, and is
    consumed on success. The identity table is derived from the token's
    stored audience (never user-supplied), same as /change-password. All of
    the identity's refresh sessions are revoked so a password reset logs
    the account out everywhere at once.

    The endpoint is throttled per source IP with the same sentinel-email
    scheme as /forgot-password so reset tokens cannot be brute-forced; the
    throttle row is committed up front so even invalid-token guesses count
    toward the per-IP cap (they never touch a real account's login lockout).
    """
    token_hash = hash_token(request.token)
    now = datetime.now(timezone.utc)
    ip = _client_ip(http_request)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            _check_reset_throttle(cur, ip)
            _record_reset_attempt(cur, ip)
            # Persist the throttle record immediately: an invalid-token guess
            # below raises before the final commit, which would otherwise
            # roll the counter back and defeat brute-force protection.
            conn.commit()
            cur.execute(
                "SELECT id, audience, identity_id, expires_at FROM password_resets "
                "WHERE token_hash = %s AND used_at IS NULL",
                (token_hash,),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid or already-used reset token",
                )
            if row["expires_at"] is None or row["expires_at"] < now:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Reset token expired",
                )

            table = "clients" if row["audience"] == "client" else "users"
            identity_id = int(row["identity_id"])
            new_hash = bcrypt.hash(request.new_password)
            cur.execute(
                f"UPDATE {table} SET password_hash = %s WHERE id = %s",
                (new_hash, identity_id),
            )
            cur.execute(
                "UPDATE password_resets SET used_at = now() WHERE id = %s",
                (row["id"],),
            )
            if row["audience"] == "client":
                cur.execute(
                    "UPDATE refresh_tokens SET revoked_at = now() "
                    "WHERE client_id = %s AND revoked_at IS NULL",
                    (identity_id,),
                )
            else:
                cur.execute(
                    "UPDATE refresh_tokens SET revoked_at = now() "
                    "WHERE user_id = %s AND revoked_at IS NULL",
                    (identity_id,),
                )
        conn.commit()
    return {"ok": True, "detail": "Password updated; other sessions were signed out"}


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

    # H5: a revoked access-token jti is dead even before natural expiry.
    if payload.get("jti"):
        with session.acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM revoked_jtis WHERE jti = %s",
                    (payload["jti"],),
                )
                if cur.fetchone() is not None:
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
            # Revoke every other live refresh session for this identity so a
            # stolen session dies on password change (H6). The current request
            # carries an access token and keeps working until expiry.
            if table == "clients":
                cur.execute(
                    "UPDATE refresh_tokens SET revoked_at = now() "
                    "WHERE client_id = %s AND audience = 'client' "
                    "AND revoked_at IS NULL",
                    (user_id,),
                )
            else:
                cur.execute(
                    "UPDATE refresh_tokens SET revoked_at = now() "
                    "WHERE user_id = %s AND audience = 'staff' "
                    "AND revoked_at IS NULL",
                    (user_id,),
                )
            conn.commit()
        finally:
            cur.close()

    return ChangePasswordResponse(updated=True)
