"""Scoring: apply configurable weights to combine BM25 + vector scores.

Reads weights from ranking/weights_config.py (config, not constants).
This is a simpler linear combination that can be used as an alternative
to RRF or as a secondary signal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from app.ranking.weights_config import DEFAULT_WEIGHTS, RankingWeights

if TYPE_CHECKING:
    from app.ranking.rrf import RankedCandidate


def compute_scores(
    candidates: Sequence[dict],
    weights: RankingWeights = DEFAULT_WEIGHTS,
) -> list[tuple[int, float]]:
    """Apply weighted linear combination to candidate scores.

    Each candidate dict must have 'chunk_id', 'bm25_score', and 'vec_score'.
    Returns list of (chunk_id, combined_score) sorted descending.
    """
    scored: list[tuple[int, float]] = []

    for c in candidates:
        bm25 = float(c.get("bm25_score", 0.0) or 0.0)
        vec = float(c.get("vec_score", 0.0) or 0.0)
        # NaN safety: a NaN vector score would make the weighted sum NaN and
        # sort NaN above every real candidate. Coerce to 0.
        if bm25 != bm25:
            bm25 = 0.0
        if vec != vec:
            vec = 0.0
        score = (
            weights.bm25_weight * bm25
            + weights.vector_weight * vec
        )
        scored.append((c["chunk_id"], score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def apply_linear_reorder(
    ranked: Sequence["RankedCandidate"],
    weights: RankingWeights = DEFAULT_WEIGHTS,
) -> list["RankedCandidate"]:
    """Re-sort already-fused candidates by the weighted linear score.

    Used after RRF fusion so the final list order reflects the
    benchmark-verified weighted combination (weights_config.py) while the
    RRF score field stays intact for confidence/routing (it is scale-
    independent). Returns the same objects, re-ordered, with
    ``combined_rank`` refreshed.
    """
    ordered = list(ranked)
    ordered.sort(
        key=lambda c: weights.bm25_weight * float(c.bm25_score)
        + weights.vector_weight * float(c.vec_score),
        reverse=True,
    )
    for i, c in enumerate(ordered):
        c.combined_rank = i + 1
    return ordered
