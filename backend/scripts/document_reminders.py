"""Client document reminder emails (one-shot batch).

Run via systemd timer (asto-doc-reminders.timer) — deliberately NOT inside
the FastAPI process (rule 5). Emails every active client their outstanding
document checklist items.

Usage:
    python -m scripts.document_reminders
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db.postgres import session
from app.documents.reminders import DEFAULT_REMINDER, ReminderConfig, send_reminders


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Collect and print the reminder plan without sending")
    args = parser.parse_args()

    with session.acquire() as conn:
        if args.dry_run:
            from app.documents.reminders import collect_outstanding

            entries = collect_outstanding(conn)
            for entry in entries:
                print(f"{entry['email']}: "
                      + "; ".join(
                          f"{c['case_number']}: {', '.join(c['missing'])}"
                          for c in entry["cases"]
                      ))
            print(f"{len(entries)} client(s) with outstanding documents")
            return 0

        report = send_reminders(conn, ReminderConfig(subject=DEFAULT_REMINDER.subject))

    print(
        f"Reminders: {report['clients_with_outstanding']} client(s) outstanding, "
        f"{report['emails_sent']} email(s) sent"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
