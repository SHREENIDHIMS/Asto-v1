"""Client document reminder emails (batch-only).

For every active case, derives the document checklist (K1) and emails each
client the list of outstanding ("pending") items — verbatim requirement
names from ``case_document_requirements``/the seeded defaults. No generated
prose beyond fixed template sentences around the names.

Batch-only by design (rule 5): invoked from ``scripts/document_reminders.py``
behind a systemd timer, never from a request handler. Delivery is
best-effort via the shared mailer (console fallback when SMTP is
unconfigured); failures never raise.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReminderConfig:
    """Knobs for the reminder run (rule 7: configuration, not constants)."""

    subject: str = "Your document checklist needs attention"
    reminder_type: str = "document_reminder"


DEFAULT_REMINDER = ReminderConfig()


def collect_outstanding(conn) -> list[dict]:
    """Group outstanding checklist items per client across their cases.

    Returns one entry per client that has at least one pending item:
    ``{"client_id", "email", "full_name",
       "cases": [{"case_id", "case_number", "missing": [str, ...]}]}``.
    Read-only; the caller owns the transaction.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.id AS case_id, c.case_number, "
            "cl.id AS client_id, cl.email, cl.full_name "
            "FROM cases c "
            "JOIN clients cl ON cl.id = c.client_id "
            "WHERE c.is_active = true AND cl.is_active = true "
            "AND cl.email IS NOT NULL"
        )
        cases = [dict(r) for r in cur.fetchall()]

    from app.documents.requirements import derive_case_checklist

    by_client: dict[int, dict] = {}
    for case in cases:
        checklist = derive_case_checklist(conn, int(case["case_id"]))
        missing = [
            item["name"] for item in checklist if item.get("status") == "pending"
        ]
        if not missing:
            continue
        entry = by_client.setdefault(
            int(case["client_id"]),
            {
                "client_id": int(case["client_id"]),
                "email": case["email"],
                "full_name": case["full_name"],
                "cases": [],
            },
        )
        entry["cases"].append(
            {
                "case_id": int(case["case_id"]),
                "case_number": case["case_number"],
                "missing": missing,
            }
        )
    return list(by_client.values())


def render_reminder(entry: dict, config: ReminderConfig | None = None) -> tuple[str, str, str]:
    """Render one client's reminder as ``(subject, text, html)``."""
    config = config or DEFAULT_REMINDER
    name = entry.get("full_name") or "there"

    lines = [f"Hello {name},", "", "The following documents are still outstanding:"]
    html_parts = [f"<p>Hello {name},</p>", "<p>The following documents are still outstanding:</p>"]

    for case in entry["cases"]:
        header = f"Case {case['case_number']}:"
        lines.append("")
        lines.append(header)
        html_parts.append(f"<p><strong>{header}</strong></p><ul>")
        for item in case["missing"]:
            lines.append(f"  - {item}")
            html_parts.append(f"<li>{item}</li>")
        html_parts.append("</ul>")

    lines.extend(["", "Please upload them through your client portal.", "", "— Asto"])
    html_parts.append('<p>Please upload them through your client portal.</p><p>— Asto</p>')

    return config.subject, "\n".join(lines), "".join(html_parts)


def send_reminders(conn, config: ReminderConfig | None = None) -> dict:
    """Collect outstanding items and email each client. Returns a report.

    Best-effort: uses the shared mailer (never raises). With SMTP
    unconfigured each message is logged to the console instead.
    """
    config = config or DEFAULT_REMINDER
    entries = collect_outstanding(conn)

    from app.email.mailer import send_email

    sent = 0
    for entry in entries:
        subject, text, html = render_reminder(entry, config)
        if send_email(entry["email"], subject, html, text):
            sent += 1

    return {
        "reminder_type": config.reminder_type,
        "clients_with_outstanding": len(entries),
        "emails_sent": sent,
    }
