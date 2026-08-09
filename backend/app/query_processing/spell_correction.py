"""Vocabulary-gated typo correction.

Strategy: correct a *single token* only when it is NOT already a known
term/acronym/common word AND it has a strong fuzzy match in the domain
vocabulary. Everything else is left untouched:

- numbers, percentages, dollar amounts are never corrected
- known acronyms (ltv, dti, fha, va, usda, apr ...) are protected
- unknown words with no near match are left as-is (the search engine is
  still typo-tolerant via tsvector stemming and vector similarity)

A small "glued word" recovery pass fixes tokens like ``whatis`` or
``creditscore`` by splitting them into two known vocabulary words.

``rapidfuzz`` is a small, C-accelerated, actively-maintained library —
far lighter than SymSpell or any model, and fast enough for query-time
use on a shared micro instance.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz, process

from app.query_processing import domain_terms

_MIN_TOKEN_LEN_FOR_CORRECTION = 4
# Strong-match threshold. Below this the candidate is too different to
# trust; we keep the user's spelling rather than risk a wrong "fix".
# 80 is chosen so that single-character edits in 4-6 char tokens (e.g.
# "inocme" → "income" at 83.3) are caught, while random strings are not.
_RATIO_THRESHOLD = 80
# Phrase-level threshold (multi-word aliases) is higher — replacing a
# whole phrase is more invasive.
_PHRASE_RATIO_THRESHOLD = 92
# Real-word-swap guard (design decision 2026-08-09). A valid English word
# can fuzzy-match a DIFFERENT vocab word at >= 80 with a length jump of 2
# (e.g. "second" → "send" at 80.0, "borrow" → "borrower" at 83.3 before
# "borrow" was protected). Legitimate typos almost never move more than 1
# character in length ("credt" → "credit", "ammount" → "amount",
# "documnts" → "documents"). Requiring |len(token) - len(best)| <= 1
# blocks identity swaps while keeping every real typo fix. As a fallback
# for longer words, allow a 2-char jump only at a much stronger ratio.
_MAX_LEN_DIFF = 1
_LEN_DIFF_2_MIN_RATIO = 92

_TOKEN_RE = re.compile(r"[a-z]+")
_ALPHA_RE = re.compile(r"^[a-z]+$")

# Vocabulary for token-level correction: only SINGLE-WORD entries.
# Multi-word phrases are handled by the phrase-level pass, not here.
# Using only single words prevents low ratios when comparing a short
# token against a multi-word alias (e.g. "credt" vs "credit score").
_CORRECTION_VOCAB: list[str] = sorted(
    set(a for a in domain_terms.aliases() if " " not in a)
    | set(d for d in domain_terms.DOMAIN_TERMS.keys() if " " not in d)
    | domain_terms.COMMON_WORDS
)
_VOCAB_SET: set[str] = set(_CORRECTION_VOCAB)

# Multi-word vocabulary for phrase-level protection (all aliases + canonicals).
# Used to skip phrases that are already known terms.
_MULTIWORD_VOCAB: set[str] = set(
    set(alias for alias in domain_terms.aliases() if " " in alias)
    | set(canon for canon in domain_terms.DOMAIN_TERMS if " " in canon)
)

# Multi-word aliases for the phrase-level fix pass.
_MULTIWORD_ALIASES: list[str] = sorted(
    domain_terms.multiword_aliases(), key=len, reverse=True
)

def _is_protected(token: str) -> bool:
    """Tokens that must never be rewritten."""
    if not token:
        return True
    if not _ALPHA_RE.match(token):
        return True  # contains digits / symbols / $ / % etc.
    if token in _VOCAB_SET:
        return True
    # Protect common English plurals: if dropping a trailing "s" yields
    # a known word, treat the plural as protected too.
    if len(token) > 4 and token.endswith("s") and token[:-1] in _VOCAB_SET:
        return True
    if len(token) < _MIN_TOKEN_LEN_FOR_CORRECTION:
        return True
    return False


def _split_glued(token: str) -> str | None:
    """Return a space-joined split if the token is two known words glued."""
    if len(token) < 5:
        return None
    for i in range(2, len(token) - 1):
        left, right = token[:i], token[i:]
        if len(left) < 2 or len(right) < 2:
            continue
        if left in _VOCAB_SET and right in _VOCAB_SET:
            return f"{left} {right}"
    return None


def _correct_token(token: str) -> str:
    if _is_protected(token):
        return token
    # Try glued-word recovery FIRST — "whatis" should split to "what is",
    # not get fuzzy-matched to "what" (which drops the "is" entirely).
    glued = _split_glued(token)
    if glued:
        return glued
    best, score, _ = process.extractOne(token, _CORRECTION_VOCAB, scorer=fuzz.ratio)
    if score >= _RATIO_THRESHOLD:
        # A single candidate can fail the length guard while a slightly
        # worse one is a perfect-size fix (e.g. "properti" → "properties"
        # at 88.9 but len+2, vs "property" at 87.5 and len+0). Walk the
        # top matches and take the first that respects the length guard.
        for candidate, candidate_score, _ in process.extract(
            token, _CORRECTION_VOCAB, scorer=fuzz.ratio, limit=5
        ):
            if candidate_score < _RATIO_THRESHOLD:
                break
            length_diff = abs(len(token) - len(candidate))
            if length_diff <= _MAX_LEN_DIFF or (length_diff == 2 and candidate_score >= _LEN_DIFF_2_MIN_RATIO):
                return candidate
    return token


def _correct_multiword_phrases(text: str) -> str:
    """Fix misspelled multi-word phrases using a sliding-window match.

    Only replaces a window when the fuzzy match is very strong and the
    window is not already an exact alias.

    Uses a single pass with position tracking to prevent infinite loops
    between aliases that fuzzy-match each other (e.g. "credit score" vs
    "credit scores"). Each token position can only be replaced once per
    pass, and we cap iterations as a safety net.
    """
    tokens = text.split()
    if len(tokens) < 2:
        return text

    _MAX_PHRASE_PASSES = 3
    for _ in range(_MAX_PHRASE_PASSES):
        changed = False
        used_positions: set[int] = set()

        for alias in _MULTIWORD_ALIASES:
            alias_tokens = alias.split()
            n = len(alias_tokens)
            for i in range(len(tokens) - n + 1):
                if any(pos in used_positions for pos in range(i, i + n)):
                    continue
                window = " ".join(tokens[i : i + n])
                if window == alias or window in _MULTIWORD_VOCAB:
                    for pos in range(i, i + n):
                        used_positions.add(pos)
                    continue
                # Protect windows where every token is already a known word
                # (e.g. "a loan" must not become "va loan"). Phrase repair is
                # only for misspellings — a fully-known phrase is left alone.
                if all(tok in _VOCAB_SET for tok in tokens[i : i + n]):
                    for pos in range(i, i + n):
                        used_positions.add(pos)
                    continue
                if fuzz.ratio(window, alias) >= _PHRASE_RATIO_THRESHOLD:
                    tokens[i : i + n] = alias_tokens
                    for pos in range(i, i + n):
                        used_positions.add(pos)
                    changed = True
                    break
            if changed:
                break

        if not changed:
            break

    return " ".join(tokens)


def correct(text: str) -> str:
    """Correct spelling of a normalized (lowercased) query string.

    Order: token-level correction, then multi-word phrase repair, then
    collapse any whitespace introduced.
    """
    if not text:
        return text
    tokens = text.split()
    corrected_tokens = [_correct_token(t) for t in tokens]
    joined = " ".join(corrected_tokens)
    joined = _correct_multiword_phrases(joined)
    return re.sub(r"\s+", " ", joined).strip()
