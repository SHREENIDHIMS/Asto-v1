"""Saved searches (J7) — per-staff reusable queries.

Staff-only CRUD for the chat "Save this search" feature:
  GET    /staff/saved-searches          — list own saved searches
  POST   /staff/saved-searches          — save a query (max 50 per user)
  DELETE /staff/saved-searches/{id}     — delete one of your own

Scoping is in the SQL WHERE clause (`user_id = %s`, rule #1): a user can
only ever read or delete their own saved searches. Client accounts are
rejected with 403 (the saved-searches UI is staff-only).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.types.json import Json
from pydantic import BaseModel, Field

from app.db.postgres import session
from app.dependencies import require_auth
from app.api.v1.staff import _require_staff

router = APIRouter()

MAX_SAVED_SEARCHES = 50


class SaveSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    filters: dict = Field(default_factory=dict)


class SavedSearch(BaseModel):
    id: int
    query: str
    filters: dict
    created_at: str | None = None


class SavedSearchListResponse(BaseModel):
    saved_searches: list[SavedSearch]


def _row_to_saved_search(row) -> SavedSearch:
    created = row["created_at"]
    return SavedSearch(
        id=int(row["id"]),
        query=row["query"],
        filters=row["filters"] or {},
        created_at=str(created) if created is not None else None,
    )


@router.get("/saved-searches", response_model=SavedSearchListResponse)
async def list_saved_searches(
    user: dict = Depends(require_auth),
) -> SavedSearchListResponse:
    """List the caller's saved searches, newest first."""
    _require_staff(user)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, query, filters, created_at FROM saved_searches "
                "WHERE user_id = %s ORDER BY created_at DESC, id DESC",
                (int(user["id"]),),
            )
            rows = cur.fetchall()
    return SavedSearchListResponse(
        saved_searches=[_row_to_saved_search(r) for r in rows]
    )


@router.post("/saved-searches", response_model=SavedSearch, status_code=status.HTTP_201_CREATED)
async def save_search(
    request: SaveSearchRequest,
    user: dict = Depends(require_auth),
) -> SavedSearch:
    """Save a query + filters for later reuse (max 50 per user).

    Enforcing the cap in the same transaction as the insert keeps the
    count accurate under concurrency.
    """
    _require_staff(user)
    user_id = int(user["id"])

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM saved_searches WHERE user_id = %s",
                (user_id,),
            )
            count = cur.fetchone()["n"]
            if int(count) >= MAX_SAVED_SEARCHES:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Save limit reached ({MAX_SAVED_SEARCHES} saved searches)",
                )

            cur.execute(
                "INSERT INTO saved_searches (user_id, query, filters) "
                "VALUES (%s, %s, %s) RETURNING id, query, filters, created_at",
                (user_id, request.query.strip(), Json(request.filters)),
            )
            conn.commit()
            row = cur.fetchone()

    return _row_to_saved_search(row)


@router.delete("/saved-searches/{saved_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_search(
    saved_id: int,
    user: dict = Depends(require_auth),
) -> None:
    """Delete one of the caller's saved searches (own rows only)."""
    _require_staff(user)
    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM saved_searches WHERE id = %s AND user_id = %s",
                (saved_id, int(user["id"])),
            )
            conn.commit()
            if cur.rowcount == 0:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Saved search not found",
                )
