"""Precision and recall metrics for retrieval evaluation."""

from __future__ import annotations

from typing import Sequence


def precision_at_k(retrieved_ids: Sequence[int], relevant_ids: set[int], k: int) -> float:
    """Precision@k: fraction of top-k retrieved docs that are relevant."""
    if k == 0 or len(retrieved_ids) == 0:
        return 0.0
    top_k = retrieved_ids[:k]
    hits = sum(1 for doc_id in top_k if doc_id in relevant_ids)
    return hits / k


def recall_at_k(retrieved_ids: Sequence[int], relevant_ids: set[int], k: int) -> float:
    """Recall@k: fraction of relevant docs found in top-k."""
    if len(relevant_ids) == 0:
        return 1.0
    top_k = retrieved_ids[:k]
    hits = sum(1 for doc_id in top_k if doc_id in relevant_ids)
    return hits / len(relevant_ids)


def accuracy_at_k(retrieved_ids: Sequence[int], relevant_ids: set[int], k: int) -> float:
    """Accuracy@k: any relevant doc in top-k."""
    if len(relevant_ids) == 0:
        return 1.0
    top_k = retrieved_ids[:k]
    return 1.0 if any(doc_id in relevant_ids for doc_id in top_k) else 0.0


def mean_precision(retrieved_ids: Sequence[int], relevant_ids: set[int]) -> float:
    """Mean precision across all cutoffs (for non-dcg use)."""
    if len(retrieved_ids) == 0:
        return 0.0
    hits = 0
    total = 0
    for i, doc_id in enumerate(retrieved_ids):
        if doc_id in relevant_ids:
            hits += 1
            total += hits / (i + 1)
    return total / len(retrieved_ids) if retrieved_ids else 0.0
