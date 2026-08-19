"""Lightweight, provider-agnostic SMTP mailer (DEC-3).

Any SMTP relay works — Postfix, Amazon SES SMTP, SendGrid, Mailgun, etc. —
configured purely through environment variables (ASTO_SMTP_*). When no SMTP
host is configured the mailer falls back to logging the message at INFO, so
every delivery seam (password reset, notification emails) works in local dev
with no provider at all.

Request-path rule: delivery is best-effort and never raises. A failed send
is logged at ERROR and the message is re-logged at INFO as a fallback, so
the caller's request (e.g. forgot-password) still succeeds when mail is
down. This deliberately keeps SMTP out of the compliance-critical serving
path: no answer content is ever emailed, only auth/notification messages.
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger(__name__)

_SEND_TIMEOUT_S = 10
_FALLBACK_FROM = "Asto <no-reply@asto.local>"


def smtp_configured() -> bool:
    """True when a real SMTP transport is available."""
    return bool(settings.smtp_host and settings.smtp_from)


def send_email(
    to: str,
    subject: str,
    html: str,
    text: str,
) -> bool:
    """Send one email. Returns True on success, False on fallback.

    With SMTP unconfigured (or a failed send), the message is logged at INFO
    and False is returned so callers know delivery was console-only. Never
    raises.
    """
    if not smtp_configured():
        logger.info("EMAIL (console fallback) to=%s subject=%r text=%r", to, subject, text)
        return False

    from_addr = settings.smtp_from or _FALLBACK_FROM
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        if settings.smtp_use_ssl:
            with smtplib.SMTP_SSL(
                settings.smtp_host, settings.smtp_port, timeout=_SEND_TIMEOUT_S
            ) as server:
                server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(
                settings.smtp_host, settings.smtp_port, timeout=_SEND_TIMEOUT_S
            ) as server:
                server.ehlo()
                if settings.smtp_use_tls:
                    server.starttls()
                    server.ehlo()
                if settings.smtp_user:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
    except Exception:
        # Never break the caller's request because mail is down. Re-log the
        # full message so the flow still works in dev/ops.
        logger.exception("EMAIL send failed to=%s subject=%r", to, subject)
        logger.info("EMAIL (failed-send fallback) to=%s subject=%r text=%r", to, subject, text)
        return False

    logger.info("EMAIL sent to=%s subject=%r", to, subject)
    return True
