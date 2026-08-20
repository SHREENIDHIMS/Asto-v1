"""Cross-encoder reranker using ONNX Int8 quantized model.

Scores only the top-10 RRF candidates to stay within the <200ms p95
latency budget (CLAUDE.md rule #6). The scoring pipeline is loaded once per
process and cached (rebuilt only if ``rerank_model_dir`` changes), so the
budget is enforceable instead of paying a full model load on every request.
"""

from __future__ import annotations

import logging
from typing import Sequence

from app.config import settings

logger = logging.getLogger(__name__)

_scorer = None
_scorer_model: str | None = None


def _get_scorer():
    """Return the cached text-ranking pipeline, building it on first use.

    Rebuilds the pipeline only when ``rerank_model_dir`` changes so a single
    worker process pays the model load once instead of once per request.
    Returns ``None`` when ``transformers`` is unavailable, leaving the caller
    to fall back to RRF scores.
    """
    global _scorer, _scorer_model
    if _scorer is not None and _scorer_model == settings.rerank_model_dir:
        return _scorer
    try:
        from transformers import pipeline  # type: ignore
    except ImportError:
        logger.warning("transformers not installed; reranker disabled, falling back to RRF scores")
        return None
    _scorer = pipeline(
        "text-ranking",
        model=settings.rerank_model_dir,
        device=-1,
    )
    _scorer_model = settings.rerank_model_dir
    return _scorer


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

    top_candidates = list(candidates)[:top_k]

    try:
        scorer = _get_scorer()
        if scorer is None:
            return top_candidates
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