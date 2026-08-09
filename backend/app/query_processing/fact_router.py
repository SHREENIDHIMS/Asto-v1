"""Structured-fact intent router (Phase 1 dual-path assistant).

Deterministic, rule-driven classifier that decides whether a user query
should take the structured-fact path (typed SQL on the operational schema)
or fall through to the document path (vector + BM25 on document chunks).

No ML, no LLM — pure phrase matching, same trust posture as the rest of
the query_processing pipeline.

Per docs/architecture/dual_path_assistant.md §3:
- A query that matches no structured-fact intent falls through to the
  document path.
- A query that matches an intent whose resolver has no supported fact
  (e.g. no due-date column exists) also falls through.
"""

from __future__ import annotations

import re

# Intent table (docs/architecture/dual_path_assistant.md §3.1).
# Order matters: more specific phrases are matched first. A query that
# matches no phrase here routes to the document path.
FACT_INTENT_PHRASES: dict[str, list[str]] = {
    "case_status": [
        "status of my case",
        "status of my application",
        "case status",
        "application status",
        "current status",
        "how is my case",
        "where is my case",
        "where is my application",
        "status of the case",
    ],
    "case_next_step": [
        "what happens next",
        "what's next",
        "what is next",
        "next step",
        "what should i do next",
        "what do i do next",
        "what now",
    ],
    "missing_documents": [
        "what documents are missing",
        "missing documents",
        "documents do you need",
        "what do you still need",
        "still missing",
        "outstanding documents",
        "what else do you need",
        "documents are outstanding",
    ],
    "case_documents": [
        "documents i submitted",
        "documents on file",
        "documents for my case",
        "show my documents",
        "my case documents",
        "documents submitted",
        "documents in my case",
    ],
    "case_property": [
        "which property",
        "what property",
        "property for my case",
        "my property address",
        "which address",
        "what address is my case",
    ],
    "case_timeline": [
        "history of my case",
        "case history",
        "case timeline",
        "timeline of my case",
        "progress of my case",
        "case progress",
        "what has happened",
    ],
    "workflow_step": [
        "where is my file",
        "where in the process",
        "what stage",
        "what step",
        "where is my application in",
        "workflow status",
    ],
    "client_financials": [
        "loan amount",
        "how much is my loan",
        "loan balance",
        "how much do i owe",
        "amount of my loan",
        "how much is my mortgage",
    ],
}

# Intents that are recognized but have no supported resolver yet. The
# router returns None for these so the query falls through to the document
# path instead of producing a misleading "no answer" fact package.
UNSUPPORTED_FACT_INTENTS: set[str] = {"due_date"}

_NON_WORD_RE = re.compile(r"[^a-z]+")


def classify_fact_intent(normalized_query: str) -> str | None:
    """Return the dominant structured-fact intent, or None for document path.

    ``normalized_query`` should be the normalized (lowercased, collapsed)
    user query from the pipeline.
    """
    lower = normalized_query.lower()
    lower = _NON_WORD_RE.sub(" ", lower)
    lower = re.sub(r"\s+", " ", lower).strip()

    for intent, phrases in FACT_INTENT_PHRASES.items():
        if intent in UNSUPPORTED_FACT_INTENTS:
            continue
        for phrase in phrases:
            if phrase in lower:
                return intent
    return None
