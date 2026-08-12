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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import settings
from app.db.postgres.schema import ensure_schema

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

# CORS — restricted in production, permissive in dev
if settings.cors_origins == "*":
    allow_origins = ["*"]
else:
    allow_origins = settings.cors_origins.split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    """Health check endpoint — no DB dependency."""
    return {"status": "healthy", "timestamp": time.time()}


@app.get(f"{settings.api_prefix}/health")
async def api_health() -> dict:
    """API-level health check with DB connectivity."""
    from app.db.postgres.session import ping

    db_ok = ping()
    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "timestamp": time.time(),
    }


app.include_router(api_router, prefix=settings.api_prefix)
