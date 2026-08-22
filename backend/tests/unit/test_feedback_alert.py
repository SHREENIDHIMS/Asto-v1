"""Unit tests for negative-feedback admin alerting on POST /feedback/."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

STAFF_USER = {
    "id": 2,
    "email": "staff@asto.local",
    "full_name": "Dana Officer",
    "is_active": True,
    "audience": "staff",
    "role": "loan_officer",
    "department": "general",
    "allowed_departments": ["general"],
}


def _conn() -> MagicMock:
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cur = conn.cursor.return_value
    cur.__enter__.return_value = cur
    return conn


def _authorized():
    from app.main import app
    from app.dependencies import require_auth

    app.dependency_overrides[require_auth] = lambda: STAFF_USER
    return TestClient(app)


def _cleanup() -> None:
    from app.main import app
    from app.dependencies import require_auth

    app.dependency_overrides.pop(require_auth, None)


class TestNegativeFeedbackAlert:
    def test_thumbs_down_notifies_admins_with_query_and_comment(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"id": 11},  # feedback insert RETURNING
            {"query": "what is an APR"},  # audit_log lookup
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                with patch(
                    "app.api.v1.notifications.notify_admins"
                ) as mock_notify:
                    response = _authorized().post(
                        "/api/v1/feedback/",
                        json={
                            "response_id": "resp-1",
                            "rating": -1,
                            "comment": "Wrong answer",
                        },
                    )
            finally:
                _cleanup()
        assert response.status_code == 201
        assert mock_notify.call_count == 1
        args = mock_notify.call_args.args
        assert args[1] == "feedback_negative"
        assert "what is an APR" in args[3]
        assert "Wrong answer" in args[3]

    def test_thumbs_down_without_query_or_comment_still_notifies(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.side_effect = [
            {"id": 12},
            None,  # no matching audit row
        ]
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                with patch(
                    "app.api.v1.notifications.notify_admins"
                ) as mock_notify:
                    response = _authorized().post(
                        "/api/v1/feedback/",
                        json={"response_id": "resp-2", "rating": -1},
                    )
            finally:
                _cleanup()
        assert response.status_code == 201
        assert mock_notify.call_count == 1
        assert "resp-2" in mock_notify.call_args.args[3]

    def test_thumbs_up_does_not_notify(self):
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"id": 13}
        with patch("app.db.postgres.session.acquire", return_value=conn):
            try:
                with patch(
                    "app.api.v1.notifications.notify_admins"
                ) as mock_notify:
                    response = _authorized().post(
                        "/api/v1/feedback/",
                        json={"response_id": "resp-3", "rating": 1},
                    )
            finally:
                _cleanup()
        assert response.status_code == 201
        mock_notify.assert_not_called()
