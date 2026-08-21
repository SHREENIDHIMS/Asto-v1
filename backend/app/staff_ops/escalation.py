"""Overdue task/workflow escalation notifications (batch-only).

Finds tasks and workflows whose due date has passed without completion and
notifies the assignee (in-app notification + best-effort email mirror via
the shared mailer). A 24h per-item cooldown (checked against the
notifications table) keeps daily timer runs from spamming.

Batch-only by design (rule 5): invoked from ``scripts/escalate_overdue.py``
behind a systemd timer, never from a request handler.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EscalationConfig:
    """Knobs for the escalation run (rule 7: configuration, not constants)."""

    cooldown_hours: int = 24
    task_type: str = "task_overdue"
    workflow_type: str = "workflow_overdue"


DEFAULT_ESCALATION = EscalationConfig()


def _recently_notified(conn, item_type: str, item_id: int, config: EscalationConfig) -> bool:
    """True when this exact item was already escalated inside the cooldown."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM notifications "
            "WHERE type = %s "
            "AND metadata->>'item_id' = %s "
            "AND created_at >= now() - make_interval(hours => %s)",
            (item_type, str(item_id), config.cooldown_hours),
        )
        return int(cur.fetchone()["n"] or 0) > 0


def _notify_assignee(conn, user_id: int | None, item_type: str, item_id: int,
                     title: str, body: str, config: EscalationConfig) -> bool:
    """Insert a notification (+ email mirror) for the assignee. No commit."""
    if user_id is None:
        return False
    if _recently_notified(conn, item_type, item_id, config):
        return False
    from app.api.v1.notifications import notify_user

    notify_user(
        conn,
        int(user_id),
        item_type,
        title,
        body,
        link="/staff",
    )
    # Tag the row with the item id so the cooldown lookup can find it.
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE notifications SET metadata = jsonb_build_object('item_id', %s) "
            "WHERE id = (SELECT MAX(id) FROM notifications WHERE user_id = %s AND type = %s)",
            (str(item_id), int(user_id), item_type),
        )
    return True


def collect_overdue_tasks(conn) -> list[dict]:
    """Unfinished tasks past their due date, with assignee emails."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT t.id, t.title, t.due_at, t.assignee_id, u.email AS assignee_email "
            "FROM tasks t LEFT JOIN users u ON u.id = t.assignee_id "
            "WHERE t.due_at IS NOT NULL AND t.due_at < now() "
            "AND t.status NOT IN ('completed', 'overdue')",
        )
        return [dict(r) for r in cur.fetchall()]


def collect_overdue_workflows(conn) -> list[dict]:
    """Unfinished workflows past their due date, with assignee emails."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT w.id, w.title, w.due_at, w.assigned_to AS assignee_id, "
            "u.email AS assignee_email "
            "FROM workflows w LEFT JOIN users u ON u.id = w.assigned_to "
            "WHERE w.due_at IS NOT NULL AND w.due_at < now() "
            "AND w.status <> 'done'",
        )
        return [dict(r) for r in cur.fetchall()]


def run_escalation(conn, config: EscalationConfig | None = None) -> dict:
    """Escalate every overdue item once per cooldown. Caller commits.

    Returns a report dict: {"tasks_notified", "workflows_notified",
    "tasks_overdue", "workflows_overdue"}.
    """
    config = config or DEFAULT_ESCALATION

    tasks = collect_overdue_tasks(conn)
    workflows = collect_overdue_workflows(conn)

    tasks_notified = 0
    for t in tasks:
        if _notify_assignee(
            conn,
            t["assignee_id"],
            config.task_type,
            int(t["id"]),
            "Task overdue",
            f"Task \"{t['title']}\" was due {t['due_at']}.",
            config,
        ):
            tasks_notified += 1

    workflows_notified = 0
    for w in workflows:
        if _notify_assignee(
            conn,
            w["assignee_id"],
            config.workflow_type,
            int(w["id"]),
            "Workflow overdue",
            f"Workflow \"{w['title']}\" was due {w['due_at']}.",
            config,
        ):
            workflows_notified += 1

    return {
        "tasks_overdue": len(tasks),
        "workflows_overdue": len(workflows),
        "tasks_notified": tasks_notified,
        "workflows_notified": workflows_notified,
    }
