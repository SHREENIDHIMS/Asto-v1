"""pinned answers: curated verbatim response packages

Revision ID: 0004_pinned_answers
Revises: 0003_scoped_chunk_dedup
Create Date: 2026-08-21

Adds ``pinned_answers`` — admin-curated response packages served verbatim
on an exact normalized-query match, before retrieval. Doctrine-compliant
(no generation): a pin is a stored SearchResponse produced by a real
audited search (``source_response_id`` references ``audit_log``), replayed
verbatim.

Audience scoping ('staff' | 'client' | 'any') is enforced in the serve-time
SQL WHERE clause (CLAUDE.md rule 1): a pin captured from staff-visible
documents must never leak to client accounts.

Idempotent on fresh databases: 0001 (baseline) imports the updated
schema.py which creates the table directly.
"""

from __future__ import annotations

from alembic import op

revision = "0004_pinned_answers"
down_revision = "0003_scoped_chunk_dedup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pinned_answers (
            id                  BIGSERIAL PRIMARY KEY,
            query               TEXT NOT NULL,
            query_norm          TEXT NOT NULL UNIQUE,
            audience            TEXT NOT NULL DEFAULT 'staff'
                                CHECK (audience IN ('staff', 'client', 'any')),
            package             JSONB NOT NULL,
            source_response_id  TEXT,
            confidence          DOUBLE PRECISION NOT NULL DEFAULT 1.0,
            created_by          BIGINT REFERENCES users(id),
            is_active           BOOLEAN NOT NULL DEFAULT true,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pinned_answers_active "
        "ON pinned_answers (query_norm, is_active)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_pinned_answers_active")
    op.execute("DROP TABLE IF EXISTS pinned_answers")
