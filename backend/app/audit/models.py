"""Audit log data models.

The audit_log table schema is defined in db/postgres/schema.py.
This module provides type-safe helpers for constructing and
querying audit entries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AuditRecord:
    """A single audit log entry fetched from the database."""

    id: int
    user_id: Optional[int]
    query: str
    sub_queries: Optional[list[str]] = None
    retrieved_ids: Optional[list[int]] = None
    confidence: Optional[float] = None
    response_id: Optional[str] = None
    outcome: Optional[str] = None
    latency_ms: Optional[float] = None
    created_at: Optional[str] = None


@dataclass
class AuditQuery:
    """Parameters for querying audit logs."""

    user_id: Optional[int] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    min_confidence: Optional[float] = None
    outcome: Optional[str] = None
    limit: int = 100
