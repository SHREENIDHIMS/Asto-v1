"""Row helpers for the persistence layer.

Keeps small, dependency-free row→dict mapping here so the query/search
modules can stay focused on logic. No ORM — a knowledge assistant with
one small Postgres schema does not justify SQLAlchemy's footprint on a
shared 1 GiB host.
"""

from __future__ import annotations

import hashlib


def content_hash(content: str) -> str:
    """Deterministic hash used for chunk-level deduplication."""
    return hashlib.sha256(content.strip().lower().encode("utf-8")).hexdigest()


def row_to_dict(row: dict) -> dict:
    """psycopg dict rows are already dict-like; normalize keys for JSON."""
    return {k: v for k, v in row.items()}


def chunk_row_to_candidate(row: dict) -> dict:
    """Shape a document_chunks JOIN documents row into a search candidate."""
    return {
        "chunk_id": row["id"],
        "document_id": row["document_id"],
        "title": row["title"],
        "doc_type": row["doc_type"],
        "department": row["department"],
        "client_id": row.get("client_id"),
        "section": row["section"],
        "chunk_type": row["chunk_type"],
        "content": row["content"],
        "bm25_score": row.get("bm25_score"),
        "vec_score": row.get("vec_score"),
    }


def client_row_to_dict(row: dict) -> dict:
    """Shape a clients table row for JSON responses (never expose hash)."""
    return {
        "id": row["id"],
        "email": row["email"],
        "full_name": row["full_name"],
        "is_active": row["is_active"],
        "created_at": row.get("created_at"),
    }


def case_row_to_dict(row: dict) -> dict:
    """Shape a cases table row for JSON responses."""
    return {
        "id": row["id"],
        "case_number": row["case_number"],
        "client_id": row["client_id"],
        "property_id": row["property_id"],
        "loan_amount": row.get("loan_amount"),
        "status": row["status"],
        "is_active": row["is_active"],
        "created_at": row.get("created_at"),
    }


def case_event_row_to_dict(row: dict) -> dict:
    """Shape a case_events table row for JSON responses."""
    return {
        "id": row["id"],
        "case_id": row["case_id"],
        "status": row["status"],
        "note": row.get("note"),
        "created_at": row.get("created_at"),
    }


def sop_row_to_dict(row: dict) -> dict:
    """Shape a sops table row for JSON responses."""
    return {
        "id": row["id"],
        "title": row["title"],
        "department": row["department"],
        "body": row["body"],
        "version": row["version"],
        "created_by": row.get("created_by"),
        "updated_at": row.get("updated_at"),
        "is_active": row["is_active"],
    }


def sop_request_row_to_dict(row: dict) -> dict:
    """Shape a sop_access_requests table row for JSON responses."""
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "action": row["action"],
        "department": row["department"],
        "reason": row.get("reason"),
        "status": row["status"],
        "reviewed_by": row.get("reviewed_by"),
        "reviewed_at": row.get("reviewed_at"),
        "created_at": row.get("created_at"),
    }


def workflow_row_to_dict(row: dict) -> dict:
    """Shape a workflows table row for JSON responses."""
    return {
        "id": row["id"],
        "title": row["title"],
        "department": row["department"],
        "case_id": row.get("case_id"),
        "status": row["status"],
        "assigned_to": row.get("assigned_to"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def case_note_row_to_dict(row: dict) -> dict:
    """Shape a case_notes table row for JSON responses."""
    return {
        "id": row["id"],
        "case_id": row["case_id"],
        "user_id": row["user_id"],
        "author_name": row.get("author_name"),
        "body": row["body"],
        "created_at": row.get("created_at"),
    }


def conversation_row_to_dict(row: dict) -> dict:
    """Shape a conversations table row for JSON responses."""
    return {
        "id": row["id"],
        "case_id": row.get("case_id"),
        "client_id": row.get("client_id"),
        "subject": row.get("subject"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def message_row_to_dict(row: dict) -> dict:
    """Shape a messages table row for JSON responses."""
    return {
        "id": row["id"],
        "conversation_id": row["conversation_id"],
        "sender_type": row["sender_type"],
        "sender_user_id": row.get("sender_user_id"),
        "sender_client_id": row.get("sender_client_id"),
        "sender_name": row.get("sender_name"),
        "body": row["body"],
        "created_at": row.get("created_at"),
    }
