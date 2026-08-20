"""TOTP (2FA) helpers for admin accounts (Phase H4).

Thin wrapper around ``pyotp`` plus Fernet symmetric encryption for the
secret at rest. The secret is never returned after setup — only the
one-time provisioning URI/secret used by the authenticator app — and the
DB stores ``Fernet(jwt_secret)`` ciphertext, not the plaintext base32 key.

The Fernet key is derived from ``settings.jwt_secret`` (SHA-256). That key
already gates every JWT in the system, so reusing it avoids a second secret
to rotate; a compromise of the app secrets file can decrypt both.
"""

from __future__ import annotations

import base64
import hashlib

import pyotp
from cryptography.fernet import Fernet

from app.config import settings

TOTP_ISSUER: str = "Asto"
TOTP_VALID_WINDOW: int = 1  # ±1 x 30s window tolerates clock drift


def _fernet_key() -> bytes:
    """Deterministic 32-byte url-safe Fernet key derived from jwt_secret."""
    # No fallback: config.py guarantees a strong ASTO_JWT_SECRET in every
    # environment, so the derived key can never degrade to a public constant.
    secret = settings.jwt_secret.encode("utf-8")
    return base64.urlsafe_b64encode(hashlib.sha256(secret).digest())


def _fernet() -> Fernet:
    return Fernet(_fernet_key())


def new_secret() -> str:
    """Generate a new base32 TOTP secret for one-time provisioning."""
    return pyotp.random_base32()


def provisioning_uri(secret: str, email: str) -> str:
    """Build the otpauth:// URI the authenticator app scans or imports."""
    return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name=TOTP_ISSUER)


def verify_code(secret: str, code: str) -> bool:
    """Check a 6-digit code against the secret, tolerating ±1 window."""
    if not code or not code.isdigit():
        return False
    return pyotp.totp.TOTP(secret).verify(code, valid_window=TOTP_VALID_WINDOW)


def current_code(secret: str) -> str:
    """Return the code that is valid right now (used in tests)."""
    return pyotp.totp.TOTP(secret).now()


def encrypt_secret(secret: str) -> str:
    """Encrypt a base32 secret for storage in ``users.totp_secret``."""
    return _fernet().encrypt(secret.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str | None:
    """Decrypt a stored secret; returns None on tampering."""
    if not ciphertext:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except Exception:
        return None
