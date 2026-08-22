"""Unit tests for client document reminder emails (batch-only module)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.documents.reminders import (
    ReminderConfig,
    collect_outstanding,
    render_reminder,
    send_reminders,
)


def _conn(cases: list[dict], checklists: dict[int, list[dict]]) -> MagicMock:
    """Connection whose first fetchall returns cases; derive_case_checklist
    is patched by the caller, so the cursor only serves the case query."""
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchall.return_value = cases
    return conn


def _checklist(*statuses: str) -> list[dict]:
    return [
        {"name": f"Item {i}", "description": "", "status": s,
         "has_document": s == "approved", "matching_document": None}
        for i, s in enumerate(statuses)
    ]


class TestCollectOutstanding:
    def test_groups_pending_items_per_client(self):
        cases = [
            {"case_id": 1, "case_number": "PUR-1", "client_id": 7,
             "email": "c@asto.local", "full_name": "Client User"},
            {"case_id": 2, "case_number": "REF-2", "client_id": 7,
             "email": "c@asto.local", "full_name": "Client User"},
        ]
        conn = _conn(cases, {})
        with patch(
            "app.documents.requirements.derive_case_checklist",
            side_effect=[
                _checklist("approved", "pending"),
                _checklist("pending", "approved", "pending"),
            ],
        ):
            entries = collect_outstanding(conn)

        assert len(entries) == 1
        entry = entries[0]
        assert entry["client_id"] == 7
        assert entry["email"] == "c@asto.local"
        assert len(entry["cases"]) == 2
        assert entry["cases"][0]["missing"] == ["Item 1"]
        assert entry["cases"][1]["missing"] == ["Item 0", "Item 2"]

    def test_client_with_nothing_pending_is_skipped(self):
        cases = [
            {"case_id": 1, "case_number": "PUR-1", "client_id": 7,
             "email": "c@asto.local", "full_name": "Client User"},
        ]
        conn = _conn(cases, {})
        with patch(
            "app.documents.requirements.derive_case_checklist",
            return_value=_checklist("approved", "received"),
        ):
            entries = collect_outstanding(conn)
        assert entries == []


class TestRenderReminder:
    def test_lists_verbatim_requirement_names(self):
        entry = {
            "client_id": 7,
            "email": "c@asto.local",
            "full_name": "Client User",
            "cases": [
                {"case_id": 1, "case_number": "PUR-1",
                 "missing": ["Proof of Income", "Bank Statements"]}
            ],
        }
        subject, text, html = render_reminder(entry)
        assert subject == ReminderConfig.subject
        assert "Proof of Income" in text and "Bank Statements" in text
        assert "PUR-1" in text
        assert "<li>Proof of Income</li>" in html
        # No requirement name may be altered — verbatim only.
        assert "proof of income" not in text.replace("Proof of Income", "")

    def test_falls_back_to_generic_greeting(self):
        entry = {
            "client_id": 7,
            "email": "c@asto.local",
            "full_name": None,
            "cases": [{"case_id": 1, "case_number": "PUR-1", "missing": ["X"]}],
        }
        _, text, _ = render_reminder(entry)
        assert "Hello there," in text


class TestSendReminders:
    def test_sends_one_email_per_outstanding_client(self):
        cases = [
            {"case_id": 1, "case_number": "PUR-1", "client_id": 7,
             "email": "a@asto.local", "full_name": "A"},
            {"case_id": 2, "case_number": "REF-2", "client_id": 8,
             "email": "b@asto.local", "full_name": "B"},
        ]
        conn = _conn(cases, {})
        with patch(
            "app.documents.requirements.derive_case_checklist",
            side_effect=[_checklist("pending"), _checklist("approved")],
        ), patch("app.email.mailer.send_email", return_value=True) as mock_send:
            report = send_reminders(conn)

        assert report["clients_with_outstanding"] == 1
        assert report["emails_sent"] == 1
        assert mock_send.call_count == 1
        assert mock_send.call_args.args[0] == "a@asto.local"

    def test_mailer_failure_does_not_raise(self):
        cases = [
            {"case_id": 1, "case_number": "PUR-1", "client_id": 7,
             "email": "a@asto.local", "full_name": "A"},
        ]
        conn = _conn(cases, {})
        with patch(
            "app.documents.requirements.derive_case_checklist",
            return_value=_checklist("pending"),
        ), patch("app.email.mailer.send_email", return_value=False):
            report = send_reminders(conn)
        assert report["clients_with_outstanding"] == 1
        assert report["emails_sent"] == 0
