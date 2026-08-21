"""Feedback endpoints for response quality signals."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.dependencies import require_auth
from app.db.postgres import session

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
    """Submit feedback (thumbs up/down) on a response.

    A thumbs-down additionally notifies every admin in-app (best-effort)
    so low-quality answers surface immediately instead of only in the
    analytics aggregate.
    """
    if request.rating not in (-1, 1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rating must be 1 or -1",
        )

    with session.acquire() as conn:
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

            if request.rating == -1:
                # Attach the original query for context, when still in audit_log.
                cur.execute(
                    "SELECT query FROM audit_log WHERE response_id = %s "
                    "ORDER BY id DESC LIMIT 1",
                    (request.response_id,),
                )
                row = cur.fetchone()
                original_query = row["query"] if row else None

                from app.api.v1.notifications import notify_admins

                body_parts = []
                if original_query:
                    body_parts.append(f'Query: "{original_query}"')
                if request.comment:
                    body_parts.append(f"Comment: {request.comment}")
                notify_admins(
                    conn,
                    "feedback_negative",
                    "Negative feedback received",
                    " ".join(body_parts) or f"Response {request.response_id} was rated thumbs-down.",
                    link="/admin",
                )
        conn.commit()

    return {
        "message": "Feedback recorded",
        "feedback_id": feedback_id,
    }
