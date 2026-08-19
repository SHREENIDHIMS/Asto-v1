"""M5 — GDPR-style personal-data export builder.

Collects every table that holds a client's personal data into a single JSON
document: profile, properties, cases, documents (with chunk content),
conversations (the client's own messages), feedback, and their query audit
history. Scoping is always by ``client_id`` from the JWT, never from the
request body.

The builder returns plain JSON-safe structures (datetimes/Decimals are
converted) so callers can hand it straight to a ``JSONResponse``.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal

from app.db.postgres import session


def json_safe(value):
    """Recursively convert a DB row into a JSON-serializable structure."""
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _rows(conn, sql: str, params: tuple) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _one(conn, sql: str, params: tuple) -> dict | None:
    rows = _rows(conn, sql, params)
    return rows[0] if rows else None


def _drop(rows: list[dict], *keys: str) -> list[dict]:
    for row in rows:
        for key in keys:
            row.pop(key, None)
    return rows


def build_client_export(client_id: int) -> dict:
    """Build the full personal-data export for one client."""
    with session.acquire() as conn:
        client = _one(
            conn,
            "SELECT * FROM clients WHERE id = %s",
            (client_id,),
        )
        if client is None:
            return {"client": None, "exists": False}

        properties = _rows(
            conn,
            "SELECT id, address, city, state, postal_code, property_type, "
            "is_active, created_at FROM properties WHERE client_id = %s "
            "ORDER BY id",
            (client_id,),
        )

        cases = _rows(
            conn,
            "SELECT id, case_number, property_id, loan_amount, status, "
            "is_active, created_at FROM cases WHERE client_id = %s ORDER BY id",
            (client_id,),
        )

        documents = _rows(
            conn,
            "SELECT d.id, d.title, d.doc_type, d.department, d.approval_status, "
            "d.is_active, d.created_at, "
            "COALESCE(string_agg(c.content, E'\\n---\\n' ORDER BY c.id), '') AS content "
            "FROM documents d "
            "LEFT JOIN document_chunks c ON c.document_id = d.id "
            "WHERE d.client_id = %s GROUP BY d.id ORDER BY d.id",
            (client_id,),
        )

        conversations = _rows(
            conn,
            "SELECT id, case_id, subject, created_at "
            "FROM conversations WHERE client_id = %s ORDER BY id",
            (client_id,),
        )
        conversation_ids = [c["id"] for c in conversations]
        messages = []
        if conversation_ids:
            messages = _rows(
                conn,
                "SELECT conversation_id, sender_type, sender_user_id, "
                "sender_client_id, body, created_at "
                "FROM messages WHERE sender_client_id = %s ORDER BY created_at, id",
                (client_id,),
            )

        feedback = _rows(
            conn,
            "SELECT response_id, rating, comment, created_at "
            "FROM feedback WHERE user_id = %s ORDER BY created_at, id",
            (client_id,),
        )

        audit = _rows(
            conn,
            "SELECT id, query, outcome, confidence, response_id, latency_ms, "
            "created_at FROM audit_log WHERE user_id = %s ORDER BY created_at, id",
            (client_id,),
        )

    return {
        "exists": True,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "client": _drop([client], "password_hash")[0],
        "properties": properties,
        "cases": cases,
        "documents": documents,
        "conversations": conversations,
        "messages": messages,
        "feedback": feedback,
        "audit": audit,
    }
