"""Unit tests for DEC-3 email delivery.

Covers the provider-agnostic SMTP mailer (console fallback when
unconfigured, real SMTP/SSL transports, failure never raising), the H2
password-reset link delivery seam, and the L7 notification→email mirror.
SMTP settings are patched per test; no network is ever touched.
"""

from __future__ import annotations

import smtplib
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from app.api.v1.notifications import notify_user
from app.auth.password_reset_email import deliver_reset_link
from app.config import settings
from app.email.mailer import send_email, smtp_configured


def _enter(patches) -> ExitStack:
    """Enter a list of patches, returning the ExitStack to close them."""
    stack = ExitStack()
    for p in patches:
        stack.enter_context(p)
    return stack


def _unconfigure():
    """Force the mailer into console-fallback mode for a test."""
    return _enter([
        patch.object(settings, "smtp_host", ""),
        patch.object(settings, "smtp_from", ""),
        patch.object(settings, "smtp_user", ""),
        patch.object(settings, "smtp_password", ""),
        patch.object(settings, "smtp_port", 587),
        patch.object(settings, "smtp_use_tls", True),
        patch.object(settings, "smtp_use_ssl", False),
    ])


def _configure():
    """Point the mailer at a fake SMTP relay."""
    return _enter([
        patch.object(settings, "smtp_host", "smtp.test.example"),
        patch.object(settings, "smtp_from", "Asto <no-reply@example.com>"),
        patch.object(settings, "smtp_user", "relay-user"),
        patch.object(settings, "smtp_password", "relay-pass"),
        patch.object(settings, "smtp_port", 587),
        patch.object(settings, "smtp_use_tls", True),
        patch.object(settings, "smtp_use_ssl", False),
    ])


class TestSmtpConfigured:
    def test_true_when_host_and_from_set(self):
        with _configure():
            assert smtp_configured() is True

    def test_false_when_host_empty(self):
        with _unconfigure():
            assert smtp_configured() is False


class TestSendEmail:
    def test_console_fallback_when_unconfigured(self, caplog):
        with _unconfigure():
            with caplog.at_level("INFO", logger="app.email.mailer"):
                ok = send_email("a@b.c", "Subject", "<p>hi</p>", "hi")
        assert ok is False
        assert "console fallback" in caplog.text
        assert "a@b.c" in caplog.text

    def test_smtp_success_returns_true(self):
        with _configure():
            smtp = MagicMock()
            smtp.__enter__ = MagicMock(return_value=smtp)
            smtp.__exit__ = MagicMock(return_value=False)
            with patch("app.email.mailer.smtplib.SMTP", return_value=smtp) as cls:
                ok = send_email("a@b.c", "Subject", "<p>hi</p>", "hi")
        assert ok is True
        cls.assert_called_once_with("smtp.test.example", 587, timeout=10)
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with("relay-user", "relay-pass")
        smtp.send_message.assert_called_once()
        subject = smtp.send_message.call_args.args[0]["Subject"]
        assert subject == "Subject"
        assert smtp.send_message.call_args.args[0]["To"] == "a@b.c"

    def test_smtp_ssl_uses_smtp_ssl_transport(self):
        with _configure():
            with patch.object(settings, "smtp_use_ssl", True):
                with patch.object(settings, "smtp_use_tls", False):
                    smtp = MagicMock()
                    smtp.__enter__ = MagicMock(return_value=smtp)
                    smtp.__exit__ = MagicMock(return_value=False)
                    with patch("app.email.mailer.smtplib.SMTP_SSL", return_value=smtp) as cls:
                        ok = send_email("a@b.c", "Subject", "<p>hi</p>", "hi")
        assert ok is True
        cls.assert_called_once_with("smtp.test.example", 587, timeout=10)
        smtp.starttls.assert_not_called()

    def test_failure_falls_back_and_never_raises(self, caplog):
        with _configure():
            with caplog.at_level("INFO", logger="app.email.mailer"):
                with patch("app.email.mailer.smtplib.SMTP", side_effect=smtplib.SMTPException("down")):
                    ok = send_email("a@b.c", "Subject", "<p>hi</p>", "hi")
        assert ok is False
        assert "failed-send fallback" in caplog.text


class TestDeliverResetLink:
    def test_uses_mailer_with_expiry_and_link(self):
        with patch("app.auth.password_reset_email.send_email") as send:
            deliver_reset_link("user@asto.local", "http://localhost:3011/reset?token=xyz")
        send.assert_called_once()
        to, subject, html, text = send.call_args.args
        assert to == "user@asto.local"
        assert subject == "Reset your Asto password"
        assert "http://localhost:3011/reset?token=xyz" in html
        assert "http://localhost:3011/reset?token=xyz" in text


class TestNotificationEmailMirror:
    def _conn_with_email(self, email: str):
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = {"email": email}
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur
        return conn

    def test_emails_recipient_when_smtp_configured(self):
        conn = self._conn_with_email("staff@asto.local")
        with _configure():
            with patch("app.api.v1.notifications.send_email") as send:
                notify_user(conn, 5, "review", "Doc approved", "Body", None)
        send.assert_called_once()
        to, subject, html, text = send.call_args.args
        assert to == "staff@asto.local"
        assert subject == "Doc approved"
        assert "Body" in html and "Body" in text

    def test_includes_link_when_present(self):
        conn = self._conn_with_email("staff@asto.local")
        with _configure():
            with patch("app.api.v1.notifications.send_email") as send:
                notify_user(conn, 5, "review", "Doc approved", "Body", "/docs/9")
        html = send.call_args.args[2]
        text = send.call_args.args[3]
        assert '/docs/9' in html and '/docs/9' in text

    def test_skips_email_when_smtp_unconfigured(self):
        conn = self._conn_with_email("staff@asto.local")
        with _unconfigure():
            with patch("app.api.v1.notifications.send_email") as send:
                notify_user(conn, 5, "review", "Doc approved", "Body", None)
        send.assert_not_called()

    def test_skips_email_when_user_has_no_email(self):
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = None
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur
        with _configure():
            with patch("app.api.v1.notifications.send_email") as send:
                notify_user(conn, 5, "review", "Doc approved", "Body", None)
        send.assert_not_called()
