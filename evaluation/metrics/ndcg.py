"""Normalized Discounted Cumulative Gain (nDCG) metric."""

from __future__ import annotations

import math
from typing import Sequence


def discounted_cumulative_gain(retrieved_ids: Sequence[int], relevance_scores: dict[int, float]) -> float:
    """DCG: sum of (rel_i / log2(i+1)) for each retrieved item."""
    dcg = 0.0
    for i, doc_id in enumerate(retrieved_ids):
        rel = relevance_scores.get(doc_id, 0.0)
        dcg += rel / math.log2(i + 2)  # i+2 because i is 0-indexed, log2(1) = 0
    return dcg


def ideal_dcg(relevance_scores: dict[int, float], k: int) -> float:
    """IDCG: DCG of the ideal ranking."""
    sorted_scores = sorted(relevance_scores.values(), reverse=True)[:k]
    idcg = 0.0
    for i, score in enumerate(sorted_scores):
        if i == 0:
            idcg += score  # log2(2) = 1
        else:
            idcg += score / math.log2(i + 2)
    return idcg if idcg > 0 else 1.0


def ndcg_at_k(retrieved_ids: Sequence[int], relevance_scores: dict[int, float], k: int) -> float:
    """nDCG@k: normalized DCG at cutoff k."""
    if k == 0:
        return 0.0
    top_k = retrieved_ids[:k]
    dcg = discounted_cumulative_gain(top_k, relevance_scores)
    idcg = ideal_dcg(relevance_scores, k)
    return min(dcg / idcg, 1.0)
