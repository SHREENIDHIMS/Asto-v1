"""Unit tests for J1 — search-result matched-term highlighting."""

from __future__ import annotations

from app.ranking.rrf import RankedCandidate
from app.response.package_builder import build_response_package
from app.search.matched_terms import matched_terms, query_terms


def _candidate(chunk_id: int, content: str, title: str = "Policy") -> RankedCandidate:
    return RankedCandidate(
        chunk_id=chunk_id,
        content=content,
        document_id=chunk_id,
        title=title,
        section=None,
        chunk_type="paragraph",
        department="general",
        bm25_score=0.8,
        vec_score=0.9,
        rrf_score=0.05,
        combined_rank=1,
        is_approved=True,
        document_version=1,
    )


class TestQueryTerms:
    def test_terms_are_lowercased_and_split(self):
        assert query_terms("Credit Score Requirements") == [
            "credit", "score", "requirements",
        ]

    def test_punctuation_stripped(self):
        assert query_terms("loan-to-value 80%!") == [
            "loan-to-value", "80",
        ]

    def test_empty_query(self):
        assert query_terms("   ") == []


class TestMatchedTerms:
    def test_returns_terms_that_appear_in_text(self):
        assert matched_terms(
            "credit score minimum",
            "The minimum credit score is 620.",
        ) == ["credit", "score", "minimum"]

    def test_omits_terms_not_in_text(self):
        assert matched_terms(
            "credit score mortgage",
            "The credit score is 620.",
        ) == ["credit", "score"]

    def test_case_insensitive_match(self):
        assert matched_terms("CREDIT", "low credit scores") == ["credit"]

    def test_no_substring_collision(self):
        """Short terms must not match inside longer words."""
        assert matched_terms("lo", "loan approval") == []

    def test_empty_text(self):
        assert matched_terms("credit", "") == []

    def test_stopwords_excluded(self):
        assert matched_terms(
            "what is the credit score for a loan",
            "what is the credit score for a loan",
        ) == ["credit", "score", "loan"]


class TestPackageBuilderMatchedTerms:
    def test_excerpts_carry_matched_terms(self):
        candidates = [
            _candidate(1, "The minimum credit score is 620."),
            _candidate(2, "The maximum loan amount is 80%."),
        ]
        package = build_response_package(
            candidates=candidates,
            query_text="credit score loan amount",
        )
        assert package.excerpts[0].matched_terms == ["credit", "score"]
        assert package.excerpts[1].matched_terms == ["loan", "amount"]

    def test_matched_terms_empty_without_overlap(self):
        candidates = [_candidate(1, "Appraisal guidelines here.")]
        package = build_response_package(
            candidates=candidates,
            query_text="tax credit",
        )
        assert package.excerpts[0].matched_terms == []

    def test_summary_sentences_carry_matched_terms(self):
        candidates = [
            _candidate(1, "A borrower needs a minimum credit score of 620 to qualify for a loan. "
                          "Higher scores receive better rates. Appraisal value is verified separately."),
            _candidate(2, "The credit score threshold applies to all new mortgage applications. "
                          "Existing customers keep their current terms. Loan sizing follows LTV limits."),
        ]
        package = build_response_package(
            candidates=candidates,
            query_text="credit score loan",
        )
        assert package.summary, "expected an extractive summary"
        for sentence in package.summary:
            assert isinstance(sentence.matched_terms, list)
            # Every reported term must actually appear in the sentence text.
            for term in sentence.matched_terms:
                assert term in sentence.text.lower()
