"""Unit tests for overdue task/workflow escalation (batch-only module)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.staff_ops.escalation import (
    EscalationConfig,
    collect_overdue_tasks,
    collect_overdue_workflows,
    run_escalation,
)


def _conn(fetchall_queue: list[list[dict]] | None = None) -> MagicMock:
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    batches = iter(fetchall_queue or [])
    cur.fetchall.side_effect = lambda: next(batches, [])
    cur.fetchone.return_value = {"n": 0}  # cooldown: nothing recent
    return conn


TASK_ROW = {
    "id": 11,
    "title": "Order appraisal",
    "due_at": "2026-08-01",
    "assignee_id": 2,
    "assignee_email": "staff@asto.local",
}

WORKFLOW_ROW = {
    "id": 21,
    "title": "Refi intake",
    "due_at": "2026-08-02",
    "assignee_id": 2,
    "assignee_email": "staff@asto.local",
}


class TestCollectors:
    def test_tasks_exclude_completed(self):
        conn = _conn()
        collect_overdue_tasks(conn)
        sql = conn.cursor.return_value.__enter__.return_value.execute.call_args.args[0]
        assert "status NOT IN ('completed', 'overdue')" in sql
        assert "due_at < now()" in sql

    def test_workflows_exclude_done(self):
        conn = _conn()
        collect_overdue_workflows(conn)
        sql = conn.cursor.return_value.__enter__.return_value.execute.call_args.args[0]
        assert "w.status <> 'done'" in sql
        assert "w.due_at < now()" in sql


class TestRunEscalation:
    def test_notifies_assignees_with_item_tagging(self):
        conn = _conn([[TASK_ROW], [WORKFLOW_ROW]])
        with patch(
            "app.api.v1.notifications.notify_user"
        ) as mock_notify:
            report = run_escalation(conn)

        assert report == {
            "tasks_overdue": 1,
            "workflows_overdue": 1,
            "tasks_notified": 1,
            "workflows_notified": 1,
        }
        assert mock_notify.call_count == 2
        # The notification row must be tagged with the item id for cooldown.
        cur = conn.cursor.return_value.__enter__.return_value
        tag_calls = [
            c for c in cur.execute.call_args_list
            if "jsonb_build_object" in c.args[0]
        ]
        assert len(tag_calls) == 2
        assert tag_calls[0].args[1][0] == "11"

    def test_cooldown_skips_recently_notified(self):
        conn = _conn([[TASK_ROW], []])
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = {"n": 1}  # already escalated recently
        with patch("app.api.v1.notifications.notify_user") as mock_notify:
            report = run_escalation(conn)
        assert report["tasks_notified"] == 0
        mock_notify.assert_not_called()

    def test_unassigned_items_are_skipped(self):
        unassigned = {**TASK_ROW, "assignee_id": None}
        conn = _conn([[unassigned], []])
        with patch("app.api.v1.notifications.notify_user") as mock_notify:
            report = run_escalation(conn)
        assert report["tasks_notified"] == 0
        mock_notify.assert_not_called()

    def test_custom_cooldown_reaches_sql(self):
        conn = _conn([[TASK_ROW], []])
        run_escalation(conn, EscalationConfig(cooldown_hours=72))
        cur = conn.cursor.return_value.__enter__.return_value
        cooldown_calls = [
            c for c in cur.execute.call_args_list
            if "make_interval" in c.args[0]
        ]
        assert cooldown_calls and cooldown_calls[0].args[1][2] == 72
