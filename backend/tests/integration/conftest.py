"""Integration test fixtures.

Adds the repository root to sys.path so integration tests can import the
``evaluation`` package (repo-root level) — the same layout the benchmark
runner assumes.

Also ensures the Postgres schema exists before any integration test runs.
Locally the dev DB already has tables, but CI provisions a *fresh* Postgres
where only the ``vector`` extension exists — tests that insert into
``documents``/``document_chunks`` (e.g. ``test_benchmark_db_isolation``)
would otherwise die with ``UndefinedTable``. ``ensure_schema()`` is
idempotent, so this is a no-op against an already-migrated DB and matches
the production entrypoint's ``auto_create_schema`` behaviour.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = BACKEND_DIR.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="session", autouse=True)
def _ensure_asto_schema():
    """Create the asto_assistant schema on a fresh CI database (no-op when
    tables already exist or the DB is unreachable)."""
    from app.db.postgres.session import ping

    if not ping():
        return
    from app.db.postgres.schema import ensure_schema

    ensure_schema()
