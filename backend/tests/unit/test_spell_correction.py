"""Unit tests for spell correction module.

Covers:
- Misspelled domain terms are corrected
- Known acronyms are protected (never changed)
- Numbers, percentages, dollar amounts are never corrected
- Short tokens (<4 chars) are skipped
- Non-alpha tokens (digits, symbols, $) are skipped
- Glued word recovery (whatis → what is)
- Multi-word phrase repair (investmnt properti → investment properties)
- Regression test for infinite loop bug (credit score vs credit scores)
- Unknown words with no match are left as-is
- Empty input
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

# Ensure backend/app is importable
backend_path = Path(__file__).resolve().parent.parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from app.query_processing.spell_correction import correct


class TestBasicCorrection:
    """Misspelled domain terms should be corrected."""

    def test_minimum_credit_score_misspelled(self):
        result = correct("what is the minimun credt scor")
        assert "minimum" in result
        assert "score" in result

    def test_minimum_credit_score_correct(self):
        result = correct("what is the minimum credit score")
        assert result == "what is the minimum credit score"

    def test_investment_property_misspelled(self):
        result = correct("max ltv for investmnt properti")
        assert "investment" in result
        assert "properties" in result or "property" in result

    def test_documents_required_misspelled(self):
        result = correct("what documnts are requred")
        assert "documents" in result
        assert "required" in result


class TestProtectedTokens:
    """Known acronyms, numbers, and short tokens are never changed."""

    def test_acronym_ltv_not_corrected(self):
        result = correct("max ltv")
        assert "ltv" in result

    def test_acronym_fha_not_corrected(self):
        result = correct("fha loan requirements")
        assert "fha" in result

    def test_acronym_va_not_corrected(self):
        result = correct("va loan")
        assert "va" in result

    def test_acronym_dti_not_corrected(self):
        result = correct("dti ratio")
        assert "dti" in result

    def test_numbers_not_corrected(self):
        result = correct("what is 30 percent")
        assert "30" in result
        assert "percent" in result

    def test_dollar_amount_not_corrected(self):
        result = correct("house costs 500000 dollars")
        assert "500000" in result

    def test_short_tokens_not_corrected(self):
        result = correct("what is")
        assert "is" in result


class TestGluedWordRecovery:
    """Tokens like 'whatis' should be split into 'what is'."""

    def test_glued_contraction(self):
        result = correct("whatis the requirement")
        assert "what" in result
        assert "is" in result


class TestMultiwordPhraseRepair:
    """Multi-word aliases should be repaired from misspellings."""

    def test_phrase_repair_investment(self):
        result = correct("max ltv for investmnt properti")
        assert "investment" in result

    def test_phrase_repair_dti(self):
        result = correct("what is my dti ratio")
        assert "dti" in result


class TestInfiniteLoopRegression:
    """Regression tests for the infinite loop bug in _correct_multiword_phrases.

    The bug: aliases 'credit score' (singular) and 'credit scores' (plural)
    fuzzy-match each other with ratio=96 (>=92 threshold), causing the
    while-changed loop to oscillate forever.
    """

    def test_credit_score_singular_no_hang(self):
        """This specific input hung forever before the fix."""
        result = _run_with_timeout(lambda: correct("tell me the minimum credit score"), timeout=5)
        assert "credit" in result
        assert "score" in result

    def test_credit_scores_plural_no_hang(self):
        result = _run_with_timeout(lambda: correct("what are acceptable credit scores"), timeout=5)
        assert "credit" in result

    def test_credit_score_in_long_query(self):
        result = _run_with_timeout(
            lambda: correct("what is the minimum credit score for a conventional loan"),
            timeout=5,
        )
        assert "credit" in result
        assert "score" in result

    def test_multiple_singular_plural_pairs(self):
        """Ensure no oscillation with multiple singular/plural alias pairs."""
        result = _run_with_timeout(
            lambda: correct("what are the document requirements and credit scores needed"),
            timeout=5,
        )
        assert "document" in result or "documents" in result
        assert "credit" in result

    def test_max_ltvs_highest(self):
        """'max ltvs' should not oscillate between ltv/ltvs aliases."""
        result = _run_with_timeout(lambda: correct("max ltvs for conventional"), timeout=5)
        assert "ltv" in result or "loan to value" in result


class TestNoFalseCorrections:
    """Unknown words with no good match should be left as-is."""

    def test_unknown_word_left_alone(self):
        result = correct("asdfqwer zxcvbnm")
        assert result == "asdfqwer zxcvbnm"

    def test_low_confidence_not_corrected(self):
        result = correct("xyzqwerty plm")
        # Should not be 'corrected' to something unrelated
        assert "xyzqwerty" in result

    def test_a_loan_not_rewritten_to_va_loan(self):
        """'a loan' must not be fuzzy-replaced with the 'va loan' alias.

        Regression: window "a loan" scored 92.3 against "va loan" (>= 92)
        and was silently rewritten, corrupting generic queries like
        "can i get a loan with a 580 credit score".
        """
        result = correct("can i get a loan with a 580 credit score")
        assert "a loan" in result
        assert "va loan" not in result

    def test_qualify_for_a_loan_not_rewritten(self):
        result = correct("what fico score do i need to qualify for a loan")
        assert "a loan" in result
        assert "va loan" not in result

    def test_fully_known_phrase_still_repairs_misspelling(self):
        """Guard must not disable genuine phrase repair."""
        result = correct("max ltv for investmnt properti")
        assert "investment" in result
        assert "property" in result or "properties" in result


class TestCommonWordProtection:
    """Common English words that must never be rewritten by fuzzy match.

    Regressions: unknown common words were being "corrected" into domain
    aliases by substring-favouring fuzzy matches:
    - finance     -> refinance   (containment match)
    - statements  -> settlement  (then 'settlement' is a 'closing' alias)
    - application -> applicant
    - approval    -> preapproval
    - require     -> required    (grammar corruption)
    - hello/thanks-> heloc/than  (noise words)
    """

    def test_finance_not_rewritten_to_refinance(self):
        result = correct("can i finance a manufactured home")
        assert "finance" in result
        assert "refinance" not in result

    def test_bank_statements_not_rewritten_to_bank_settlement(self):
        result = correct("do i need to provide bank statements")
        assert "bank statements" in result
        assert "settlement" not in result

    def test_application_not_rewritten_to_applicant(self):
        result = correct("what documents are required for a mortgage application")
        assert "application" in result
        assert "applicant" not in result

    def test_approval_not_rewritten_to_preapproval(self):
        result = correct("what is a pre approval letter")
        assert "approval" in result
        assert "preapproval" not in result

    def test_require_not_rewritten_to_required(self):
        result = correct("do fha loans require a down payment")
        assert "require" in result
        assert "required" not in result

    def test_noise_words_not_rewritten(self):
        assert correct("hello") == "hello"
        assert correct("thanks") == "thanks"


class TestRealWordSwapProtection:
    """Valid English words must never be corrected into a DIFFERENT word.

    Regressions (design decision 2026-08-09): valid words with a fuzzy
    match to another vocab word at ratio >= 80 were being silently
    rewritten:
    - "second" -> "send"  (ratio 80, len 6 -> 4; blocked by the
      length-difference guard + "second" now protected)
    - "borrow" -> "borrower" (blocked by adding "borrow" to COMMON_WORDS)
    - "wats"  -> "was" (bad guess; handled as a contraction in
      normalization, "wats" -> "what is")
    """

    def test_second_not_rewritten_to_send(self):
        assert correct("what is the down payment for a second home") == \
            "what is the down payment for a second home"

    def test_second_home_entity_survives_pipeline(self):
        from app.query_processing import pipeline

        plan = pipeline.process_query("what is the down payment for a second home")
        assert len(plan.sub_queries) == 1
        sq = plan.sub_queries[0]
        assert "second home" in sq.text
        canonicals = [e.canonical for e in sq.entities]
        assert "second home" in canonicals

    def test_second_home_requirements_entity_survives_pipeline(self):
        from app.query_processing import pipeline

        plan = pipeline.process_query("what are second home requirements")
        assert len(plan.sub_queries) == 1
        sq = plan.sub_queries[0]
        assert "second home" in sq.text
        canonicals = [e.canonical for e in sq.entities]
        assert "second home" in canonicals

    def test_borrow_never_becomes_borrower(self):
        result = correct("how much did i borrow")
        assert "borrow" in result
        assert "borrower" not in result

    def test_owe_never_becomes_owed(self):
        result = correct("how much do i owe")
        assert "owe" in result
        assert "owed" not in result

    def test_genuine_typos_still_corrected_after_guard(self):
        """The length-diff guard must not disable real typo fixes."""
        assert "credit" in correct("what is my credt score")
        assert "amount" in correct("wats my loan ammount")
        assert "requirements" in correct("what are the requirments")
        assert "documents" in correct("what documnts are requred")
        assert "minimum" in correct("what is the minimun score")
        assert "investment" in correct("max ltv for investmnt properti")

    def test_case_processing_words_never_rewritten(self):
        """'processed'/'stage' etc. are valid words with near vocab matches."""
        assert correct("is my loan being processed") == "is my loan being processed"
        assert correct("what stage is my case in") == "what stage is my case in"
        assert correct("what is the status of my pending case") == "what is the status of my pending case"
        assert "progressed" not in correct("is my loan being processed")
        assert "state" not in correct("what stage is my case in")

    def test_no_known_word_in_router_phrases_is_corrupted(self):
        """Systematic sweep: every real word in the fact-router phrase table
        and the eval dataset must survive spelling correction unchanged."""
        import re

        from app.query_processing.fact_router import FACT_INTENT_PHRASES
        from app.query_processing.spell_correction import correct

        tokens: set[str] = set()
        for phrases in FACT_INTENT_PHRASES.values():
            for phrase in phrases:
                tokens.update(phrase.split())

        corrupted = sorted(
            {
                word
                for word in tokens
                if re.fullmatch(r"[a-z]{4,}", word) and correct(word) != word
            }
        )
        assert corrupted == [], f"real words corrupted by spell correction: {corrupted}"


class TestEmptyInput:
    def test_empty_string(self):
        assert correct("") == ""

    def test_whitespace_only(self):
        assert correct("   ") == ""


class TestIdempotency:
    """Running correct() twice should yield the same result."""

    def test_idempotent_clean(self):
        original = "what is the minimum credit score"
        once = correct(original)
        twice = correct(once)
        assert once == twice

    def test_idempotent_misspelled(self):
        original = "what is the minimun credt scor"
        once = correct(original)
        twice = correct(once)
        assert once == twice


class TestPipelineIntegration:
    """Test that correct() works as expected in the full pipeline context."""

    def test_correct_with_pipeline(self):
        """Test correct() output can be used in downstream pipeline stages."""
        from app.query_processing import pipeline

        plan = pipeline.process_query("what is the minimun credt scor")
        assert len(plan.sub_queries) == 1
        sq = plan.sub_queries[0]
        assert "minimum" in sq.text
        assert "score" in sq.text

    def test_correct_with_multi_question(self):
        """Test correct() with multi-question splitting."""
        from app.query_processing import pipeline

        plan = pipeline.process_query(
            "What documents are required, what is the maximum LTV, and also tell me the minimum credit score?"
        )
        assert len(plan.sub_queries) == 3
        # Each sub-query should be corrected
        for sq in plan.sub_queries:
            assert len(sq.text) > 0

    def test_occupancy_paraphrase_expands_to_canonical(self):
        """'live in the home' must extract occupancy and expand the query.

        Regression: without the occupancy aliases, the canonical term never
        reached the search query, so the occupancy chunk failed the BM25
        lexical gate (fts @@) and could never be retrieved (see benchmark
        gap "do i need to live in the home").
        """
        from app.query_processing import pipeline

        for question in (
            "do i need to live in the home",
            "must i move into the property",
            "do i have to reside there",
        ):
            plan = pipeline.process_query(question)
            assert len(plan.sub_queries) == 1
            sq = plan.sub_queries[0]
            canonicals = [e.canonical for e in sq.entities]
            assert "occupancy" in canonicals, f"no occupancy entity for {question!r}"
            assert "occupancy" in sq.expanded

    def test_document_paperwork_expands_to_canonical(self):
        """'paperwork' / 'documents' must extract the document entity and
        expand the query so document chunks pass the BM25 lexical gate.

        Regression: there was no 'document' domain term, so queries like
        "what paperwork do i need to apply for a loan" carried no lexical
        anchor for document chunks (benchmark gap id 10, ranked ~13).
        """
        from app.query_processing import pipeline

        for question in (
            "what paperwork do i need to apply for a loan",
            "what documents are required for a mortgage application",
            "what paperwork do i need to provide",
        ):
            plan = pipeline.process_query(question)
            assert len(plan.sub_queries) == 1
            sq = plan.sub_queries[0]
            assert sq.intent == "documents"
            canonicals = [e.canonical for e in sq.entities]
            assert "document" in canonicals, f"no document entity for {question!r}"


def _run_with_timeout(func, timeout: int = 5) -> str:
    """Run a function with a timeout to detect hangs/infinite loops.

    Uses threading (cross-platform) instead of signal.SIGALRM (Unix-only).
    """
    import threading

    result = [None]
    exception = [None]

    def target():
        try:
            result[0] = func()
        except Exception as e:
            exception[0] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        raise TimeoutError(f"Function did not complete within {timeout}s — possible infinite loop")

    if exception[0] is not None:
        raise exception[0]

    return result[0]
