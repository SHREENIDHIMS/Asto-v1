"""Unit tests for mention-based case resolution (case_resolver.py).

Covers the deterministic matchers without a DB:
- case-number extraction (``CAS-2026-0001`` anywhere in the query)
- property address matching (street name, street number optional, city fallback)
- client name matching (full name required, no bare "client")
- priority order: case number > property > client name

RLS scoping itself is exercised against the live DB in the integration
suite (test_fact_path_integration.py).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.query_processing.case_resolver import (
    _case_number_matches,
    _client_mentioned,
    _extract_case_numbers,
    _normalize,
    _property_mentioned,
    _single_or_candidates,
    resolve_case_from_query,
)

CLIENT_USER = {
    "id": 7,
    "email": "client@asto.local",
    "full_name": "Client",
    "is_active": True,
    "audience": "client",
    "client_id": 7,
    "role": "client",
    "department": None,
    "allowed_departments": [],
}

STAFF_USER = {
    "id": 3,
    "email": "loan@asto.local",
    "full_name": "Loan Officer",
    "is_active": True,
    "audience": "staff",
    "role": "loan_officer",
    "department": "general",
    "allowed_departments": [],
}


class TestCaseNumberExtraction:
    def test_extracts_cas_style_number(self):
        assert _extract_case_numbers("what's the loan on CAS-2026-0001?") == {"cas20260001"}

    def test_normalizes_spacing_and_case(self):
        assert _extract_case_numbers("ref: cas 2026 0001 please") == {"cas20260001"}

    def test_no_false_positive_on_plain_numbers(self):
        assert _extract_case_numbers("what is 2026 like?") == set()

    def test_extracts_short_form_without_year(self):
        assert _extract_case_numbers("status of my case CAS-0001") == {"cas0001"}

    def test_extracts_short_form_with_underscore_separator(self):
        assert _extract_case_numbers("what about cas_0001?") == {"cas0001"}

    def test_no_false_positive_on_plain_word_plus_number(self):
        assert _extract_case_numbers("tell me about case 1") == set()
        assert _extract_case_numbers("what is 2026 like?") == set()


class TestCaseNumberMatching:
    def test_exact_alnum_matches(self):
        assert _case_number_matches("cas20260001", {"cas20260001"})

    def test_short_form_matches_full_number(self):
        assert _case_number_matches("cas20260001", {"cas0001"})

    def test_wrong_letters_do_not_match(self):
        assert not _case_number_matches("cas20260001", {"xyz0001"})

    def test_wrong_digits_do_not_match(self):
        assert not _case_number_matches("cas20260001", {"cas0002"})

    def test_matches_any_of_several_mentions(self):
        assert _case_number_matches("cas20260001", {"cas0002", "cas0001"})


class TestPropertyMention:
    def test_street_name_matches_without_number(self):
        assert _property_mentioned("what is the loan on main st", "123 Main St", "Springfield")

    def test_street_number_disambiguates_shared_street(self):
        assert _property_mentioned("what is the loan on 99 factpath ave", "99 Factpath Ave", "Factville")
        assert not _property_mentioned("what is the loan on 99 factpath ave", "77 Factpath Ave", "Factville")

    def test_city_fallback(self):
        assert _property_mentioned("the property in springfield", "123 Main St", "Springfield")

    def test_street_suffix_alone_never_matches(self):
        assert not _property_mentioned("anything on st or ave", "123 Main St", "Springfield")

    def test_unrelated_query_does_not_match(self):
        assert not _property_mentioned("do you accept refinance applications", "456 Oak Ave", "Shelbyville")

    def test_concatenated_number_and_street_matches(self):
        # "456Oak" (no space) must still match "456 Oak Ave".
        assert _property_mentioned("what is the loan on 456oak ave", "456 Oak Ave", "Shelbyville")

    def test_concatenated_number_disambiguates_shared_street(self):
        assert not _property_mentioned("what is the loan on 456oak ave", "77 Oak Ave", "Shelbyville")


class TestClientMention:
    def test_full_name_required(self):
        assert _client_mentioned(set(_normalize("what is the loan for client two").split()), "Client Two")
        assert not _client_mentioned(set(_normalize("what is the loan for client two").split()), "Client User")

    def test_bare_client_word_never_matches(self):
        assert not _client_mentioned(set(_normalize("is there a client discount").split()), "Client Two")


class TestSingleOrCandidates:
    def _row(self, case_id: int, number: str) -> dict:
        return {"case_id": case_id, "case_number": number, "client_name": "X", "address": "1 Main St"}

    def test_unique_returns_case_id(self):
        res = _single_or_candidates([self._row(1, "CAS-2026-0001")], "property")
        assert res.case_id == 1
        assert res.candidates == []
        assert res.matched_by == "property"

    def test_multiple_returns_candidates(self):
        rows = [self._row(1, "CAS-2026-0001"), self._row(2, "CAS-2026-0002")]
        res = _single_or_candidates(rows, "property")
        assert res.case_id is None
        assert len(res.candidates) == 2
        assert [c.case_number for c in res.candidates] == ["CAS-2026-0001", "CAS-2026-0002"]


class TestResolvePriority:
    def _conn(self, rows: list[dict]) -> MagicMock:
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = rows
        return conn

    def test_case_number_wins_over_property(self):
        rows = [
            {"case_id": 1, "case_number": "CAS-2026-0001", "client_name": "Client User", "address": "123 Main St", "city": "Springfield", "state": "IL"},
            {"case_id": 2, "case_number": "CAS-2026-0002", "client_name": "Client Two", "address": "456 Oak Ave", "city": "Shelbyville", "state": "IL"},
        ]
        conn = self._conn(rows)
        res = resolve_case_from_query(conn, STAFF_USER, "loan on 456 oak ave for case CAS-2026-0001")
        # case-number mention dominates the property mention
        assert res.case_id == 1
        assert res.matched_by == "case_number"

    def test_ambiguous_property_returns_candidates(self):
        rows = [
            {"case_id": 1, "case_number": "CAS-2026-0001", "client_name": "Client User", "address": "123 Main St", "city": "Springfield", "state": "IL"},
            {"case_id": 2, "case_number": "CAS-2026-0002", "client_name": "Client Two", "address": "456 Oak Ave", "city": "Shelbyville", "state": "IL"},
        ]
        conn = self._conn(rows)
        # "ave" alone is a street suffix → no property match, no client match.
        res = resolve_case_from_query(conn, STAFF_USER, "loan on ave")
        assert res.case_id is None
        assert res.candidates == []

    def test_short_case_number_resolves_precisely(self):
        rows = [
            {"case_id": 1, "case_number": "CAS-2026-0001", "client_name": "Client User", "address": "123 Main St", "city": "Springfield", "state": "IL"},
            {"case_id": 2, "case_number": "CAS-2026-0002", "client_name": "Client Two", "address": "456 Oak Ave", "city": "Shelbyville", "state": "IL"},
        ]
        conn = self._conn(rows)
        # "CAS-0001" (no year) must resolve to CAS-2026-0001, not the chip path.
        res = resolve_case_from_query(conn, STAFF_USER, "status of my case CAS-0001")
        assert res.case_id == 1
        assert res.matched_by == "case_number"
        assert res.candidates == []

    def test_short_case_number_ambiguous_still_returns_candidates(self):
        rows = [
            {"case_id": 1, "case_number": "CAS-2026-0001", "client_name": "Client User", "address": "123 Main St", "city": "Springfield", "state": "IL"},
            {"case_id": 2, "case_number": "CAS-2027-0001", "client_name": "Client Two", "address": "456 Oak Ave", "city": "Shelbyville", "state": "IL"},
        ]
        conn = self._conn(rows)
        # Two cases share the trailing "0001" across different years → ambiguous.
        res = resolve_case_from_query(conn, STAFF_USER, "status of my case CAS-0001")
        assert res.case_id is None
        assert len(res.candidates) == 2
        assert res.matched_by == "case_number"
