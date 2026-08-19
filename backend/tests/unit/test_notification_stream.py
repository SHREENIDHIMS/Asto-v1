"""Unit tests for the SSE notification stream (Phase N6).

Covers: route wiring, auth, audience gating, the keepalive/ping framing,
resume-from-id semantics, and graceful cancellation of the event generator.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.v1 import notifications as notif_module

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

CLIENT_USER = {
    "id": 7,
    "email": "client@asto.local",
    "full_name": "Client User",
    "is_active": True,
    "audience": "client",
    "client_id": 7,
    "role": "client",
    "department": None,
    "allowed_departments": [],
}

ROW_1 = {
    "id": 11,
    "user_id": 2,
    "type": "document_rejected",
    "title": "Paystubs rejected",
    "body": "Missing a month.",
    "link": None,
    "is_read": False,
    "created_at": "2026-08-01T10:00:00",
}
ROW_2 = {
    "id": 12,
    "user_id": 2,
    "type": "document_approved",
    "title": "Paystubs approved",
    "body": "All good.",
    "link": None,
    "is_read": False,
    "created_at": "2026-08-01T10:01:00",
}


def _conn():
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cur = conn.cursor.return_value
    cur.__enter__.return_value = cur
    return conn


def _authorized(user: dict):
    from app.main import app
    from app.dependencies import require_auth

    app.dependency_overrides[require_auth] = lambda: user
    return TestClient(app)


def _cleanup() -> None:
    from app.main import app
    from app.dependencies import require_auth

    app.dependency_overrides.pop(require_auth, None)


def _collect(agen, max_events):
    """Drive an async generator until ``max_events`` events are collected."""
    events = []

    async def _driver():
        async for ev in agen:
            events.append(ev)
            if len(events) >= max_events:
                break

    asyncio.run(_driver())
    return events


def _expect_cancelled():
    """Context manager asserting asyncio.CancelledError was raised."""
    import contextlib

    @contextlib.contextmanager
    def _cm():
        try:
            yield
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("expected asyncio.CancelledError")

    return _cm()


class TestNotificationStreamRoutes:
    def test_routes_exist(self):
        from app.main import app
        paths = list(app.openapi()["paths"].keys())
        assert "/api/v1/staff/notifications/stream" in paths

    def test_stream_requires_auth(self):
        from app.main import app
        response = TestClient(app).get("/api/v1/staff/notifications/stream")
        assert response.status_code == 401

    def test_stream_denies_client_audience(self):
        try:
            response = _authorized(CLIENT_USER).get(
                "/api/v1/staff/notifications/stream"
            )
            assert response.status_code == 403
        finally:
            _cleanup()


class TestSseFraming:
    def test_sse_event_with_data(self):
        frame = notif_module._sse_event("notification", {"id": 1})
        assert frame == 'event: notification\ndata: {"id": 1}\n\n'

    def test_sse_event_without_data(self):
        frame = notif_module._sse_event("ping", None)
        assert frame == "event: ping\n\n"


class TestNotificationEventStream:
    def test_hello_then_new_notifications(self):
        """hello carries unread + latest id; rows > since_id stream oldest first."""
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"unread": 3, "latest_id": 12}
        cur.fetchall.return_value = [ROW_1, ROW_2]

        with patch("app.db.postgres.session.acquire", return_value=conn):
            events = _collect(
                notif_module._notification_event_stream(
                    2, since_id=10, poll_interval_s=0.001, ping_interval_s=5
                ),
                max_events=3,
            )

        assert events[0][0] == "hello"
        assert events[0][1] == {"unread_count": 3, "latest_id": 12}
        assert events[1][0] == "notification"
        assert events[1][1]["id"] == 11
        assert events[1][1]["title"] == "Paystubs rejected"
        assert events[2][0] == "notification"
        assert events[2][1]["id"] == 12

    def test_skips_rows_below_since_id(self):
        """Rows at/below since_id are never re-emitted (resume semantics).

        The DB query itself filters ``id > %s``; the mock mirrors that by
        only returning rows strictly above the client's resume point.
        """
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"unread": 0, "latest_id": 11}
        cur.fetchall.return_value = [ROW_2]

        with patch("app.db.postgres.session.acquire", return_value=conn):
            events = _collect(
                notif_module._notification_event_stream(
                    2, since_id=11, poll_interval_s=0.001, ping_interval_s=5
                ),
                max_events=2,
            )

        assert [ev for ev, _ in events] == ["hello", "notification"]
        assert events[1][1]["id"] == 12

    def test_emits_ping_keepalive(self):
        """With a short ping interval a ping event is emitted."""
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"unread": 0, "latest_id": 0}
        cur.fetchall.return_value = []

        with patch("app.db.postgres.session.acquire", return_value=conn):
            events = _collect(
                notif_module._notification_event_stream(
                    2, since_id=0, poll_interval_s=0.001, ping_interval_s=0.001
                ),
                max_events=3,
            )

        events_kind = [ev for ev, _ in events]
        assert events_kind[0] == "hello"
        assert "ping" in events_kind[1:]

    def test_cancellation_propagates(self):
        """Cancelling the consumer cancels the stream (client disconnect)."""
        conn = _conn()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = {"unread": 0, "latest_id": 0}
        cur.fetchall.return_value = []

        async def _drive():
            agen = notif_module._notification_event_stream(
                2, since_id=0, poll_interval_s=10, ping_interval_s=5
            )
            first = await anext(agen)
            task = asyncio.create_task(agen.__anext__())
            task.cancel()
            with _expect_cancelled():
                await task
            return first

        with patch("app.db.postgres.session.acquire", return_value=conn):
            first = asyncio.run(_drive())
        assert first[0] == "hello"