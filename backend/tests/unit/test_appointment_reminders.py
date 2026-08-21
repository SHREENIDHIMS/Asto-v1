"""Unit tests for appointment reminder emails (batch-only module)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.staff_ops.appointment_reminders import (
    AppointmentReminderConfig,
    collect_upcoming,
    render_reminder,
    send_reminders,
)

APPT = {
    "id": 31,
    "title": "Closing call",
    "description": "Bring the signed disclosure.",
    "start_at": "2026-08-22 10:00",
    "end_at": "2026-08-22 11:00",
    "staff_id": 2,
    "staff_email": "staff@asto.local",
    "staff_name": "Dana Officer",
}


def _conn(rows: list[dict] | None = None) -> MagicMock:
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchall.return_value = rows or []
    cur.fetchone.return_value = {"n": 0}  # cooldown: nothing recent
    return conn


class TestCollectUpcoming:
    def test_window_and_status_in_sql(self):
        conn = _conn()
        collect_upcoming(conn, AppointmentReminderConfig(window_hours=12))
        cur = conn.cursor.return_value.__enter__.return_value
        sql = cur.execute.call_args.args[0]
        assert "status = 'scheduled'" in sql
        assert "make_interval(hours => %s)" in sql
        assert cur.execute.call_args.args[1] == (12,)


class TestRenderReminder:
    def test_includes_title_time_and_description(self):
        subject, text, html = render_reminder(APPT)
        assert "Closing call" in subject
        assert "2026-08-22 10:00" in text
        assert "signed disclosure" in text and "signed disclosure" in html


class TestSendReminders:
    def test_reminds_assigned_staff_once(self):
        conn = _conn([APPT])
        with patch("app.email.mailer.send_email", return_value=True) as mock_send, \
             patch("app.api.v1.notifications.notify_user") as mock_notify:
            report = send_reminders(conn)

        assert report == {"upcoming": 1, "reminded": 1}
        assert mock_send.call_args.args[0] == "staff@asto.local"
        assert mock_notify.call_count == 1
        # Notification row tagged with the appointment id for cooldown.
        cur = conn.cursor.return_value.__enter__.return_value
        tag_calls = [
            c for c in cur.execute.call_args_list
            if "jsonb_build_object" in c.args[0]
        ]
        assert len(tag_calls) == 1
        assert tag_calls[0].args[1][0] == "31"

    def test_cooldown_prevents_double_reminder(self):
        conn = _conn([APPT])
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = {"n": 1}
        with patch("app.email.mailer.send_email", return_value=True) as mock_send, \
             patch("app.api.v1.notifications.notify_user") as mock_notify:
            report = send_reminders(conn)
        assert report["reminded"] == 0
        mock_send.assert_not_called()
        mock_notify.assert_not_called()

    def test_unassigned_appointment_skipped(self):
        conn = _conn([{**APPT, "staff_id": None}])
        with patch("app.email.mailer.send_email", return_value=True) as mock_send, \
             patch("app.api.v1.notifications.notify_user") as mock_notify:
            report = send_reminders(conn)
        assert report["reminded"] == 0
        mock_send.assert_not_called()
        mock_notify.assert_not_called()
