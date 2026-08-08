"""Mean Reciprocal Rank (MRR) metric."""

from __future__ import annotations

from typing import Sequence


def reciprocal_rank(retrieved_ids: Sequence[int], relevant_ids: set[int]) -> float:
    """Reciprocal rank: 1/rank_of_first_relevant_doc, or 0 if none found."""
    for i, doc_id in enumerate(retrieved_ids):
        if doc_id in relevant_ids:
            return 1.0 / (i + 1)
    return 0.0


def mean_reciprocal_rank(rank_lists: list[Sequence[int]], relevant_sets: list[set[int]]) -> float:
    """MRR across multiple queries."""
    if len(rank_lists) == 0:
        return 0.0
    rrs = [reciprocal_rank(r, r_set) for r, r_set in zip(rank_lists, relevant_sets)]
    return sum(rrs) / len(rrs)
