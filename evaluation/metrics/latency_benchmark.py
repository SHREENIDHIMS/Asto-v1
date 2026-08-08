"""Latency benchmark for the reranker and overall pipeline.

Per CLAUDE.md rule #6: cross-encoder reranking has a <200ms p95 latency budget.
This module measures reranker latency and overall search latency.
"""

from __future__ import annotations

import time
from typing import Sequence

import numpy as np


def measure_latency(func, *args, **kwargs) -> float:
    """Run func once and return wall-clock latency in milliseconds."""
    start = time.perf_counter()
    func(*args, **kwargs)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return elapsed_ms


def percentile_latencies(latencies: Sequence[float], percentiles: Sequence[float]) -> dict[float, float]:
    """Compute percentile latencies from a list of millisecond values."""
    if len(latencies) == 0:
        return {p: 0.0 for p in percentiles}
    arr = np.array(latencies)
    return {p: float(np.percentile(arr, p)) for p in percentiles}


def check_reranker_budget(latencies: Sequence[float]) -> bool:
    """Verify reranker p95 latency is under 200ms (CLAUDE.md rule #6)."""
    if len(latencies) == 0:
        return True
    p95 = percentile_latencies(latencies, [95])[95]
    return p95 < 200.0


def check_cold_start_budget(latencies: Sequence[float]) -> bool:
    """Verify cold-start latency is under 10s (acceptable for low-traffic)."""
    if len(latencies) == 0:
        return True
    p95 = percentile_latencies(latencies, [95])[95]
    return p95 < 10000.0


def benchmark_reranker(rerank_fn, queries: list[str], topk: list[list[dict]]) -> dict:
    """Benchmark the reranker across queries.

    Args:
        rerank_fn: callable(query_str, candidates) -> ranked_candidates
        queries: list of query strings
        topk: list of candidate lists (one per query)

    Returns:
        {'latencies_ms': [...], 'p50': ..., 'p95': ..., 'budget_ok': bool}
    """
    latencies = []
    for query, candidates in zip(queries, topk):
        if not candidates:
            continue
        lat = measure_latency(rerank_fn, query, candidates)
        latencies.append(lat)

    percentiles = percentile_latencies(latencies, [50, 95, 99])
    return {
        "latencies_ms": latencies,
        "p50": percentiles[50],
        "p95": percentiles[95],
        "p99": percentiles[99],
        "budget_ok": check_reranker_budget(latencies) if latencies else True,
    }
