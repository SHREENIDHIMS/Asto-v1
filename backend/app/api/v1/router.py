"""
API v1 router aggregator.

Registers all route groups under /api/v1/. Each route module implements
its own endpoints; this file just aggregates them.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    analytics,
    approvals,
    auth,
    client,
    documents,
    feedback,
    notifications,
    saved_searches,
    search,
    staff,
    upload,
)

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(upload.router, prefix="/documents", tags=["upload"])
api_router.include_router(feedback.router, prefix="/feedback", tags=["feedback"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(approvals.router, prefix="/admin", tags=["approvals"])
api_router.include_router(client.router, prefix="/client", tags=["client"])
api_router.include_router(staff.router, prefix="/staff", tags=["staff"])
api_router.include_router(saved_searches.router, prefix="/staff", tags=["staff"])
api_router.include_router(notifications.router, prefix="/staff", tags=["staff"])
