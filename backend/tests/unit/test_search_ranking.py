"""Unit tests for search and ranking modules."""

from __future__ import annotations

from app.ranking.rrf import rank_fusion
from app.ranking.scoring import apply_linear_reorder, compute_scores
from app.ranking.weights_config import DEFAULT_WEIGHTS, RankingWeights
from app.search.bm25_search import build_tsquery, has_lexical_terms
from app.search.metadata_filters import get_search_filter, get_version_filter


class TestBM25Search:
    def test_build_tsquery_simple(self):
        q = build_tsquery("credit score requirements")
        assert "credit" in q
        assert "score" in q
        assert "requirements" in q

    def test_build_tsquery_strips_punctuation(self):
        q = build_tsquery("max LTV? for investment properties!")
        assert "ltv" in q
        assert "investment" in q
        assert "properties" in q

    def test_build_tsquery_empty(self):
        q = build_tsquery("")
        assert q == "''::tsquery"

    def test_has_lexical_terms_ascii(self):
        assert has_lexical_terms("credit score")
        assert has_lexical_terms("  FHA 30% loan  ")

    def test_has_lexical_terms_rejects_non_ascii(self):
        assert not has_lexical_terms("")
        assert not has_lexical_terms("??? !!! ---")
        assert not has_lexical_terms("मोर्टगेज दर")  # Devanagari only
        assert not has_lexical_terms("貸款 利率")      # Han only
        assert not has_lexical_terms("ипотека")       # Cyrillic only

    def test_search_skips_non_ascii_query(self):
        """A non-Latin query must return no candidates (graceful no_answer)
        instead of feeding an empty tsquery into to_tsquery (SQL error -> 500)."""
        from unittest.mock import MagicMock

        from app.search.hybrid_orchestrator import search_knowledge_base

        result = search_knowledge_base(MagicMock(), ["मोर्टगेज दर"], user=None)
        assert result.candidates == []
        assert result.query_embedding == []


class TestMetadataFilters:
    def test_admin_returns_no_filter(self):
        clause, params = get_search_filter({
            "role": "super_admin",
            "department": "general",
        })
        assert clause == ""
        assert params == []

    def test_loan_officer_filters_departments(self):
        clause, params = get_search_filter({
            "role": "loan_officer",
            "department": "general",
            "allowed_departments": ["compliance"],
        })
        assert "department" in clause
        assert "general" in params
        assert "compliance" in params

    def test_no_user_denies_all(self):
        """When user is None (unauthenticated), the RBAC filter must
        deny all access — get_search_filter returns '1=0' so no rows
        can ever pass the WHERE clause."""
        clause, params = get_search_filter(None)
        # Clause should contain '1=0' (always false) or an equivalent
        # always-false condition that ensures no results return
        assert clause != ""
        assert "1=0" in clause or "false" in clause.lower() or "= 0" in clause

    def test_version_filter(self):
        clause, params = get_version_filter()
        assert "is_active" in clause
        assert "is_approved" in clause

    def test_version_filter_inactive(self):
        clause, _ = get_version_filter(is_active=False)
        assert "is_active" not in clause


class TestRRF:
    def test_rrf_combines_ranks(self):
        bm25_ranked = [(1, 0.9), (2, 0.5)]
        vector_ranked = [(2, 0.95), (1, 0.8)]
        chunk_lookup = {
            1: {"content": "doc1", "title": "Doc1", "section": None, "chunk_type": "paragraph", "department": "general"},
            2: {"content": "doc2", "title": "Doc2", "section": None, "chunk_type": "paragraph", "department": "general"},
        }
        results = rank_fusion(bm25_ranked, vector_ranked, chunk_lookup)

        assert len(results) == 2
        assert results[0].chunk_id in (1, 2)
        # Both should have rrf_score > 0
        assert all(r.rrf_score > 0 for r in results)
        # Results should be sorted by rrf_score descending
        scores = [r.rrf_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_rrf_handles_empty_lists(self):
        results = rank_fusion([], [], {}, k=60)
        assert len(results) == 0


class TestScoring:
    def test_compute_scores_weighted(self):
        candidates = [
            {"chunk_id": 1, "bm25_score": 0.8, "vec_score": 0.9},
            {"chunk_id": 2, "bm25_score": 0.3, "vec_score": 0.4},
        ]
        weights = RankingWeights(bm25_weight=0.5, vector_weight=0.5)
        scored = compute_scores(candidates, weights)

        assert len(scored) == 2
        assert scored[0][0] == 1  # higher score first
        assert scored[1][0] == 2

    def test_compute_scores_default_weights(self):
        candidates = [
            {"chunk_id": 1, "bm25_score": 1.0, "vec_score": 0.0},
            {"chunk_id": 2, "bm25_score": 0.0, "vec_score": 1.0},
        ]
        scored = compute_scores(candidates)
        # Default: bm25 0.2, vector 0.8 → vec wins
        assert scored[0][0] == 2

    def test_compute_scores_coerces_nan_to_zero(self):
        candidates = [
            {"chunk_id": 1, "bm25_score": 0.9, "vec_score": float("nan")},
            {"chunk_id": 2, "bm25_score": 0.5, "vec_score": 0.6},
        ]
        scored = compute_scores(candidates, RankingWeights(bm25_weight=0.5, vector_weight=0.5))
        # NaN coerced to 0: 0.45 vs 0.55 → candidate 2 wins, never NaN.
        assert scored[0][0] == 2
        assert scored[0][1] == scored[0][1]  # not NaN


class TestLinearReorder:
    """apply_linear_reorder re-sorts fused candidates by weighted score.

    Default weights are 0.2 bm25 / 0.8 vector (benchmark-verified in
    evaluation/compare_rankings.py), so vector-dominant candidates win
    ties, but a strong BM25 candidate can still rank first.
    """

    def _candidates(self):
        from app.ranking.rrf import RankedCandidate

        return [
            RankedCandidate(
                chunk_id=i, document_id=1, content=f"c{i}", title="t",
                section=None, chunk_type="paragraph", department="general",
                bm25_score=bm25, vec_score=vec, rrf_score=0.0, combined_rank=0,
                is_approved=True, document_version=1,
            )
            for i, (bm25, vec) in enumerate([
                (0.3, 0.8),   # 0: 0.2*0.3+0.8*0.8 = 0.70
                (1.0, 0.5),   # 1: 0.2*1.0+0.8*0.5 = 0.60
                (0.1, 0.9),   # 2: 0.2*0.1+0.8*0.9 = 0.74 → winner
            ], start=1)
        ]

    def test_reorders_by_weighted_score(self):
        cands = self._candidates()
        ordered = apply_linear_reorder(cands)
        assert [c.chunk_id for c in ordered] == [3, 1, 2]

    def test_updates_combined_rank(self):
        cands = self._candidates()
        ordered = apply_linear_reorder(cands)
        assert [c.combined_rank for c in ordered] == [1, 2, 3]
