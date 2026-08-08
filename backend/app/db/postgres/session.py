"""Postgres connection handling.

One shared Postgres instance per host, one database per project. This
module connects to this project's database and exposes:

- ``pool``  : a lazily-created psycopg connection pool
- ``acquire()`` : a context manager yielding a connection from the pool
- ``register_vector_type(conn)`` : wires the pgvector type adapter

The pool is deliberately small (see config) — the backend runs with a
single worker on a memory-capped shared host.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import psycopg
import psycopg_pool
from pgvector.psycopg import register_vector

from app.config import settings

logger = logging.getLogger(__name__)

_pool: psycopg_pool.ConnectionPool | None = None


def get_pool() -> psycopg_pool.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg_pool.ConnectionPool(
            settings.database_url,
            min_size=1,
            max_size=settings.database_pool_max,
            timeout=settings.database_pool_timeout_s,
            open=False,
        )
        _pool.open()
        logger.info("Postgres pool opened (max_size=%d)", settings.database_pool_max)
    return _pool


@contextmanager
def acquire() -> Iterator[psycopg.Connection]:
    """Yield a pooled connection; registers the pgvector adapter once."""
    with get_pool().connection() as conn:
        if not getattr(conn, "_pgvector_registered", False):
            register_vector(conn)
            conn._pgvector_registered = True  # type: ignore[attr-defined]
        if conn.row_factory is not psycopg.rows.dict_row:
            conn.row_factory = psycopg.rows.dict_row
        yield conn


def ping() -> bool:
    """Health-check: SELECT 1 against the database."""
    try:
        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
    except Exception:  # noqa: BLE001 - health check reports any failure as unhealthy
        return False
