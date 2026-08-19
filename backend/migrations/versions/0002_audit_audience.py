"""audit_log.audience column

Revision ID: 0002_audit_audience
Revises: 0001_baseline
Create Date: 2026-08-19

Adds the ``audience`` column to ``audit_log`` so the audit INSERT
(``PostgresAuditLogger.log_query``) succeeds on databases that were
provisioned by an earlier baseline revision which created the table
without this column. The dev/seed databases had it applied by hand;
every fresh deployment now gets it via either the baseline CREATE TABLE
(schema.py imports are live, so 0001 already includes the column) or, for
databases already stamped ``0001_baseline``, this migration.

Idempotent: ``ADD COLUMN IF NOT EXISTS`` (no-op if the column already
exists from a hand-applied addition or a re-run 0001).
"""

from __future__ import annotations

from alembic import op

revision = "0002_audit_audience"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS audience TEXT"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE audit_log DROP COLUMN IF EXISTS audience")
