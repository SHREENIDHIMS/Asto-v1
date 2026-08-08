"""Cross-encoder reranker using ONNX Int8 quantized model.

Scores only the top-10 RRF candidates to stay within the <200ms p95
latency budget (CLAUDE.md rule #6).
"""

from __future__ import annotations

import logging
from typing import Sequence

from app.config import settings

logger = logging.getLogger(__name__)


def rerank(
    query: str,
    candidates: Sequence[dict],
    top_k: int = 10,
) -> list[dict]:
    """Re-rank the top-k candidates using a cross-encoder model.

    Args:
        query: The original user query string.
        candidates: List of candidate dicts with 'chunk_id' and 'content'.
        top_k: Number of candidates to re-rank (default 10).

    Returns:
        List of candidates sorted by cross-encoder score descending.
    """
    if not settings.rerank_enabled or not candidates:
        return list(candidates)[:top_k]

    try:
        from transformers import pipeline  # type: ignore
    except ImportError:
        logger.warning("transformers not installed; reranker disabled, falling back to RRF scores")
        return list(candidates)[:top_k]

    top_candidates = list(candidates)[:top_k]

    try:
        scorer = pipeline(
            "text-ranking",
            model=settings.rerank_model_dir,
            device=-1,
        )
        pairs = [{"query": query, "passage": c.get("content", "")} for c in top_candidates]
        scores = scorer(pairs, top_k=top_k)

        for i, score_entry in enumerate(scores):
            if i < len(top_candidates):
                top_candidates[i]["rerank_score"] = score_entry["score"]
    except Exception as exc:
        logger.warning("Reranking failed, falling back to RRF scores: %s", exc)
        return top_candidates

    top_candidates.sort(key=lambda c: c.get("rerank_score", 0.0), reverse=True)
    return top_candidates