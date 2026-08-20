"""Unit tests for audit fix #18 — PII scanner breadth + ReDoS safety.

The original heuristic covered only email / dashed SSN / DOB / US address
and its address regex nested two permissive character classes, allowing
pathological backtracking. After the fix it also detects phone numbers,
Luhn-valid credit card numbers, undashed SSNs, and check-digit-valid ABA
routing numbers, and the address pattern cannot hang on hostile input.
"""

from __future__ import annotations

import time

from app.documents.pii_check import flagged_kinds, has_pii, scan_for_pii


class TestNewKinds:
    def test_phone_detected(self):
        kinds = flagged_kinds("Call (555) 123-4567 today.")
        assert "phone" in kinds

    def test_phone_detected_with_country_code(self):
        assert "phone" in flagged_kinds("Reach +1-800-555-0199 now.")

    def test_luhn_valid_credit_card_detected(self):
        kinds = flagged_kinds("Card 4111 1111 1111 1111 used on file.")
        assert "credit_card" in kinds

    def test_grouped_credit_card_with_dashes_detected(self):
        assert "credit_card" in flagged_kinds("4111-1111-1111-1111")

    def test_luhn_invalid_card_not_flagged(self):
        assert "credit_card" not in flagged_kinds("Card 4111 1111 1111 1112 declined.")

    def test_undashed_ssn_detected(self):
        kinds = flagged_kinds("Ref SSN 123456789 on the form.")
        assert "ssn_nodash" in kinds

    def test_invalid_ssn_area_not_flagged(self):
        # 666-xx-xxxx is never a valid SSN -> must not fire.
        assert "ssn_nodash" not in flagged_kinds("666123456")

    def test_aba_routing_detected(self):
        # 021000021 is a well-known valid test routing number.
        kinds = flagged_kinds("Wire to routing 021000021.")
        assert "aba_routing" in kinds

    def test_random_nine_digit_number_not_flagged(self):
        # 900123457 fails both the SSN shape (area >= 900) and the ABA check
        # digit -> no false positive.
        assert "ssn_nodash" not in flagged_kinds("PO 900123457")
        assert "aba_routing" not in flagged_kinds("PO 900123457")


class TestExistingKindsStillWork:
    def test_email_detected(self):
        assert "email" in flagged_kinds("mail me at a.b@example.com please")

    def test_dashed_ssn_detected(self):
        assert "ssn" in flagged_kinds("SSN 123-45-6789")

    def test_dob_detected(self):
        assert "dob" in flagged_kinds("Born 03/14/1990.")

    def test_us_address_detected(self):
        kinds = flagged_kinds("Bill to 123 Main St, Springfield, IL 62704.")
        assert "us_address" in kinds

    def test_us_address_with_zip4_detected(self):
        assert "us_address" in flagged_kinds("1 Oak Ave, Tulsa, OK 74103-1234")

    def test_non_address_numbers_not_flagged(self):
        assert not has_pii("Total due today: $1,234.56 by EOD.")


class TestReDosSafety:
    def test_address_pattern_returns_promptly_on_hostile_input(self):
        # Ambiguous commas + spaces inside both classes used to backtrack
        # combinatorially; this input must return in well under a second.
        hostile = "1111 " + ", ".join(["A" * 40] * 200)
        start = time.monotonic()
        results = scan_for_pii(hostile)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0
        assert results == []

    def test_empty_text(self):
        assert scan_for_pii("") == []
        assert not has_pii("")