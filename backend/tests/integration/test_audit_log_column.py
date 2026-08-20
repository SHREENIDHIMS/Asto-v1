"""Integration test: audit_log.audience column round-trips on a fresh DB.

P0-1 regression guard: a prior audit claimed ``audit_log.audience`` was
missing. It was a false positive (the column exists in the schema and in
the live database). This test proves a query audit write persists the
``audience`` value end-to-end against the real Postgres.
"""

from __future__ import annotations

import uuid

import pytest


def _db_available() -> bool:
    try:
        from app.db.postgres.session import ping
        return ping()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="Requires a running Postgres instance with asto_assistant schema",
)


class TestAuditLogAudienceColumn:
    def test_audience_persists_for_client_entry(self):
        marker = f"__audit_col__{uuid.uuid4().hex[:8]}"
        from app.audit.audit_logger import AuditLogEntry, log_query
        from app.db.postgres import session

        log_query(
            AuditLogEntry(
                user_id=7,
                query=marker,
                audience="client",
                outcome="answer",
                confidence=0.91,
            )
        )

        with session.acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT audience, user_id, outcome FROM audit_log "
                    "WHERE query = %s",
                    (marker,),
                )
                row = cur.fetchone()

        assert row is not None
        assert row["audience"] == "client"
        assert row["user_id"] == 7
        assert row["outcome"] == "answer"

    def test_audience_persists_for_staff_entry(self):
        marker = f"__audit_col__{uuid.uuid4().hex[:8]}"
        from app.audit.audit_logger import AuditLogEntry, log_query
        from app.db.postgres import session

        log_query(
            AuditLogEntry(
                user_id=3,
                query=marker,
                audience="staff",
                outcome="no_answer",
                confidence=0.12,
            )
        )

        with session.acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT audience, user_id, outcome FROM audit_log "
                    "WHERE query = %s",
                    (marker,),
                )
                row = cur.fetchone()

        assert row is not None
        assert row["audience"] == "staff"
        assert row["user_id"] == 3
        assert row["outcome"] == "no_answer"