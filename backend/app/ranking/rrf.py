"""Reciprocal Rank Fusion (RRF) — combines BM25 and vector rankings.

RRF is chosen for its simplicity and parameter-free nature on micro-tier
hardware. Each candidate's final score is:

    score = sum(1 / (k + rank_i))  for each result list i

where k is the RRF constant (default 60) and rank_i is the position
(1-indexed) of the candidate in list i.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass
class RankedCandidate:
    chunk_id: int
    document_id: int
    content: str
    title: str
    section: str | None
    chunk_type: str
    department: str
    bm25_score: float
    vec_score: float
    rrf_score: float
    combined_rank: int
    is_approved: bool
    document_version: int
    client_id: int | None = None


RRF_K: int = 60  # standard RRF constant


def rank_fusion(
    bm25_ranked: Sequence[tuple[int, float]],
    vector_ranked: Sequence[tuple[int, float]],
    chunk_lookup: dict[int, dict],
    k: int = RRF_K,
) -> list[RankedCandidate]:
    """Fuse two ranked lists using RRF.

    Args:
        bm25_ranked: list of (chunk_id, bm25_score) in descending score order
        vector_ranked: list of (chunk_id, vec_score) in descending score order
        chunk_lookup: dict mapping chunk_id -> chunk metadata dict
        k: RRF constant (higher = flatter curve)

    Returns:
        List of RankedCandidate sorted by RRF score descending.
    """
    ranks: dict[int, dict] = {}

    for rank, (cid, score) in enumerate(bm25_ranked, start=1):
        if cid not in ranks:
            ranks[cid] = {"bm25_score": score, "vec_score": 0.0, "bm25_rank": rank, "vec_rank": 9999}
        else:
            ranks[cid]["bm25_score"] = score
            ranks[cid]["bm25_rank"] = rank

    for rank, (cid, score) in enumerate(vector_ranked, start=1):
        if cid not in ranks:
            ranks[cid] = {"bm25_score": 0.0, "vec_score": score, "bm25_rank": 9999, "vec_rank": rank}
        else:
            ranks[cid]["vec_score"] = score
            ranks[cid]["vec_rank"] = rank

    results: list[RankedCandidate] = []
    for cid, r in ranks.items():
        rrf_score = (1.0 / (k + r["bm25_rank"])) + (1.0 / (k + r["vec_rank"]))
        meta = chunk_lookup.get(cid, {})
        results.append(RankedCandidate(
            chunk_id=cid,
            content=meta.get("content", ""),
            document_id=meta.get("document_id", 0),
            title=meta.get("title", ""),
            section=meta.get("section"),
            chunk_type=meta.get("chunk_type", "paragraph"),
            department=meta.get("department", ""),
            client_id=meta.get("client_id"),
            bm25_score=r["bm25_score"],
            vec_score=r["vec_score"],
            rrf_score=rrf_score,
            combined_rank=0,
            is_approved=meta.get("is_approved", True),
            document_version=meta.get("document_version", 1),
        ))

    results.sort(key=lambda c: c.rrf_score, reverse=True)
    for i, c in enumerate(results):
        c.combined_rank = i + 1

    return results
