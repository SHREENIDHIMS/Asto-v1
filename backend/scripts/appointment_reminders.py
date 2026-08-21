"""Appointment reminder emails (one-shot batch).

Run via systemd timer (asto-appointment-reminders.timer) — deliberately
NOT inside the FastAPI process (rule 5). Reminds assigned staff about
appointments starting within the next 24h (per-appointment cooldown).

Usage:
    python -m scripts.appointment_reminders
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db.postgres import session
from app.staff_ops.appointment_reminders import (
    DEFAULT_REMINDER,
    AppointmentReminderConfig,
    send_reminders,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window-hours", type=int, default=DEFAULT_REMINDER.window_hours)
    args = parser.parse_args()

    config = AppointmentReminderConfig(window_hours=args.window_hours)

    with session.acquire() as conn:
        report = send_reminders(conn, config)
        conn.commit()

    print(
        f"Appointment reminders: {report['upcoming']} upcoming, "
        f"{report['reminded']} reminded"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
