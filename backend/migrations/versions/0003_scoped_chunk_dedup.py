"""scope document_chunks.content_hash uniqueness to the document

Revision ID: 0003_scoped_chunk_dedup
Revises: 0002_audit_audience
Create Date: 2026-08-20

``content_hash`` was globally UNIQUE, which meant an identical chunk
(e.g. the same boilerplate or a re-uploaded file) could only belong to ONE
document row:

- Re-uploading an existing document (version bump in ``index_document``)
  created a fresh ``documents`` row but every chunk conflicted with the
  previous version's rows and was skipped → the new active version was
  effectively unsearchable (zero chunks).
- Two clients uploading documents that share verbatim text silently lost
  chunks / cross-referenced the wrong document.

Uniqueness is now scoped per-document: ``(document_id, content_hash)``.
Intra-document duplicate chunks are still skipped (both via the unique
index and the in-loop ``seen_hashes`` set); identical text across distinct
documents is allowed and each document owns its chunks.

Idempotent on fresh databases: 0001 (baseline) now imports the updated
schema.py which creates the scoped index directly, so the drops below are
no-ops there.
"""

from __future__ import annotations

from alembic import op

revision = "0003_scoped_chunk_dedup"
down_revision = "0002_audit_audience"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Inline UNIQUE on the column auto-creates document_chunks_content_hash_key.
    op.execute(
        "ALTER TABLE document_chunks "
        "DROP CONSTRAINT IF EXISTS document_chunks_content_hash_key"
    )
    op.execute("DROP INDEX IF EXISTS uq_chunks_content_hash")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_chunks_content_hash "
        "ON document_chunks (document_id, content_hash)"
    )


def downgrade() -> None:
    # Re-creating a GLOBAL unique index may fail if the DB now holds the same
    # chunk text under multiple documents (the very case this migration
    # permits) — downgrading is only safe on databases that kept hashes
    # unique across documents.
    op.execute("DROP INDEX IF EXISTS uq_chunks_content_hash")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_chunks_content_hash "
        "ON document_chunks (content_hash)"
    )