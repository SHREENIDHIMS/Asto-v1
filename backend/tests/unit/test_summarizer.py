"""Unit tests for extractive summary generation (Sumy TextRank)."""

from __future__ import annotations

from app.response.package_builder import Excerpt, Source
from app.response.summarizer import summarize_excerpts


def _excerpt(text: str, title: str = "Doc", chunk_id: int = 1) -> Excerpt:
    return Excerpt(
        text=text,
        source=Source(
            chunk_id=chunk_id,
            document_id=1,
            title=title,
            section=None,
            chunk_type="paragraph",
            is_approved=True,
            document_version=1,
        ),
        confidence=90.0,
        bm25_score=0.9,
        vec_score=0.9,
    )


class TestSummarizeExcerpts:
    def test_empty_excerpts_returns_empty(self):
        assert summarize_excerpts([]) == []

    def test_returns_verbatim_sentences_from_source(self):
        excerpts = [
            _excerpt(
                "The minimum credit score for a VA loan is 620. "
                "Veterans must provide a Certificate of Eligibility. "
                "The funding fee is waived for disabled veterans.",
                title="VA Loan Guide",
                chunk_id=1,
            ),
            _excerpt(
                "The maximum loan term is 30 years. "
                "The maximum loan-to-value ratio is 100 percent.",
                title="VA Loan Guide",
                chunk_id=2,
            ),
        ]
        summary = summarize_excerpts(excerpts, sentences_count=4)
        assert len(summary) <= 4
        assert len(summary) >= 1
        for sentence in summary:
            assert sentence.text.strip()
            assert sentence.source_title == "VA Loan Guide"
            # every sentence must exist verbatim somewhere in the excerpts
            corpus = " ".join(e.text.lower() for e in excerpts)
            assert sentence.text.lower() in corpus

    def test_short_single_excerpt_degrades_gracefully(self):
        excerpts = [_excerpt("One short sentence here.", title="Short")]
        summary = summarize_excerpts(excerpts, sentences_count=4)
        assert isinstance(summary, list)
