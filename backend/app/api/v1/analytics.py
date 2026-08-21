"""Analytics endpoints for admin review."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.permissions import require_role
from app.dependencies import require_auth
from app.db.postgres import session

router = APIRouter()


@router.get("/knowledge-gaps")
async def knowledge_gaps(
    user: dict = Depends(require_auth),
    limit: int = 50,
) -> dict:
    """View low-confidence / no-answer queries. Requires admin role."""
    require_role(user, "admin")

    with session.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, query, intent, confidence, created_at "
                "FROM knowledge_gaps ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
            gaps = [dict(row) for row in cur.fetchall()]

    return {"knowledge_gaps": gaps}


    return {
        "total_gaps": total,
        "by_intent": by_intent,
        "by_day": by_day,
        "low_confidence_count": low_confidence,
    }


@router.get("/gap-topics")
async def gap_topics(
    user: dict = Depends(require_auth),
    window_days: int = 30,
    min_queries: int = 3,
) -> dict:
    """Recurring unanswered topics across recent knowledge gaps.

    Deterministic token clustering over ``knowledge_gaps`` — every sample
    query is verbatim from the log. Requires admin role.
    """
    require_role(user, "admin")

    from app.knowledge_gap.topics import TopicConfig, cluster_gap_topics

    window_days = max(1, min(window_days, 365))
    min_queries = max(2, min(min_queries, 50))

    with session.acquire() as conn:
        report = cluster_gap_topics(
            conn,
            TopicConfig(window_days=window_days, min_queries=min_queries),
        )
    return report


@router.get("/content-coverage")
async def content_coverage(
    user: dict = Depends(require_auth),
) -> dict:
    """Where the knowledge base is thin: per (department, doc_type)
    approved-document and chunk counts, thinnest first, plus cells that
    have no approved documents at all. Requires admin role."""
    require_role(user, "admin")

    from app.documents.coverage import build_coverage_report

    with session.acquire() as conn:
        return build_coverage_report(conn)


# J6 — document popularity analytics
_WEAK_OUTCOMES_SQL = "'no_answer', 'partial'"
_ANSWERED_OUTCOMES_SQL = "'answer', 'partial'"


def _document_popularity_rows(conn, limit: int) -> list[dict]:
    """Per-document retrieval + feedback stats from audit_log.

    A document is "hit" when it appears in an audit row's ``retrieved_ids``.
    ``answer_count`` = hits on answered/partial responses; ``no_answer_count``
    = hits on no-answer responses. Feedback is attributed per response, so each
    document that was retrieved by a response inherits that response's rating —
    this lets us rank docs by how positively the answers they supported were
    received.

    Base stats and feedback counts are aggregated in two separate grouped
    subqueries and joined, so the response→doc fan-out never double-counts
    the base columns.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH hit AS (
              SELECT d.id AS doc_id, d.title, d.department,
                     a.user_id, a.outcome, a.response_id
              FROM audit_log a
              JOIN LATERAL unnest(a.retrieved_ids) AS rid ON TRUE
              JOIN documents d ON d.id = rid
              WHERE a.retrieved_ids IS NOT NULL
                AND a.outcome IN ({_ANSWERED_OUTCOMES_SQL}, 'no_answer')
                AND a.created_at >= now() - interval '30 days'
            ),
            doc_resp AS (
              SELECT h.doc_id, h.response_id
              FROM hit h
              WHERE h.outcome IN ({_ANSWERED_OUTCOMES_SQL})
              GROUP BY h.doc_id, h.response_id
            ),
            fb_count AS (
              SELECT h.doc_id,
                     COUNT(*) FILTER (WHERE h.outcome IN ({_ANSWERED_OUTCOMES_SQL})) AS answer_count,
                     COUNT(*) FILTER (WHERE h.outcome = 'no_answer') AS no_answer_count,
                     COUNT(DISTINCT h.user_id) FILTER (
                       WHERE h.user_id IS NOT NULL
                         AND h.outcome IN ({_ANSWERED_OUTCOMES_SQL})
                     ) AS distinct_users
              FROM hit h
              GROUP BY h.doc_id
            ),
            feedback_count AS (
              SELECT dr.doc_id,
                     COUNT(p.id) FILTER (WHERE p.rating = 1) AS positive_count,
                     COUNT(p.id) FILTER (WHERE p.rating = -1) AS negative_count
              FROM doc_resp dr
              JOIN feedback p ON p.response_id = dr.response_id
              GROUP BY dr.doc_id
            )
            SELECT f.doc_id AS doc_id, h.title, h.department,
                   f.answer_count, f.no_answer_count, f.distinct_users,
                   COALESCE(fc.positive_count, 0) AS positive_count,
                   COALESCE(fc.negative_count, 0) AS negative_count
            FROM fb_count f
            JOIN documents h ON h.id = f.doc_id
            LEFT JOIN feedback_count fc ON fc.doc_id = f.doc_id
            WHERE f.answer_count > 0 OR f.no_answer_count > 0
            ORDER BY f.answer_count DESC, f.no_answer_count DESC
            LIMIT %s
            """,
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]


def _rank_popularity(rows: list[dict]) -> dict:
    """Pure helper: rank docs into top + underperforming.

    - ``top_documents``: by answer_count (most answered), then positive ratio.
    - ``underperforming``: docs that answered queries (answer_count > 0) but
      have a negative review, or no-answer hits outnumbering answers with
      few answers.
    """
    ranked = []
    for r in rows:
        pos = int(r["positive_count"] or 0)
        neg = int(r["negative_count"] or 0)
        total_reviews = pos + neg
        positive_ratio = (pos / total_reviews) if total_reviews else 0.0
        ranked.append({
            "doc_id": int(r["doc_id"]),
            "title": r["title"],
            "department": r["department"],
            "answer_count": int(r["answer_count"] or 0),
            "no_answer_count": int(r["no_answer_count"] or 0),
            "distinct_users": int(r["distinct_users"] or 0),
            "positive_count": pos,
            "negative_count": neg,
            "positive_ratio": round(positive_ratio, 3),
        })

    top = sorted(
        ranked,
        key=lambda d: (d["answer_count"], d["positive_ratio"]),
        reverse=True,
    )

    underperforming = [
        d for d in ranked
        if d["answer_count"] > 0
        and (
            (d["negative_count"] > 0 and d["positive_ratio"] < 0.5)
            or (d["no_answer_count"] >= d["answer_count"] and d["answer_count"] <= 2)
        )
    ]

    return {"top_documents": top, "underperforming_documents": underperforming}


@router.get("/document-popularity")
async def document_popularity(
    user: dict = Depends(require_auth),
    limit: int = 20,
) -> dict:
    """Per-document retrieval + feedback stats (admin only).

    Aggregates audit_log (query → retrieved document ids) and feedback
    (response_id) into per-document answered-query counts, distinct users,
    and positive/negative review ratio. Supports J6 "Top documents by
    answers" and "Underperforming docs" charts.
    """
    require_role(user, "admin")

    with session.acquire() as conn:
        rows = _document_popularity_rows(conn, limit)
    return _rank_popularity(rows)


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

    with session.acquire() as conn:
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
