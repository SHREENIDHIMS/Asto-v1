"""Ranking weights configuration.

Ranking weights are configuration, not constants (CLAUDE.md rule 7).
Defaults are benchmark-verified: evaluation/compare_rankings.py ran a
weight sweep over the 125-query dataset (report in evaluation/reports/).
0.2/0.8 beat the previous 0.3/0.7 and RRF on hit_rate@1 (100% vs 97.6% /
95.2%), MRR (96.8% vs 95.6% / 94.4%) with comparable nDCG@10 (90.4% vs
90.6% / 88.8%). Any further change must be backed by the same comparison.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RankingWeights:
    bm25_weight: float = 0.2
    vector_weight: float = 0.8
    top_k: int = 25


DEFAULT_WEIGHTS = RankingWeights()
