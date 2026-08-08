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
