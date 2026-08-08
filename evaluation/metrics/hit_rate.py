"""Hit rate metric — did the relevant doc appear in the top-k?"""

from __future__ import annotations

from typing import Sequence


def hit_at_k(retrieved_ids: Sequence[int], relevant_ids: set[int], k: int) -> bool:
    """Returns True if any relevant doc is in the top-k."""
    if len(relevant_ids) == 0:
        return True  # vacuous truth — no relevant docs means nothing to miss
    top_k = set(retrieved_ids[:k])
    return bool(top_k & relevant_ids)


def hit_rate(rank_lists: list[Sequence[int]], relevant_sets: list[set[int]], k: int = 10) -> float:
    """Hit rate across multiple queries at cutoff k."""
    if len(rank_lists) == 0:
        return 0.0
    hits = sum(hit_at_k(r, r_set, k) for r, r_set in zip(rank_lists, relevant_sets))
    return hits / len(rank_lists)
