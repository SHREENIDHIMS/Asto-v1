"""Confidence thresholds and routing logic.

Per CLAUDE.md rule 7, these are configuration, not constants.
Defaults from Final_System_Design.md §5.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConfidenceLevel:
    high: float = 90.0   # ≥90: return answer immediately
    medium: float = 75.0  # 75–89: return answer with caveat
    low: float = 50.0    # 50–74: return partial + suggest rephrase
    no_answer: float = 0.0  # <50: "no answer found" + log knowledge gap


DEFAULT_THRESHOLDS = ConfidenceLevel()


def route_by_confidence(confidence: float) -> str:
    """Return the routing decision for a given confidence score.

    Returns one of: "answer", "partial", "no_answer"
    """
    if confidence >= DEFAULT_THRESHOLDS.high:
        return "answer"
    if confidence >= DEFAULT_THRESHOLDS.medium:
        return "partial"
    if confidence >= DEFAULT_THRESHOLDS.low:
        return "partial"
    return "no_answer"
