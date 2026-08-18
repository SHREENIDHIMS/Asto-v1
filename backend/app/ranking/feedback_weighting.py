"""Feedback-weighted ranking (J3).

Wires positive/negative user feedback into the retrieval order. Per
CLAUDE.md rule 7, the boost is configuration (`RankingWeights.feedback_boost`,
default 0.0 = disabled, identical to baseline), not a constant. The
aggregation query counts per-document positive/negative feedback from
``feedback`` rows attributed through ``audit_log`` (``response_id`` →
``retrieved_ids`` → ``documents``).

The variant scoring is a pure function so it is unit-testable and so the
benchmark (evaluation/compare_rankings.py) can compare it against the
baseline ordering with a before/after report.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from app.ranking.weights_config import DEFAULT_WEIGHTS, RankingWeights

if TYPE_CHECKING:
    from app.ranking.rrf import RankedCandidate


def feedback_weighted_score(
    bm25_score: float,
    vec_score: float,
    doc_ratio: float,
    boost: float,
    weights: RankingWeights = DEFAULT_WEIGHTS,
) -> float:
    """Linear combination score scaled by a per-document feedback boost.

    ``doc_ratio`` is in [0, 1]: 1.0 = all positive feedback, 0.0 = no /
    all-negative. With ``boost`` (feedback_boost) the multiplier is
    ``1 + boost * ratio`` — so a doc with perfect feedback and boost 0.3
    is ranked ~30% higher than its lexical+vector score alone. At
    ``boost == 0`` (the default) this reduces exactly to the baseline
    linear score, keeping the comparison apples-to-apples.
    """
    linear = weights.bm25_weight * float(bm25_score) + weights.vector_weight * float(vec_score)
    multiplier = 1.0 + float(boost) * float(doc_ratio)
    return linear * multiplier


def compute_doc_feedback_ratios(conn) -> dict[int, float]:
    """Aggregate per-document positive/negative feedback from real data.

    A document "receives" a response's rating when it appears in that
    response's ``audit_log.retrieved_ids`` and the response was answered
    (outcome IN (answer, partial)). Returns ``{doc_id: ratio}`` where
    ratio = positive / (positive + negative), 0.0 when no feedback.
    """
    with conn.cursor() as cur:
        cur.execute(
            "WITH doc_resp AS ( "
            "  SELECT d.id AS doc_id, fb.rating "
            "  FROM audit_log a "
            "  JOIN LATERAL unnest(a.retrieved_ids) AS rid ON TRUE "
            "  JOIN documents d ON d.id = rid "
            "  JOIN feedback fb ON fb.response_id = a.response_id "
            "  WHERE a.outcome IN ('answer', 'partial') "
            "    AND a.retrieved_ids IS NOT NULL "
            ") "
            "SELECT doc_id, "
            "  COUNT(*) FILTER (WHERE rating = 1) AS positive_count, "
            "  COUNT(*) FILTER (WHERE rating = -1) AS negative_count "
            "FROM doc_resp GROUP BY doc_id"
        )
        ratios: dict[int, float] = {}
        for row in cur.fetchall():
            pos = int(row["positive_count"] or 0)
            neg = int(row["negative_count"] or 0)
            total = pos + neg
            ratios[int(row["doc_id"])] = (pos / total) if total else 0.0
        return ratios


def apply_feedback_weighted_reorder(
    ranked: Sequence["RankedCandidate"],
    doc_ratios: dict[int, float],
    boost: float | None = None,
    weights: RankingWeights = DEFAULT_WEIGHTS,
) -> list["RankedCandidate"]:
    """Re-sort fused candidates by the feedback-weighted score.

    The `RankedCandidate` objects are returned in a new order (the objects
    themselves are not mutated); `combined_rank` is refreshed to match.
    """
    if boost is None:
        boost = weights.feedback_boost

    scored = [
        (c, feedback_weighted_score(
            c.bm25_score, c.vec_score,
            doc_ratios.get(c.document_id, 0.0),
            boost, weights,
        ))
        for c in ranked
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    ordered = [c for c, _ in scored]
    for i, c in enumerate(ordered):
        c.combined_rank = i + 1
    return ordered
