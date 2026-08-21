"""documents.review_due: scheduled content review date

Revision ID: 0005_document_review_due
Revises: 0004_pinned_answers
Create Date: 2026-08-21

Adds ``documents.review_due`` (DATE, nullable). Admins schedule a content
review per document; the admin dashboard counts overdue documents and
search responses flag sources past their review date so staff know an
excerpt may be stale. NULL means no review schedule.

Idempotent on fresh databases: 0001 (baseline) imports the updated
schema.py which adds the column directly.
"""

from __future__ import annotations

from alembic import op

revision = "0005_document_review_due"
down_revision = "0004_pinned_answers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS review_due DATE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_review_due "
        "ON documents (review_due) WHERE review_due IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_documents_review_due")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS review_due")
