"""Email delivery for the password-reset flow (H2).

DEC-3 landed (generic SMTP + console fallback): the reset link is now
delivered through :mod:`app.email.mailer`. With ASTO_SMTP_HOST unset the
mailer logs the link at INFO and the request still succeeds — the whole
flow works locally with no provider. The auth endpoints do not change;
this module remains the single delivery seam.
"""

from __future__ import annotations

import logging

from app.config import settings
from app.email.mailer import send_email

logger = logging.getLogger(__name__)

_SUBJECT = "Reset your Asto password"


def deliver_reset_link(email: str, link: str) -> None:
    """Deliver a one-time password-reset link to the given address."""
    ttl_hours = settings.password_reset_ttl_hours
    text = (
        f"Use this link to reset your Asto password. It expires in "
        f"{ttl_hours} hour(s):\n\n{link}\n\n"
        "If you didn't request this, ignore it."
    )
    html = (
        "<p>Use this link to reset your Asto password. It expires in "
        f"{ttl_hours} hour(s):</p>"
        f'<p><a href="{link}">{link}</a></p>'
        "<p>If you didn't request this, ignore it.</p>"
    )
    send_email(email, _SUBJECT, html, text)
    # Keep a greppable line for local verification WITHOUT the raw link —
    # the one-time reset token must never reach INFO logs/journald (anyone
    # with log access could otherwise reset any account). The link itself is
    # visible via the mailer's console fallback, which redacts the token.
    logger.info("PASSWORD_RESET issued for %s (ttl %s hour(s))", email, ttl_hours)
