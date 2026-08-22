"""Recent searches (G3 follow-up) — the caller's own query history.

Staff-only read view over ``audit_log`` (CLAUDE.md rule 8 already records
every query, so this adds no new logging — it just makes the user's own
history visible and re-runnable):

  GET /staff/recent-searches — distinct recent queries, newest first

Scoping is in the SQL WHERE clause (``user_id = %s``, rule #1): a user can
only ever see their own history. Client accounts are rejected with 403.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from pydantic import BaseModel

from app.db.postgres import session
from app.dependencies import require_auth
from app.api.v1.staff import _require_staff

router = APIRouter()

DEFAULT_LIMIT = 10
MAX_LIMIT = 50


class RecentSearch(BaseModel):
    query: str
    last_run_at: str | None = None
    times_run: int


class RecentSearchListResponse(BaseModel):
    recent_searches: list[RecentSearch]


@router.get("/recent-searches", response_model=RecentSearchListResponse)
async def list_recent_searches(
    user: dict = Depends(require_auth),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
) -> RecentSearchListResponse:
    """Return the caller's distinct recent queries, most recent first.

    Reads only from ``audit_log`` — no new table, no new writes. Empty
    strings and whitespace-only queries are excluded.
    """
    _require_staff(user)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT query, MAX(created_at) AS last_run, COUNT(*) AS times "
                "FROM audit_log "
                "WHERE user_id = %s AND audience = 'staff' "
                "AND btrim(query) <> '' "
                "GROUP BY query "
                "ORDER BY last_run DESC, query ASC "
                "LIMIT %s",
                (int(user["id"]), limit),
            )
            rows = cur.fetchall()

    return RecentSearchListResponse(
        recent_searches=[
            RecentSearch(
                query=r["query"],
                last_run_at=str(r["last_run"]) if r["last_run"] is not None else None,
                times_run=int(r["times"]),
            )
            for r in rows
        ]
    )
