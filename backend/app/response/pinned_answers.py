"""Pinned answers — admin-curated verbatim response packages.

An admin pins the response package of a REAL, audited search. When a later
query matches the pin's normalized key exactly, the stored package is
replayed verbatim before any retrieval happens:

- No generation anywhere: every excerpt/summary sentence/fact in a pin was
  retrieved verbatim when the source search ran (DEC-1 doctrine). Serving a
  pin replays those stored values byte-for-byte with a fresh response_id.
- Deterministic matching only: exact match on a normalized key. No fuzzy
  or semantic matching — a near-miss must fall through to the normal
  pipeline rather than risk answering a different question.
- Audience scoping in SQL (rule 1): a pin captured from staff-visible
  documents carries ``audience='staff'`` and can never be served to a
  client account. Pins verified safe for both audiences are 'any'.
- Every served pin is audit-logged like any other query (rule 8).

This module is lookup + pure logic; the API lives in
``api/v1/pinned_answers.py`` and the serving hook in ``api/v1/search.py``.
"""

from __future__ import annotations

import re
import uuid

# Collapse all whitespace runs and lowercase; strip surrounding punctuation
# so "What is an APR?" and "what is an apr" share one key.
_WS_RE = re.compile(r"\s+")
_EDGE_PUNCT_RE = re.compile(r"^[\s\"'¿?!.]+|[\s\"'¿?!.]+$")


def normalize_for_pin(query: str) -> str:
    """Deterministic normalization used BOTH at pin creation and at serve
    time — changing this function invalidates existing keys."""
    q = _WS_RE.sub(" ", query.strip().lower())
    return _EDGE_PUNCT_RE.sub("", q).strip()


def find_pinned_answer(conn, query: str, audience: str | None) -> dict | None:
    """Exact-match lookup of an active pin for this query + audience.

    The audience filter lives in the SQL WHERE clause (rule 1). Returns
    the full row (including the stored package JSONB) or None.
    """
    key = normalize_for_pin(query)
    if not key:
        return None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, query, audience, package, confidence, source_response_id "
            "FROM pinned_answers "
            "WHERE query_norm = %s AND is_active = true "
            "AND audience IN ('any', %s)",
            (key, audience if audience in ("staff", "client") else "staff"),
        )
        return cur.fetchone()


def pinned_payload(row: dict, original_query: str) -> dict:
    """Rebuild the public SearchResponse payload from a stored pin.

    Fresh response_id per serve (each answer is individually auditable);
    every content field comes verbatim from the stored package.
    """
    pkg = row["package"] or {}
    return {
        "response_id": uuid.uuid4().hex,
        "title": pkg.get("title") or row["query"],
        "answer": pkg.get("answer") or "",
        "excerpts": pkg.get("excerpts") or [],
        "summary": pkg.get("summary") or [],
        "confidence": float(row.get("confidence") or 1.0),
        "routing": "answer",
        "related_questions": pkg.get("related_questions") or [],
        "facts": pkg.get("facts") or [],
        "retrieval_path": pkg.get("retrieval_path") or "document",
        "no_answer_reason": None,
        "citations": pkg.get("citations") or [],
        "pinned": True,
        "pinned_from_query": original_query,
    }


def validate_pin_package(package: dict) -> list[str]:
    """Structural validation for a package being pinned.

    A pin must be a successful document-path response with actual verbatim
    content (excerpts and/or summary sentences). Returns a list of
    problems; empty means valid.
    """
    problems: list[str] = []
    if not isinstance(package, dict):
        return ["package must be an object"]
    if package.get("routing") != "answer":
        problems.append("only routing='answer' responses can be pinned")
    excerpts = package.get("excerpts")
    summary = package.get("summary")
    facts = package.get("facts")
    if not excerpts and not summary and not facts:
        problems.append("package has no excerpts, summary, or facts to replay")
    if excerpts is not None:
        if not isinstance(excerpts, list):
            problems.append("excerpts must be a list")
        else:
            for i, e in enumerate(excerpts):
                if not isinstance(e, dict) or not (e.get("text") or "").strip():
                    problems.append(f"excerpt[{i}] has no text")
                elif not isinstance(e.get("source"), dict):
                    problems.append(f"excerpt[{i}] has no source object")
    if summary is not None and not isinstance(summary, list):
        problems.append("summary must be a list")
    return problems
