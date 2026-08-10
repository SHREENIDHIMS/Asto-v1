"""Shared messaging helpers (Phase F6).

Conversations are client-scoped: every conversation belongs to exactly one
client (``client_id``), optionally anchored to a case (``case_id``).
Messages carry ``sender_type`` (``staff`` | ``client``) so both audiences
write into the same tables.

Scoping rules are enforced in the SQL WHERE clause at query time (see
CLAUDE.md rule 1), never as a post-hoc filter:
- A client only ever sees conversations where ``client_id = their id``.
- A staff member only sees conversations for clients they are assigned to
  (``staff_client_assignments``); admins see all.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.auth.rbac import is_admin
from app.db.postgres import session


def _assert_conversation_access_client(conn, client_id: int, conversation_id: int) -> None:
    """Raise 404 unless the conversation belongs to this client."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM conversations "
            "WHERE id = %s AND client_id = %s",
            (conversation_id, client_id),
        )
        if cur.fetchone() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )


def _assert_conversation_access_staff(
    conn, user: dict, conversation_id: int
) -> dict:
    """Raise 404 unless staff may access the conversation.

    Access rule is enforced in SQL: the conversation's client must appear
    in the staff member's assignments (admin: no restriction). Returns the
    conversation row for callers that need ``client_id``/``case_id``.
    """
    if is_admin(user):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, case_id, client_id, subject "
                "FROM conversations WHERE id = %s",
                (conversation_id,),
            )
            row = cur.fetchone()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        return dict(row)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.id, c.case_id, c.client_id, c.subject "
            "FROM conversations c "
            "JOIN staff_client_assignments sca ON sca.client_id = c.client_id "
            "WHERE c.id = %s AND sca.user_id = %s",
            (conversation_id, user["id"]),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or not assigned to you",
        )
    return dict(row)


def _list_conversations_client(conn, client_id: int) -> list[dict]:
    """Conversations for a client (SQL-scoped by client_id)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.id, c.case_id, c.client_id, c.subject, c.created_at, "
            "c.updated_at, ca.case_number "
            "FROM conversations c "
            "LEFT JOIN cases ca ON ca.id = c.case_id "
            "WHERE c.client_id = %s "
            "ORDER BY c.updated_at DESC",
            (client_id,),
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def _list_conversations_staff(conn, user: dict) -> list[dict]:
    """Conversations for assigned clients (admin: all), scoped in SQL."""
    if is_admin(user):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT c.id, c.case_id, c.client_id, c.subject, c.created_at, "
                "c.updated_at, cl.full_name AS client_name, ca.case_number "
                "FROM conversations c "
                "LEFT JOIN clients cl ON cl.id = c.client_id "
                "LEFT JOIN cases ca ON ca.id = c.case_id "
                "ORDER BY c.updated_at DESC"
            )
            rows = cur.fetchall()
            return [dict(row) for row in rows]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.id, c.case_id, c.client_id, c.subject, c.created_at, "
            "c.updated_at, cl.full_name AS client_name, ca.case_number "
            "FROM conversations c "
            "JOIN staff_client_assignments sca ON sca.client_id = c.client_id "
            "LEFT JOIN clients cl ON cl.id = c.client_id "
            "LEFT JOIN cases ca ON ca.id = c.case_id "
            "WHERE sca.user_id = %s "
            "ORDER BY c.updated_at DESC",
            (user["id"],),
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def _list_messages(conn, conversation_id: int) -> list[dict]:
    """All messages in a conversation, oldest first, with sender names."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT m.id, m.conversation_id, m.sender_type, m.sender_user_id, "
            "m.sender_client_id, m.body, m.created_at, "
            "COALESCE(u.full_name, cl.full_name) AS sender_name "
            "FROM messages m "
            "LEFT JOIN users u ON u.id = m.sender_user_id "
            "LEFT JOIN clients cl ON cl.id = m.sender_client_id "
            "WHERE m.conversation_id = %s "
            "ORDER BY m.created_at, m.id",
            (conversation_id,),
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def _touch_conversation(conn, conversation_id: int) -> None:
    """Bump updated_at so recent activity sorts to the top."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE conversations SET updated_at = now() WHERE id = %s",
            (conversation_id,),
        )
