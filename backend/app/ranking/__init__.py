"""Ranking package: RRF fusion, scoring, and optional cross-encoder reranker.

Ranking weights and confidence thresholds are configuration, not
constants (CLAUDE.md rule 7).
"""

from app.ranking.rrf import rank_fusion
from app.ranking.scoring import compute_scores
from app.ranking.weights_config import RankingWeights, DEFAULT_WEIGHTS

__all__ = ["rank_fusion", "compute_scores", "RankingWeights", "DEFAULT_WEIGHTS"]
