"""Feedback endpoints for response quality signals."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.dependencies import require_auth
from app.db.postgres.session import acquire

router = APIRouter()


class FeedbackRequest(BaseModel):
    response_id: str
    rating: int
    comment: str | None = None


@router.post("/", status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    request: FeedbackRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """Submit feedback (thumbs up/down) on a response."""
    if request.rating not in (-1, 1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rating must be 1 or -1",
        )

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO feedback (user_id, response_id, rating, comment) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (
                    user["id"],
                    request.response_id,
                    request.rating,
                    request.comment,
                ),
            )
            feedback_id = cur.fetchone()["id"]
        conn.commit()

    return {
        "message": "Feedback recorded",
        "feedback_id": feedback_id,
    }
