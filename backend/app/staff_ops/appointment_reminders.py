"""Appointment reminder emails (batch-only).

Finds scheduled appointments starting within the reminder window and
emails the assigned staff member (best-effort via the shared mailer). A
per-appointment cooldown (checked against notification rows tagged with
``metadata.item_id``, same scheme as overdue escalations) keeps daily
timer runs from reminding twice.

Batch-only by design (rule 5): invoked from
``scripts/appointment_reminders.py`` behind a systemd timer, never from a
request handler.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AppointmentReminderConfig:
    """Knobs for the reminder run (rule 7: configuration, not constants)."""

    window_hours: int = 24      # remind for appointments starting within N hours
    cooldown_hours: int = 20    # don't re-remind within this window
    reminder_type: str = "appointment_reminder"


DEFAULT_REMINDER = AppointmentReminderConfig()


def collect_upcoming(conn, config: AppointmentReminderConfig | None = None) -> list[dict]:
    """Scheduled appointments starting inside the reminder window, with
    the assignee's email. Read-only; caller owns the transaction."""
    config = config or DEFAULT_REMINDER
    with conn.cursor() as cur:
        cur.execute(
            "SELECT a.id, a.title, a.description, a.start_at, a.end_at, "
            "a.staff_id, u.email AS staff_email, u.full_name AS staff_name "
            "FROM appointments a LEFT JOIN users u ON u.id = a.staff_id "
            "WHERE a.status = 'scheduled' "
            "AND a.start_at >= now() "
            "AND a.start_at < now() + make_interval(hours => %s)",
            (config.window_hours,),
        )
        return [dict(r) for r in cur.fetchall()]


def _already_reminded(conn, appointment_id: int,
                      config: AppointmentReminderConfig) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM notifications "
            "WHERE type = %s "
            "AND metadata->>'item_id' = %s "
            "AND created_at >= now() - make_interval(hours => %s)",
            (config.reminder_type, str(appointment_id), config.cooldown_hours),
        )
        return int(cur.fetchone()["n"] or 0) > 0


def render_reminder(appt: dict) -> tuple[str, str, str]:
    """Render one appointment reminder as ``(subject, text, html)``."""
    start = appt.get("start_at")
    when = str(start) if start is not None else "scheduled time"
    subject = f"Reminder: {appt['title']}"
    text = (
        f"Hello {appt.get('staff_name') or 'there'},\n\n"
        f"\"{appt['title']}\" starts at {when}.\n"
    )
    html = (
        f"<p>Hello {appt.get('staff_name') or 'there'},</p>"
        f"<p><strong>{appt['title']}</strong> starts at {when}.</p>"
    )
    if appt.get("description"):
        text += f"\n{appt['description']}\n"
        html += f"<p>{appt['description']}</p>"
    text += "\n— Asto"
    html += "<p>— Asto</p>"
    return subject, text, html


def send_reminders(conn, config: AppointmentReminderConfig | None = None) -> dict:
    """Remind staff about upcoming appointments. Caller commits.

    Best-effort delivery via the shared mailer (never raises). Returns
    ``{"upcoming", "reminded"}``.
    """
    config = config or DEFAULT_REMINDER
    upcoming = collect_upcoming(conn, config)

    from app.api.v1.notifications import notify_user
    from app.email.mailer import send_email

    reminded = 0
    for appt in upcoming:
        if appt.get("staff_id") is None:
            continue
        if _already_reminded(conn, int(appt["id"]), config):
            continue

        subject, text, html = render_reminder(appt)
        if appt.get("staff_email"):
            send_email(appt["staff_email"], subject, html, text)

        notify_user(
            conn,
            int(appt["staff_id"]),
            config.reminder_type,
            subject,
            f"\"{appt['title']}\" starts at {appt.get('start_at')}.",
            link="/staff",
        )
        # Tag the row with the appointment id so the cooldown lookup finds it.
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE notifications SET metadata = jsonb_build_object('item_id', %s) "
                "WHERE id = (SELECT MAX(id) FROM notifications "
                "WHERE user_id = %s AND type = %s)",
                (str(appt["id"]), int(appt["staff_id"]), config.reminder_type),
            )
        reminded += 1

    return {"upcoming": len(upcoming), "reminded": reminded}
