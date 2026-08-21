"""Overdue task/workflow escalation (one-shot batch).

Run via systemd timer (asto-escalate-overdue.timer) — deliberately NOT
inside the FastAPI process (rule 5). Notifies assignees of overdue tasks
and workflows (24h per-item cooldown).

Usage:
    python -m scripts.escalate_overdue
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db.postgres import session
from app.staff_ops.escalation import DEFAULT_ESCALATION, EscalationConfig, run_escalation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cooldown-hours", type=int, default=DEFAULT_ESCALATION.cooldown_hours)
    args = parser.parse_args()

    config = EscalationConfig(cooldown_hours=args.cooldown_hours)

    with session.acquire() as conn:
        report = run_escalation(conn, config)
        conn.commit()

    print(
        f"Escalation: {report['tasks_overdue']} overdue task(s) "
        f"({report['tasks_notified']} notified), "
        f"{report['workflows_overdue']} overdue workflow(s) "
        f"({report['workflows_notified']} notified)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
