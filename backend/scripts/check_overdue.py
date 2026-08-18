#!/usr/bin/env python3
"""L3: Overdue / SLA detection batch job.

Scans workflows that are in_progress or review with a due_at timestamp
that has passed, marks them as overdue, and creates notifications.

Run via: python -m scripts.check_overdue
or systemd: asto-overdue.service

Deliberately stays out of the FastAPI request path (CLAUDE.md rule 5).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# This script lives in backend/scripts/
# __file__ resolves to the script location
# parent.parent = backend directory (two levels up from scripts/)
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from backend.app.db.postgres.session import acquire


def mark_overdue():
    """Mark overdue workflows and create notifications."""
    with acquire() as conn:
        with conn.cursor() as cur:
            # Find workflows that are in_progress or review and have passed due_at
            cur.execute(
                """
                SELECT w.id, w.title, w.department, w.assigned_to, w.case_id,
                       c.client_id
                FROM workflows w
                LEFT JOIN cases c ON c.id = w.case_id
                WHERE w.status IN ('in_progress', 'review')
                  AND w.due_at IS NOT NULL
                  AND w.due_at < NOW()
                """
            )
            overdue = cur.fetchall()

            for w in overdue:
                wid, title, dept, assigned_to, case_id, client_id = w

                # Check if already marked overdue (avoid duplicate notifications)
                # Use the metadata column we added to notifications table
                cur.execute(
                    "SELECT 1 FROM notifications WHERE metadata->>'type' = %s "
                    "AND metadata->>'workflow_id' = %s LIMIT 1",
                    ("workflow_overdue", str(wid)),
                )
                if cur.fetchone():
                    continue  # Already notified

                # Mark the workflow as overdue by updating status
                cur.execute(
                    "UPDATE workflows SET status = 'overdue' WHERE id = %s",
                    (wid,),
                )

                # Create notification
                notification_msg = f"Workflow '{title}' is overdue in department {dept}"
                cur.execute(
                    """
                    INSERT INTO notifications (user_id, title, message, type, metadata, created_at)
                    VALUES (%s, %s, %s, 'workflow_overdue', %s, NOW())
                    """,
                    (
                        assigned_to,
                        f"Overdue Workflow: {title}",
                        notification_msg,
                        json.dumps({"workflow_id": wid, "department": dept}),
                    ),
                )

                # Also notify assignee if they have a user record
                if assigned_to:
                    cur.execute(
                        """
                        INSERT INTO notifications (user_id, title, message, type, metadata, created_at)
                        VALUES (%s, %s, %s, 'workflow_overdue', %s, NOW())
                        """,
                        (
                            assigned_to,
                            f"Overdue Workflow: {title}",
                            notification_msg,
                            json.dumps({"workflow_id": wid, "department": dept}),
                        ),
                    )

            conn.commit()

            print(f"Marked {len(overdue)} workflows as overdue")


if __name__ == "__main__":
    import json
    mark_overdue()