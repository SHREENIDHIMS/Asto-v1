"""Staff notifications API (Phase G0).

Generic per-user notification inbox with RBAC scoping enforced in the
SQL WHERE clause (CLAUDE.md rule 1):

- GET  /notifications               — the caller's own notifications (unread
                                      first, newest first)
- GET  /notifications/stream        — SSE stream that pushes new
                                      notifications to the caller in real
                                      time (Phase N6, same transport as the
                                      Session-6 search stream)
- POST /notifications/{id}/read     — mark one own notification as read
- POST /notifications/read-all      — mark all own notifications as read

Notifications are created by the review pipeline (approve/reject notifies
the document uploader) and by staff uploads (notifies admins that a
document awaits review). The schema is deliberately generic so SOP-access
outcomes and message pings can become new rows without a migration.
"""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.dependencies import require_auth
from app.db.postgres import session
from app.db.postgres.models import notification_row_to_dict
from app.email.mailer import send_email, smtp_configured

router = APIRouter()

# How often the stream re-polls Postgres for new rows.
POLL_INTERVAL_MS = 3000
# Keepalive comment emitted at this cadence so idle proxies/browsers do not
# drop the connection when no notification has been inserted.
PING_INTERVAL_S = 15


def _email_user(
    conn,
    user_id: int,
    title: str,
    body: str | None,
    link: str | None,
) -> None:
    """Best-effort L7 email mirror of an in-app notification.

    Resolves the recipient's address from ``users`` and sends via the
    mailer. Only called when SMTP is configured, so it never runs in tests
    or in an SMTP-less dev environment. Failure is logged, never raised.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT email FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
    if not row or not row.get("email"):
        return
    text = body or title
    html = f"<p>{body or title}</p>"
    if link:
        text = f"{text}\n\n{link}"
        html += f'<p><a href="{link}">{link}</a></p>'
    send_email(row["email"], title, html, text)


def notify_user(
    conn,
    user_id: int,
    notification_type: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
) -> None:
    """Insert a notification for a staff user (no commit — caller commits)."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO notifications (user_id, type, title, body, link) "
            "VALUES (%s, %s, %s, %s, %s)",
            (user_id, notification_type, title, body, link),
        )
    # L7: mirror in-app notifications to email when a provider is wired up.
    if smtp_configured():
        _email_user(conn, user_id, title, body, link)


def notify_admins(
    conn,
    notification_type: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
) -> None:
    """Insert a notification for every admin-role user (no commit)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM users WHERE is_active = true AND role IN ('admin', 'super_admin')"
        )
        admin_ids = [r["id"] for r in cur.fetchall()]
    for admin_id in admin_ids:
        notify_user(conn, admin_id, notification_type, title, body, link)


@router.get("/notifications")
async def list_notifications(
    user: dict = Depends(require_auth),
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Return the authenticated staff user's own notifications."""
    if user.get("audience") == "client":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client accounts cannot access notifications",
        )

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, type, title, body, link, is_read, created_at "
                "FROM notifications WHERE user_id = %s "
                "ORDER BY is_read ASC, created_at DESC, id DESC "
                "LIMIT %s OFFSET %s",
                (user["id"], limit, offset),
            )
            notifications = [dict(row) for row in cur.fetchall()]
            cur.execute(
                "SELECT COUNT(*) AS unread FROM notifications "
                "WHERE user_id = %s AND is_read = false",
                (user["id"],),
            )
            unread = cur.fetchone()["unread"]

    return {
        "notifications": [notification_row_to_dict(n) for n in notifications],
        "unread_count": unread,
    }


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    user: dict = Depends(require_auth),
) -> dict:
    """Mark one of the caller's own notifications as read (scoped by user_id)."""
    if user.get("audience") == "client":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client accounts cannot access notifications",
        )

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE notifications SET is_read = true "
                "WHERE id = %s AND user_id = %s",
                (notification_id, user["id"]),
            )
            if cur.rowcount == 0:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Notification not found",
                )
        conn.commit()

    return {"message": "Notification marked as read"}


@router.post("/notifications/read-all")
async def mark_all_notifications_read(
    user: dict = Depends(require_auth),
) -> dict:
    """Mark all of the caller's own notifications as read."""
    if user.get("audience") == "client":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client accounts cannot access notifications",
        )

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE notifications SET is_read = true "
                "WHERE user_id = %s AND is_read = false",
                (user["id"],),
            )
        conn.commit()

    return {"message": "All notifications marked as read"}


# ---------------------------------------------------------------------------
# SSE stream (Phase N6)
# ---------------------------------------------------------------------------


def _sse_event(event: str, data: dict | None) -> str:
    if data is None:
        return f"event: {event}\n\n"
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _stream_hello(user_id: int) -> dict:
    """Current unread count + newest id, sent once on connect.

    The client uses ``latest_id`` as its baseline so that notifications
    which already existed at connect time are not double-counted.
    """
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS unread, COALESCE(MAX(id), 0) AS latest_id "
                "FROM notifications WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
    return {"unread_count": row["unread"], "latest_id": row["latest_id"]}


def _fetch_new_notifications(user_id: int, after_id: int) -> list[dict]:
    """All of the user's notifications with id > after_id, oldest first."""
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, type, title, body, link, is_read, created_at "
                "FROM notifications WHERE user_id = %s AND id > %s "
                "ORDER BY id ASC",
                (user_id, after_id),
            )
            return [dict(row) for row in cur.fetchall()]


async def _notification_event_stream(
    user_id: int,
    since_id: int,
    poll_interval_s: float | None = None,
    ping_interval_s: float | None = None,
):
    """Async generator of ``(event, data)`` tuples for the SSE endpoint.

    Emits a ``hello`` event on connect, then polls Postgres every
    ``poll_interval_s`` and emits one ``notification`` event per new row
    (id > last emitted id). Emits ``ping`` events as keepalives so idle
    proxies do not close the connection between notifications.
    """
    poll_interval_s = poll_interval_s if poll_interval_s is not None else POLL_INTERVAL_MS / 1000
    ping_interval_s = ping_interval_s if ping_interval_s is not None else PING_INTERVAL_S

    last_id = since_id
    hello = await asyncio.to_thread(_stream_hello, user_id)
    yield ("hello", hello)

    next_ping = time.monotonic() + ping_interval_s
    while True:
        rows = await asyncio.to_thread(_fetch_new_notifications, user_id, last_id)
        for row in rows:
            last_id = row["id"]
            yield ("notification", notification_row_to_dict(row))
        now = time.monotonic()
        if now >= next_ping:
            yield ("ping", None)
            next_ping = now + ping_interval_s
        await asyncio.sleep(poll_interval_s)


@router.get("/notifications/stream")
async def stream_notifications(
    request: Request,
    user: dict = Depends(require_auth),
    since_id: int = 0,
) -> StreamingResponse:
    """Server-Sent Events stream of the caller's notifications.

    On connect the client receives a ``hello`` event with the current
    ``unread_count``. After that, one ``notification`` event is pushed per
    new notification (id > ``since_id`` / the ``Last-Event-ID`` header).
    ``ping`` events are sent every few seconds as keepalives.

    The stream holds the worker process open for as long as a client is
    connected — the same trade-off the Session-6 search stream already
    makes, and the reason this endpoint lives on the (socket-activated)
    API worker rather than a standing service.
    """
    if user.get("audience") == "client":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client accounts cannot access notifications",
        )

    header_id = request.headers.get("last-event-id")
    if header_id:
        try:
            since_id = int(header_id)
        except (TypeError, ValueError):
            pass

    async def gen():
        try:
            async for event, data in _notification_event_stream(user["id"], since_id):
                yield _sse_event(event, data)
        except asyncio.CancelledError:
            raise

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
