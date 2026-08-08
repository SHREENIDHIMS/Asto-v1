"""Knowledge gap detection.

Logs queries that result in low confidence or no answer, so the
content team can identify gaps in the knowledge base and prioritize
document ingestion.

Uses the no-answer threshold from response.confidence_thresholds
(the single source of truth for confidence routing, per CLAUDE.md rule 7).
"""

from __future__ import annotations

from app.db.postgres.session import acquire
from app.response.confidence_thresholds import DEFAULT_THRESHOLDS


def detect_and_log(
    query: str,
    intent: str | None = None,
    confidence: float | None = None,
) -> None:
    """Log a knowledge gap if confidence is below the no-answer threshold.

    A knowledge gap is any query where:
    - No documents were retrieved (confidence == 0), or
    - The confidence score is below the no-answer threshold
      (ConfidenceLevel.low, default 50)

    These are written to the knowledge_gaps table for analytics review.
    Never raises — gap detection must not break the request path.
    """
    threshold = DEFAULT_THRESHOLDS.low
    if confidence is not None and confidence >= threshold:
        return  # high enough confidence — not a gap

    try:
        with acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO knowledge_gaps (query, intent, confidence) "
                    "VALUES (%s, %s, %s)",
                    (query, intent, confidence),
                )
                conn.commit()
    except Exception:
        pass  # silently fail — gap detection is best-effort
