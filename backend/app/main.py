"""FastAPI application entry point.

Run with:
    uvicorn app.main:app --workers 1 --fd 3

Socket-activated by systemd (asto-backend.socket on port 8011).
Idle-stops after 10 minutes of no activity (asto-backend-idle.timer).
"""

from __future__ import annotations

import logging
import time

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import settings
from app.db.postgres.schema import ensure_schema

__version__ = "1.1.0"

# uvicorn's default config attaches handlers to its own loggers but not the
# root, so application-level logs (search, audit, and the password-reset
# console fallback) are silently dropped. basicConfig gives every app logger
# a stderr handler that the container captures.
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Idempotent schema creation on startup; pool cleanup on shutdown."""
    if settings.auto_create_schema:
        ensure_schema()
    # Warm the connection pool so the first request isn't slowed by
    # lazy pool init (CLAUDE.md rule 6 — cold start is a tracked metric).
    from app.db.postgres.session import get_pool, ping

    get_pool()
    ping()
    yield
    from app.db.postgres.session import _pool

    if _pool is not None:
        _pool.close()


app = FastAPI(
    title=settings.app_name,
    docs_url=f"{settings.api_prefix}/docs",
    redoc_url=f"{settings.api_prefix}/redoc",
    openapi_url=f"{settings.api_prefix}/openapi.json",
    lifespan=lifespan,
)

# CORS — restricted in production, permissive in dev. A "*" origin is
# incompatible with credentialed (cookie) requests — browsers reject the
# combination and it would weaken the H1 refresh-cookie flow. When "*" is set,
# credentials are disabled, so cookie auth always requires an explicit origin.
allow_origins = ["*"] if settings.cors_origins == "*" else settings.cors_origins.split(",")
allow_credentials = settings.cors_origins != "*"

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.logging.middleware import RequestLoggingMiddleware

app.add_middleware(RequestLoggingMiddleware)


@app.get("/health")
async def health() -> dict:
    """Health check endpoint — no DB dependency."""
    return {"status": "healthy", "timestamp": time.time()}


@app.get(f"{settings.api_prefix}/health")
async def api_health() -> dict:
    """API-level health check with DB, storage, and ingest signal (M7).

    ``status`` is ``healthy`` when the DB responds, else ``degraded``.
    Storage-writability and last-ingest-time are reported for the admin
    system-status card; storage details are informational and do not by
    themselves flip the overall status.
    """
    from app.db.postgres.session import ping, acquire

    db_ok = ping()
    storage = _storage_health()
    last_ingest = None
    if db_ok:
        try:
            with acquire() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT MAX(created_at) AS t FROM documents")
                    row = cur.fetchone()
                    last_ingest = row["t"] if row and row["t"] is not None else None
        except Exception:  # noqa: BLE001 - informational, never fail the check
            last_ingest = None

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "storage": storage,
        "last_ingest": last_ingest,
        "version": __version__,
        "timestamp": time.time(),
    }


def _storage_health() -> dict:
    """Report whether the configured storage directories are writable."""
    dirs = {
        "pending": settings.storage_pending_dir,
        "processed": settings.storage_processed_dir,
    }
    result: dict[str, dict] = {}
    for key, rel in dirs.items():
        path = Path(rel)
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".health_probe"
            probe.write_bytes(b"ok")
            probe.unlink()
            result[key] = {"writable": True}
        except Exception as exc:  # noqa: BLE001
            result[key] = {"writable": False, "error": str(exc)}
    return result


app.include_router(api_router, prefix=settings.api_prefix)
