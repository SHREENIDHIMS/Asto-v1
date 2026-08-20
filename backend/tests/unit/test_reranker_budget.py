"""Unit tests for reranker latency budget + pipeline caching (rule #6).

Covers: the <200ms p95 budget helpers (``check_reranker_budget`` /
``check_cold_start_budget``), the reranker's disabled/missing-transformers
fallbacks, and the per-process pipeline cache (model loaded once, rebuilt
only when ``rerank_model_dir`` changes) that makes the budget enforceable.
"""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

import app.ranking.reranker as reranker_mod
from evaluation.metrics.latency_benchmark import (
    check_cold_start_budget,
    check_reranker_budget,
)

CANDIDATES = [{"chunk_id": i + 1, "content": f"test content {i}"} for i in range(10)]


class _FakeScorer:
    def __call__(self, pairs, top_k):
        return [{"score": 1.0 - i * 0.1} for i in range(top_k)]


@contextmanager
def _fake_transformers(pipe=None):
    """Provide a fake ``transformers`` module whose ``pipeline`` is a mock.

    ``transformers`` is not a runtime dependency (the reranker is OFF by
    default), so tests inject a stand-in module rather than patch an
    unimportable target.
    """
    fake_tf = types.ModuleType("transformers")
    fake_tf.pipeline = pipe if pipe is not None else MagicMock(return_value=_FakeScorer())
    with patch.dict(sys.modules, {"transformers": fake_tf}):
        yield fake_tf.pipeline


@pytest.fixture(autouse=True)
def _reset_pipeline_cache():
    reranker_mod._scorer = None
    reranker_mod._scorer_model = None
    yield
    reranker_mod._scorer = None
    reranker_mod._scorer_model = None


class TestRerankerBudget:
    def test_p95_under_200ms_passes(self):
        assert check_reranker_budget([100, 150, 180]) is True

    def test_p95_over_200ms_fails(self):
        assert check_reranker_budget([100, 250, 300]) is False

    def test_no_samples_passes(self):
        assert check_reranker_budget([]) is True

    def test_cold_start_under_10s_passes(self):
        assert check_cold_start_budget([5000]) is True

    def test_cold_start_over_10s_fails(self):
        assert check_cold_start_budget([15000]) is False


class TestRerankFallbacks:
    def test_disabled_returns_candidates_without_loading_model(self):
        with (
            patch.object(reranker_mod.settings, "rerank_enabled", False),
            _fake_transformers() as pipe,
        ):
            out = reranker_mod.rerank("q", CANDIDATES, top_k=3)
        pipe.assert_not_called()
        assert out == CANDIDATES[:3]

    def test_missing_transformers_falls_back_to_rrf(self):
        with (
            patch.object(reranker_mod.settings, "rerank_enabled", True),
            patch.dict(sys.modules, {"transformers": None}),
        ):
            out = reranker_mod.rerank("q", CANDIDATES, top_k=3)
        assert out == CANDIDATES[:3]

    def test_empty_candidates_returns_empty(self):
        with patch.object(reranker_mod.settings, "rerank_enabled", True):
            assert reranker_mod.rerank("q", []) == []


class TestRerankPipelineCache:
    def test_rerank_sorts_by_score_descending(self):
        with (
            patch.object(reranker_mod.settings, "rerank_enabled", True),
            _fake_transformers(),
        ):
            out = reranker_mod.rerank("q", CANDIDATES, top_k=3)
        assert out == sorted(
            CANDIDATES[:3],
            key=lambda c: c.get("rerank_score", 0.0),
            reverse=True,
        )
        assert out[0]["chunk_id"] == 1

    def test_pipeline_built_once_across_calls(self):
        with (
            patch.object(reranker_mod.settings, "rerank_enabled", True),
            _fake_transformers() as pipe,
        ):
            reranker_mod.rerank("q1", CANDIDATES, top_k=3)
            reranker_mod.rerank("q2", CANDIDATES, top_k=3)
            reranker_mod.rerank("q3", CANDIDATES, top_k=3)
        pipe.assert_called_once()

    def test_pipeline_rebuilt_when_model_dir_changes(self):
        with (
            patch.object(reranker_mod.settings, "rerank_enabled", True),
            _fake_transformers() as pipe,
        ):
            with patch.object(reranker_mod.settings, "rerank_model_dir", "model_a"):
                reranker_mod.rerank("q", CANDIDATES, top_k=3)
            with patch.object(reranker_mod.settings, "rerank_model_dir", "model_b"):
                reranker_mod.rerank("q", CANDIDATES, top_k=3)
        assert pipe.call_count == 2