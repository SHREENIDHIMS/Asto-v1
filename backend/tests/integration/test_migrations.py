"""Integration test for M2: migrations apply on a fresh database.

Verifies the DEC-4/Alembic story end to end against the shared Postgres
instance (never a separate container, rule 2):

1. A scratch database (``asto_mig_test``) is created from scratch.
2. ``alembic upgrade head`` builds the full schema — no ``ensure_schema()``
   involvement, exactly what the container entrypoint runs on deploy.
3. Key tables exist, the pgvector column is present, and ``alembic_version``
   is stamped at head.
4. The scratch database is dropped in teardown.

Requires the dev Postgres to be running (same precondition as every other
integration test) and the ``asto_app`` role to have CREATEDB — it does in
the compose setup, where it is the POSTGRES_USER superuser.
"""

from __future__ import annotations

import urllib.parse

import psycopg
import pytest

from app.config import settings

SCRATCH_DB = "asto_mig_test"
_EXPECTED_TABLES = {
    "users",
    "documents",
    "document_chunks",
    "notifications",
    "refresh_tokens",
    "password_resets",
    "saved_searches",
    "workflow_definitions",
}


def _with_dbname(url: str, dbname: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(parts._replace(path=f"/{dbname}"))


def _engine_url(db_url: str) -> str:
    """Translate a psycopg URL into SQLAlchemy's psycopg3 dialect."""
    if db_url.startswith("postgresql://"):
        return db_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return db_url.replace("postgres://", "postgresql+psycopg://", 1)


@pytest.fixture(scope="module")
def migrated_db():
    admin_url = _with_dbname(settings.database_url, "postgres")
    scratch_url = _with_dbname(settings.database_url, SCRATCH_DB)

    conn = psycopg.connect(admin_url, autocommit=True)
    try:
        conn.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {SCRATCH_DB}")
    finally:
        conn.close()

    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config()
        cfg.set_main_option("script_location", str(_migrations_dir()))
        cfg.set_main_option("sqlalchemy.url", _engine_url(scratch_url))
        command.upgrade(cfg, "head")
        yield scratch_url
    finally:
        cleanup = psycopg.connect(admin_url, autocommit=True)
        try:
            cleanup.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB} WITH (FORCE)")
        finally:
            cleanup.close()


def _migrations_dir():
    from pathlib import Path

    backend_dir = Path(__file__).resolve().parent.parent.parent
    return backend_dir / "migrations"


def test_upgrade_head_builds_full_schema(migrated_db):
    conn = psycopg.connect(migrated_db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )
            tables = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()
    assert _EXPECTED_TABLES <= tables


def test_upgrade_head_creates_pgvector_column(migrated_db):
    conn = psycopg.connect(migrated_db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'document_chunks' AND column_name = 'embedding'"
            )
            assert cur.fetchone() == ("USER-DEFINED",)
            cur.execute(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = 'document_chunks'::regclass AND attname = 'embedding'"
            )
            assert "vector" in cur.fetchone()[0]
    finally:
        conn.close()


def test_upgrade_head_stamps_alembic_version(migrated_db):
    conn = psycopg.connect(migrated_db)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT version_num FROM alembic_version")
            assert cur.fetchone() == ("0002_audit_audience",)
    finally:
        conn.close()


def test_audit_log_has_audience_column(migrated_db):
    """Regression guard (CLAUDE.md rule #8): audit_log.audit_log.write inserts
    the caller audience, so a fresh ``alembic upgrade head`` deploy must expose
    that column -- otherwise every audit write silently fails and the
    compliance trail is dead."""
    conn = psycopg.connect(migrated_db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'audit_log'"
            )
            cols = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()
    assert "audience" in cols


def test_upgrade_head_is_idempotent(migrated_db):
    """Running upgrade head again on the stamped DB must be a clean no-op."""
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(_migrations_dir()))
    cfg.set_main_option("sqlalchemy.url", _engine_url(migrated_db))
    command.upgrade(cfg, "head")