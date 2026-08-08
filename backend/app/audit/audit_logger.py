"""Audit logger — immutable record of every query.

Per CLAUDE.md rule #8: EVERY query is audit-logged, including
'no answer found' and test/internal queries against production data.
This is a compliance artifact, separate from analytics/.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Protocol

from psycopg.types.json import Json

from app.config import settings
from app.db.postgres.session import acquire

logger = logging.getLogger(__name__)


class AuditLogEntry:
    """Immutable record of a single user query and its outcome."""

    def __init__(
        self,
        user_id: int | None,
        query: str,
        sub_queries: list[str] | None = None,
        retrieved_ids: list[int] | None = None,
        confidence: float | None = None,
        response_id: str | None = None,
        outcome: str | None = None,
        latency_ms: float | None = None,
    ) -> None:
        self.user_id = user_id
        self.query = query
        self.sub_queries = sub_queries
        self.retrieved_ids = retrieved_ids
        self.confidence = confidence
        self.response_id = response_id or str(uuid.uuid4())
        self.outcome = outcome
        self.latency_ms = latency_ms


def log_query(entry: AuditLogEntry) -> None:
    """Write an audit log entry to the Postgres audit_log table.

    Never raises — audit logging must not break the request path.
    If the DB write fails, log to stderr as a fallback.
    """
    if not settings.audit_enabled:
        return

    try:
        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO audit_log "
                    "(user_id, query, sub_queries, retrieved_ids, confidence, "
                    " response_id, outcome, latency_ms) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        entry.user_id,
                        entry.query,
                        Json(entry.sub_queries) if entry.sub_queries is not None else None,
                        entry.retrieved_ids,
                        entry.confidence,
                        entry.response_id,
                        entry.outcome,
                        entry.latency_ms,
                    ),
                )
                conn.commit()
    except Exception as exc:
        logger.error("Audit log write failed: %s", exc)


class AuditLogger(Protocol):
    """Protocol for audit logging — allows dependency injection in tests."""

    def log(self, entry: AuditLogEntry) -> None: ...


class PostgresAuditLogger:
    """Production audit logger — writes to Postgres."""

    def log(self, entry: AuditLogEntry) -> None:
        log_query(entry)


class NullAuditLogger:
    """No-op audit logger for testing."""

    def log(self, entry: AuditLogEntry) -> None:
        logger.debug("Audit (null): %s", entry.query)
