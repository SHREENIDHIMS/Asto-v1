"""Unit tests for the calibrated response-level confidence (C1).

The raw normalized RRF saturates near 100 for any top-ranked candidate,
which made the `partial` routing band unreachable. The calibration
multiplies rank agreement by a smoothed query-term-coverage factor.
"""

from __future__ import annotations

import math

from app.response.confidence_thresholds import route_by_confidence
from app.response.package_builder import (
    _calibrated_confidence,
    _normalize_rrf_score,
)


class TestNormalizedRrfSaturation:
    def test_agreement_alone_saturates(self):
        # Rank (5,5) with K=60 still normalizes to ~93.8 — the bug.
        rrf = 2.0 / (60 + 5)
        assert _normalize_rrf_score(rrf) > 90


class TestCalibratedConfidence:
    def test_strong_match_stays_answer(self):
        c = _calibrated_confidence(2.0 / 61, coverage=1.0)
        assert c >= 90
        assert route_by_confidence(c) == "answer"

    def test_topical_match_lands_partial(self):
        # rank(5,5), half the query terms present.
        c = _calibrated_confidence(2.0 / 65, coverage=0.5)
        assert route_by_confidence(c) == "partial"

    def test_weak_match_lands_partial_not_answer(self):
        c = _calibrated_confidence(2.0 / 70, coverage=0.25)
        assert route_by_confidence(c) == "partial"

    def test_poor_match_lands_no_answer(self):
        c = _calibrated_confidence(2.0 / 80, coverage=0.0)
        assert route_by_confidence(c) == "no_answer"

    def test_floor_keeps_zero_coverage_routable_as_partial_at_best_rank(self):
        # Zero overlap but perfect rank agreement → exactly the floor.
        c = _calibrated_confidence(2.0 / 61, coverage=0.0)
        assert math.isclose(c, 55.0, abs_tol=0.1)
        assert route_by_confidence(c) == "partial"

    def test_monotonic_in_coverage(self):
        rrf = 2.0 / 65
        low = _calibrated_confidence(rrf, coverage=0.2)
        high = _calibrated_confidence(rrf, coverage=0.8)
        assert high > low

    def test_clamped_to_100_and_non_negative(self):
        assert _calibrated_confidence(99.0, coverage=2.0) <= 100.0
        assert _calibrated_confidence(0.0, coverage=-1.0) >= 0.0
