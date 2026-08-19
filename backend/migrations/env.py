"""Alembic environment wired to Asto's settings (DEC-4/M2).

The migration engine connects to ``ASTO_DATABASE_URL`` through the app's
``app.config.Settings``, translated to SQLAlchemy's psycopg3 dialect
(``postgresql+psycopg://``) since the project's runtime driver is psycopg3,
not psycopg2. A programmatic caller (tests, deploy tooling) may override the
target by setting the ``sqlalchemy.url`` option on the Alembic Config object
before running commands.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _engine_url() -> str:
    """Resolve the target URL from the app settings."""
    from app.config import settings

    url = settings.database_url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


def _target_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url and not url.startswith("${"):
        return url
    return _engine_url()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout)."""
    context.configure(url=_target_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (directly against the database)."""
    connectable = create_engine(_target_url())
    with connectable.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()