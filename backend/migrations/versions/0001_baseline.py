"""baseline: pre-Alembic schema owned by ensure_schema() (M2)

Revision ID: 0001_baseline
Revises:
Create Date: 2026-08-19

Before Alembic was reintroduced (DEC-4), the whole schema was created by
the idempotent ``ensure_schema()`` DDL in ``app/db/postgres/schema.py``.
This baseline re-runs the exact same statement lists, so:

- ``alembic upgrade head`` alone builds a fresh database from scratch, and
- it is a no-op on databases already created by ``ensure_schema()`` (every
  statement is IF NOT EXISTS / guarded).

Importing the app module keeps the baseline permanently in sync with the
source of truth — they can never drift. From here on, every future schema
change ships its own migration; ``schema.py`` is frozen as the baseline.
"""

from __future__ import annotations

import re

from alembic import op

from app.db.postgres import schema

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def _table_names() -> list[str]:
    """Table names in creation order, parsed from the DDL list."""
    names: list[str] = []
    for ddl in schema.DDL_STATEMENTS:
        match = re.search(r"CREATE TABLE IF NOT EXISTS (\w+)", ddl)
        if match and match.group(1) not in names:
            names.append(match.group(1))
    return names


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    for ddl in schema.DDL_STATEMENTS:
        op.execute(ddl)
    for alter in schema.ALTER_STATEMENTS:
        op.execute(alter)
    for constraint in schema.CONSTRAINT_STATEMENTS:
        op.execute(constraint)
    for index in schema.INDEX_STATEMENTS:
        op.execute(index)


def downgrade() -> None:
    # Reverse creation order so FK-dependent tables drop first; CASCADE is a
    # belt-and-braces safety net for anything we missed.
    for table in reversed(_table_names()):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")