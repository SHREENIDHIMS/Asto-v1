"""documents.tags: free-form document labels

Revision ID: 0006_document_tags
Revises: 0005_document_review_due
Create Date: 2026-08-22

Adds ``documents.tags TEXT[] NOT NULL DEFAULT '{}'`` plus a GIN index.
The column was already read and written by the documents/approvals/client
routers (tag-filtered listings, PUT /admin/documents/{id}/tags) but was
missing from every DDL — a freshly provisioned database raised
UndefinedColumn on any of those queries.

Idempotent on fresh databases: 0001 (baseline) imports the updated
schema.py which adds the column directly.
"""

from __future__ import annotations

from alembic import op

revision = "0006_document_tags"
down_revision = "0005_document_review_due"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS tags "
        "TEXT[] NOT NULL DEFAULT '{}'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_tags "
        "ON documents USING gin (tags)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_documents_tags")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS tags")
