"""Multi-question / multi-intent detection and decomposition.

Deterministic splitting of a single user message into independent
information needs, with an *over-split guard* so joint noun phrases like
``income and employment requirements`` stay as ONE question.

Splitting rules
---------------
- Hard boundaries (``?``, ``!``, ``;``, newline) always split.
- A comma splits ONLY when the following fragment looks like an
  independent clause (starts with a question word / auxiliary verb /
  info-request verb, or ends with ``?``). Commas inside numbers are
  protected.
- A conjunction (``and``/``also``/``plus``/``or``/``additionally``)
  splits ONLY when the fragment after it is an independent clause.
  Otherwise it's treated as a list continuation and merged back.

Fragments that collapse to noise words (``help``, ``please`` ...) are
dropped, and leading connectives (``and also tell me``) are stripped.
"""

from __future__ import annotations

import re

from app.config import settings
from app.query_processing import domain_terms

# Hard boundary, comma-not-inside-number, whitespace-delimited conjunction.
_BOUNDARY_RE = re.compile(
    r"([?!;\n])"
    r"|((?<!\d),(?!\d))"
    r"|((?<=\s)(and|also|plus|or|additionally)(?=\s))"
)

_HARD = frozenset("?!;")
_CONJUNCTIONS = frozenset(("and", "also", "plus", "or", "additionally"))

_CONNECTIVE_PREFIX_RE = re.compile(
    r"^(?:and|also|plus|or|additionally|in addition|then)\s+"
)

_INFOVERBS = frozenset(("tell", "list", "show", "give", "provide"))


def _strip_connectives(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = _CONNECTIVE_PREFIX_RE.sub("", text, count=1)
    return text


def is_independent_clause(fragment: str) -> bool:
    """Heuristic: does this fragment look like its own question?"""
    frag = fragment.strip()
    if not frag:
        return False
    if frag.endswith("?"):
        return True
    first = frag.split()[0]
    if first in domain_terms.QUESTION_STARTERS:
        return True
    words = set(frag.split())
    if words & _INFOVERBS:
        return True
    return False


def _fragments(norm: str) -> list[tuple[str, str]]:
    """Return ``(delimiter, text)`` pairs from a normalized query."""
    parts = [p for p in re.split(_BOUNDARY_RE, norm) if p]
    frags: list[tuple[str, str]] = []
    current_delim = ""
    for part in parts:
        stripped = part.strip()
        if part in _HARD or part == "," or stripped in _CONJUNCTIONS:
            current_delim = part
        elif stripped:
            frags.append((current_delim, stripped))
            current_delim = ""
    return frags


def split_questions(norm: str) -> list[str]:
    """Split a normalized query into sub-question strings."""
    if not norm or not norm.strip():
        return []
    questions: list[str] = []
    current = ""
    for delim, text in _fragments(norm):
        if not current:
            current = text
            continue
        if delim in _HARD:
            questions.append(current)
            current = text
        elif delim == ",":
            if is_independent_clause(text):
                questions.append(current)
                current = text
            else:
                current = f"{current}, {text}"
        else:  # conjunction word
            candidate = _strip_connectives(text)
            if candidate and is_independent_clause(candidate):
                questions.append(current)
                current = candidate
            else:
                current = f"{current} {delim} {text}"
    if current:
        questions.append(current)

    # Clean + filter
    cleaned: list[str] = []
    for q in questions:
        q = _strip_connectives(q).strip(" ?!;,").strip()
        if not q:
            continue
        if q.split()[0] in domain_terms.NOISE_WORDS and len(q.split()) == 1:
            continue
        cleaned.append(q)

    # Deduplicate identical sub-questions (preserving order)
    seen: set[str] = set()
    unique: list[str] = []
    for q in cleaned:
        if q not in seen:
            seen.add(q)
            unique.append(q)
    return unique


def plan_split(norm: str) -> tuple[list[str], bool]:
    """Split a normalized query, capping at ``max_sub_queries``.

    Returns ``(sub_queries, truncated)``.
    """
    subs = split_questions(norm)
    cap = settings.max_sub_queries
    if len(subs) > cap:
        return subs[:cap], True
    return subs, False
