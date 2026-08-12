"""Staff notifications API (Phase G0).

Generic per-user notification inbox with RBAC scoping enforced in the
SQL WHERE clause (CLAUDE.md rule 1):

- GET  /notifications          â€” the caller's own notifications (unread
                                first, newest first)
- POST /notifications/{id}/read â€” mark one own notification as read
- POST /notifications/read-all  â€” mark all own notifications as read

Notifications are created by the review pipeline (approve/reject notifies
the document uploader) and by staff uploads (notifies admins that a
document awaits review). The schema is deliberately generic so SOP-access
outcomes and message pings can become new rows without a migration.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import require_auth
from app.db.postgres import session
from app.db.postgres.models import notification_row_to_dict

router = APIRouter()


def notify_user(
    conn,
    user_id: int,
    notification_type: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
) -> None:
    """Insert a notification for a staff user (no commit â€” caller commits)."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO notifications (user_id, type, title, body, link) "
            "VALUES (%s, %s, %s, %s, %s)",
            (user_id, notification_type, title, body, link),
        )


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
