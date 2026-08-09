"""Structured-fact intent router (Phase 1 dual-path assistant).

Deterministic, rule-driven classifier that decides whether a user query
should take the structured-fact path (typed SQL on the operational schema)
or fall through to the document path (vector + BM25 on document chunks).

No ML, no LLM — pure phrase matching + fuzzy/scoring fallback, same trust
posture as the rest of the query_processing pipeline.

Two-stage routing (asymmetric thresholds):

1. **Exact phrase stage** — ``classify_fact_intent`` returns a
   structured-fact intent immediately when a deterministic phrase matches.
2. **Soft-match stage** — ``route_fact_intent``. When no exact phrase
   matches but the query reads like a personal case question, it scores
   each intent via fuzzy phrase similarity + a light keyword signal.
   - A decisive winner (score >= SOFT_ROUTE_THRESHOLD and comfortably
     ahead of the runner-up) routes to that intent.
   - A query with some signal but no decisive winner, phrased
     personally/about the caller's case, is marked ``needs_clarification``
     instead of guessing — the caller returns the deterministic "I'm not
     sure what you're asking — can you rephrase?" prompt with the intent's
     related questions as click-to-ask chips.
   - Everything else falls through to the document path.

Incomplete fragments (a bare "status?", "missing?") are never routed on
their own — see ``_word_count`` guard below (CLAUDE.md / design decision
2026-08-09: no fragment guessing).

Per docs/architecture/dual_path_assistant.md §3:
- A query that matches no structured-fact intent falls through to the
  document path.
- A query that matches an intent whose resolver has no supported fact
  (e.g. no due-date column exists) also falls through.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

# Intent table (docs/architecture/dual_path_assistant.md §3.1).
# Order matters: more specific phrases are matched first. A query that
# matches no phrase here routes to the document path.
#
# Beyond the canonical phrases, each intent carries natural / telegram
# variants that real clients type (contractions, dropped words, "app" for
# application). These are still DETERMINISTIC substring phrases — more
# surface coverage, same zero-ML posture.
FACT_INTENT_PHRASES: dict[str, list[str]] = {
    "case_status": [
        "status of my case",
        "status of my application",
        "case status",
        "application status",
        "current status",
        "how is my case",
        "how is my case going",
        "how is my case doing",
        "where is my case",
        "where is my application",
        "where is my app",
        "where is my app at",
        "status of the case",
        "whats happening with my case",
        "what is happening with my case",
        "whats happening with my app",
        "what's happening with my app",
        "whats going on with my case",
        "what is going on with my case",
        "whats going on with my app",
        "updates on my case",
        "update on my case",
        "any updates",
        "whats the status",
        "what is the status",
        "where does my case stand",
        "is my case moving forward",
        "is my case moving along",
        "any word on my application",
        "any word on my case",
        "give me the latest on my case",
        "whats the situation with my case",
        "whats the situation with my file",
        "is my application going well",
        "how is my application going",
    ],
    "case_next_step": [
        "what happens next",
        "what's next",
        "what is next",
        "next step",
        "what should i do next",
        "what do i do next",
        "what now",
        "what happens now",
        "so what now",
        "so what happens now",
        "what do we do now",
        "what happens after this",
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
        "what else do you need from me",
        "what do you need from me",
        "do you need anything from me",
        "anything else you need",
        "what am i missing",
        "whats missing",
        "what is missing",
        "what do you still need from me",
        "do you need my w2",
        "do you need my w2",
        "do you need my",
        "which documents are missing",
        "which documents do you still need",
        "what documents are you missing",
        "what documents are needed",
    ],
    "case_documents": [
        "documents i submitted",
        "documents on file",
        "documents for my case",
        "show my documents",
        "my case documents",
        "documents submitted",
        "documents in my case",
        "did you get my documents",
        "did you receive my documents",
        "what documents did i submit",
        "what have i submitted",
        "what did i submit",
        "what do you have on file",
        "show me my documents",
    ],
    "case_property": [
        "which property",
        "what property",
        "property for my case",
        "my property address",
        "which address",
        "what address is my case",
        "what address",
        "what about my house",
        "what about my property",
    ],
    "case_timeline": [
        "history of my case",
        "case history",
        "case timeline",
        "timeline of my case",
        "progress of my case",
        "case progress",
        "what has happened",
        "what has happened so far",
        "what's happened so far",
        "whats happened so far",
        "what happened",
        "history on my case",
    ],
    "workflow_step": [
        "where is my file",
        "where in the process",
        "what stage",
        "what step",
        "where is my application in",
        "workflow status",
        "what step is my case in",
        "what stage is my case in",
        "where is my case in the process",
    ],
    "client_financials": [
        "loan amount",
        "how much is my loan",
        "loan balance",
        "how much do i owe",
        "amount of my loan",
        "how much is my mortgage",
        "how much did i borrow",
        "how much did i take out",
        "what is my loan amount",
        "how much have i borrowed",
        "what is the balance",
    ],
}

# Intents that are recognized but have no supported resolver yet. The
# router returns None for these so the query falls through to the document
# path instead of producing a misleading "no answer" fact package.
UNSUPPORTED_FACT_INTENTS: set[str] = {"due_date"}

# Soft-match keyword signals per intent. These are the *core content words*
# that still echo an intent even when the exact surface phrase is missing
# (e.g. "give me the latest on my app" → case_status via "app"/"update").
# Used ONLY in the scoring stage — an exact phrase always wins first.
FACT_INTENT_KEYWORDS: dict[str, set[str]] = {
    "case_status": {"status", "statuses", "app", "application", "case", "update", "updates", "where is", "latest"},
    "case_next_step": {"next", "now", "happens", "happening", "then", "what now", "follow", "waiting"},
    "missing_documents": {"missing", "outstanding", "to send", "need from me", "still need", "required"},
    "case_documents": {"documents", "docs", "submitted", "uploaded", "on file", "submissions"},
    "case_property": {"property", "address", "home", "house are we", "which home"},
    "case_timeline": {"history", "timeline", "progress", "so far", "what happened", "since"},
    "workflow_step": {"stage", "step", "workflow", "where in", "position"},
    "client_financials": {"loan", "amount", "borrow", "borrowed", "owe", "owed", "balance", "mortgage"},
}

# Asymmetric routing thresholds (design decision 2026-08-09, docs/…/dual
# path §9a). Routing a query to a fact intent is a HIGH bar: a fuzzy match
# must clear ROUTE_SCORE and beat the runner-up intent by ROUTE_MARGIN.
# Below that bar we do NOT best-guess — if the query is a personal,
# case-flavored question with no clear document intent, we hand it back
# with a clarifying prompt instead. Queries that clearly map to a document
# intent (eligibility, requirements, costs, …) always fall through to the
# document path.
ROUTE_SCORE = 0.85        # confident fuzzy match → route to intent
ROUTE_MARGIN = 0.08       # top intent must be comfortably ahead
CLARIFY_FLOOR = 0.30      # weak-but-personal signal → ask, don't guess

_NON_WORD_RE = re.compile(r"[^a-z]+")

# Personal-case markers that make a soft-matched query "about the caller's
# own case" and therefore eligible for the clarify prompt: a possessive
# case noun ("my case/app/loan/…") or phrasing *directed at the assistant*
# ("do you need", "from me"). Bare "i"/"me" is NOT enough — "can i get a
# loan with 620?" and "what documents do i need to apply?" are generic
# questions the document path answers.
_PERSONAL_RE = re.compile(
    r"\bmy (case|app|application|loan|file|mortgage|documents|document|w2|w-2|payment|house|home|balance|status|property)\b"
    r"|\bdo you need\b|\bdo you want\b|\bneed from me\b|\bfrom me\b|\bfor me\b"
)

# Conditional / hypothetical phrasing ("what happens if i miss a payment?")
# is a policy question, never a request for this caller's current case
# facts — it always falls through to the document path.
_CONDITIONAL_RE = re.compile(r"\bif\b|what would happen|what if|when do i")

# Document-path intents that can NEVER be a case fact by construction —
# generic reference/explanatory questions (eligibility, costs, limits,
# definitions) the document path answers. They never get the clarify prompt.
# NOTE: requirements/process/documents are deliberately excluded: they
# overlap with legitimate personal case questions ("do you need my w2?" is
# a missing-documents question, not a requirements doc question).
_HARD_DOC_INTENTS: set[str] = {"eligibility", "costs", "limits", "definition"}


@dataclass(frozen=True)
class FactRoute:
    """Decision for one (sub-)query: which intent, and at what confidence.

    ``needs_clarification=True`` means: this is likely a personal case
    question but no single intent cleared the routing bar — the caller
    should return the deterministic "not sure what you're asking — can
    you rephrase?" prompt (with the example chips) instead of guessing.
    """

    intent: str | None
    confidence: float = 0.0      # 0..1
    needs_clarification: bool = False


def classify_fact_intent(normalized_query: str) -> str | None:
    """Return the dominant structured-fact intent, or None for document path.

    ``normalized_query`` should be the normalized (lowercased, collapsed)
    user query from the pipeline.
    """
    lower = normalize_lower(normalized_query)

    for intent, phrases in FACT_INTENT_PHRASES.items():
        if intent in UNSUPPORTED_FACT_INTENTS:
            continue
        for phrase in phrases:
            if phrase in lower:
                return intent
    return None


def normalize_lower(normalized_query: str) -> str:
    """Collapse to a bare lowercased word string for matching."""
    lower = (normalized_query or "").lower()
    lower = _NON_WORD_RE.sub(" ", lower)
    return re.sub(r"\s+", " ", lower).strip()


def _word_count(lower: str) -> int:
    return len(lower.split()) if lower else 0


def _personal_flavor(lower: str) -> bool:
    """True when the query reads as being about the asker's own case."""
    return bool(_PERSONAL_RE.search(lower))


def _maps_to_document_intent(lower: str) -> bool:
    """True when an explicit document-path intent dominates the query.

    Keeps the clarify prompt honest: an eligibility / requirements / costs /
    limits / process question ("can i get a loan with 620?", "what is the
    interest rate?") belongs on the document path, never in a fact-intent
    gray zone. Reuses the pipeline's own keyword classifier. "documents"
    intent is excluded (see _HARD_DOC_INTENTS) — personal document questions
    are valid fact-path candidates.
    """
    from app.query_processing.intent_detection import detect_intent

    intent = detect_intent(lower, entities=[])
    return intent in _HARD_DOC_INTENTS


def _keyword_overlap(lower: str, keywords: set[str]) -> float:
    if not keywords:
        return 0.0
    hits = sum(1 for kw in keywords if kw in lower)
    # Saturate at 3 hits so huge keyword sets can't dominate.
    return min(hits / 3.0, 1.0)


def _fuzzy_score(lower: str, phrases: list[str]) -> float:
    """Best partial-ratio against the intent's phrase list (0..1)."""
    best = 0.0
    for phrase in phrases:
        if not phrase:
            continue
        r = fuzz.partial_ratio(lower, phrase) / 100.0
        if r > best:
            best = r
    return best


def _soft_scores(lower: str) -> dict[str, float]:
    scores: dict[str, float] = {}
    for intent, phrases in FACT_INTENT_PHRASES.items():
        if intent in UNSUPPORTED_FACT_INTENTS:
            continue
        scores[intent] = round(
            0.7 * _fuzzy_score(lower, phrases)
            + 0.3 * _keyword_overlap(lower, FACT_INTENT_KEYWORDS.get(intent, set())),
            3,
        )
    return scores


def route_fact_intent(normalized_query: str) -> FactRoute:
    """Asymmetric-soft routing: confident intent, clarifying prompt, or None.

    Decision tree:
    1. Empty query / fragment (< 2 words) → no routing at all (no guessing
       from a bare "status?").
    2. Exact phrase match → route at confidence 1.0.
    3. Soft score: a decisive winner (>= ROUTE_SCORE and ahead by
       ROUTE_MARGIN) routes to that intent.
    4. Weak score above CLARIFY_FLOOR on a *personal* query → mark
       ``needs_clarification`` instead of best-guessing an intent.
    5. Otherwise → ``FactRoute(None)`` (document path).
    """
    lower = normalize_lower(normalized_query)
    if _word_count(lower) < 2:
        return FactRoute(None)

    exact = classify_fact_intent(lower)
    if exact is not None:
        return FactRoute(exact, 1.0)

    # Conditional/hypothetical phrasing is policy, not this caller's case —
    # skip soft matching entirely and fall through to the document path.
    if _CONDITIONAL_RE.search(lower):
        return FactRoute(None)

    scores = _soft_scores(lower)
    sorted_scores = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top_intent, top_score = sorted_scores[0]
    runner_up = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0

    if top_score >= ROUTE_SCORE and (top_score - runner_up) >= ROUTE_MARGIN:
        return FactRoute(top_intent, top_score)

    # A clearly-document question never gets a fact-intent gray zone: no
    # fuzzy route, no clarify prompt — return it to the document path.
    if top_score >= CLARIFY_FLOOR and _personal_flavor(lower) and not _maps_to_document_intent(lower):
        return FactRoute(None, top_score, needs_clarification=True)

    return FactRoute(None, top_score)
