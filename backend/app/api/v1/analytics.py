"""Analytics endpoints for admin review."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.permissions import require_role
from app.dependencies import require_auth
from app.db.postgres.session import acquire

router = APIRouter()


@router.get("/knowledge-gaps")
async def knowledge_gaps(
    user: dict = Depends(require_auth),
    limit: int = 50,
) -> dict:
    """View low-confidence / no-answer queries. Requires admin role."""
    require_role(user, "admin")

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, query, intent, confidence, created_at "
                "FROM knowledge_gaps ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
            gaps = [dict(row) for row in cur.fetchall()]

    return {"knowledge_gaps": gaps}


@router.get("/summary")
async def analytics_summary(
    user: dict = Depends(require_auth),
) -> dict:
    """Aggregate analytics for the admin dashboard charts.

    Returns:
    - total_gaps: total knowledge gaps recorded
    - by_intent: [{intent, count}] across all gaps
    - by_day: last 14 days [{date, count}]
    - low_confidence_count: gaps with confidence < 0.5
    """
    require_role(user, "admin")

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM knowledge_gaps")
            total = cur.fetchone()["n"] or 0

            cur.execute(
                "SELECT COALESCE(intent, 'unknown') AS intent, COUNT(*) AS count "
                "FROM knowledge_gaps GROUP BY COALESCE(intent, 'unknown') "
                "ORDER BY count DESC"
            )
            by_intent = [
                {"intent": row["intent"], "count": row["count"]}
                for row in cur.fetchall()
            ]

            cur.execute(
                "SELECT to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS day, "
                "COUNT(*) AS count "
                "FROM knowledge_gaps "
                "WHERE created_at >= NOW() - INTERVAL '14 days' "
                "GROUP BY day ORDER BY day"
            )
            by_day = [
                {"date": row["day"], "count": row["count"]}
                for row in cur.fetchall()
            ]

            cur.execute(
                "SELECT COUNT(*) AS n FROM knowledge_gaps "
                "WHERE confidence IS NULL OR confidence < 0.5"
            )
            low_confidence = cur.fetchone()["n"] or 0

    return {
        "total_gaps": total,
        "by_intent": by_intent,
        "by_day": by_day,
        "low_confidence_count": low_confidence,
    }
