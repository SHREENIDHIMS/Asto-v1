"""Mention-based case resolution (universal search).

When a query carries no explicit ``case_id`` and the caller has no
auto-resolvable case, we try to find the case the user is *talking about*
by resolving entity mentions in the query text against the operational
schema — case numbers (``CAS-2026-0001``), property addresses
(``123 main st``), and client names (``client two``). This lets a staff
member type "what's the loan amount on 456 oak ave" and land on the right
case without selecting it in the UI first, and lets a client with multiple
cases disambiguate by property.

Design posture: pure deterministic SQL + token matching — no LLM, no
embeddings, same trust posture as the rest of the fact path. RLS is bound
in the SQL ``WHERE`` clause (CLAUDE.md rule #1): the candidate set is always
the caller's own cases (client), assigned clients' cases (staff), or all
cases (admin). Resolution never widens access — it only picks a case from
the set the caller could already see.

Priority: case-number mention > property-address mention > client-name
mention.

- A unique match → the caller resolves that case.
- Several cases match → the caller emits a candidate-case clarify package
  (chips re-ask the same question with the case number appended, which
  re-enters mention resolution and lands deterministically).
- No match → the caller falls back to the existing auto-resolve /
  "I need a case selected to answer that." behavior.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import psycopg

from app.query_processing.fact_resolvers import _case_scope

# Common street suffixes we strip so "main st" still matches "123 Main St"
# and "ave"/"street" never count as a distinctive token on their own.
_STREET_SUFFIXES = {
    "st", "ave", "avenue", "rd", "road", "dr", "drive", "ln", "lane",
    "blvd", "boulevard", "ct", "court", "cir", "circle", "pkwy", "parkway",
    "hwy", "highway", "sr", "cr", "pl", "place", "ter", "terrace", "way",
    "street", "saint", "mount",
}

# Minimum token length for an address/client token to be considered
# distinctive (numbers, "st", "a" are never distinctive alone).
_MIN_TOKEN_LEN = 3

_CASE_NUMBER_FULL_RE = re.compile(
    r"\b([a-z]{2,8})[-_ ]?(\d{4})[-_ ]?(\d{1,6})\b",
    re.IGNORECASE,
)
# Short form: letters + hyphen/underscore + digits (e.g. "CAS-0001",
# "cas_0001"). A bare space is deliberately excluded so a common word
# followed by a number ("is 2026", "case 1") is never read as a mention.
_CASE_NUMBER_SHORT_RE = re.compile(
    r"\b([a-z]{2,8})[-_](\d{2,6})\b",
    re.IGNORECASE,
)


@dataclass
class CaseCandidate:
    """One candidate case offered for disambiguation."""

    case_id: int
    case_number: str
    client_name: str | None = None
    address: str | None = None


@dataclass
class CaseResolution:
    """Outcome of mention resolution.

    ``case_id`` set → unique match. ``candidates`` non-empty → ambiguous
    (several cases matched). Both empty → no mention matched.
    """

    case_id: int | None = None
    candidates: list[CaseCandidate] = field(default_factory=list)
    matched_by: str | None = None


def _alnum(text: str) -> str:
    """Lowercase alphanumeric-only string (for case-number comparison)."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _normalize(text: str) -> str:
    """Lowercase, punctuation collapsed to single spaces, stripped.

    Splits a digit↔letter boundary too, so "456Oak Ave" normalizes to
    "456 oak ave" — otherwise "456oak" becomes one token and neither the
    street number nor the street name can match.
    """
    t = (text or "").lower()
    t = re.sub(r"([a-z])(\d)", r"\1 \2", t)
    t = re.sub(r"(\d)([a-z])", r"\1 \2", t)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in _normalize(text).split() if len(t) >= _MIN_TOKEN_LEN}


def _extract_case_numbers(text: str) -> set[str]:
    """Return the set of alnum-normalized case numbers mentioned in ``text``.

    Accepts both the full form (``CAS-2026-0001``) and a short form
    (``CAS-0001``, ``cas 0001``) so a user typing a partial case number
    without the year still resolves precisely.
    """
    out: set[str] = set()
    for m in _CASE_NUMBER_FULL_RE.finditer(text or ""):
        out.add(f"{m.group(1)}{m.group(2)}{m.group(3)}".lower())
    short: set[str] = set()
    for m in _CASE_NUMBER_SHORT_RE.finditer(text or ""):
        short.add(f"{m.group(1)}{m.group(2)}".lower())
    # The short regex also sees the leading part of a full form ("CAS-2026"
    # inside "CAS-2026-0001"). The full form is more specific, so drop any
    # short mention that is a prefix of a full mention.
    for s in short:
        if not any(f.startswith(s) for f in out):
            out.add(s)
    return out


def _case_number_matches(stored_alnum: str, mentioned: set[str]) -> bool:
    """True when a stored case number matches one of the mentioned ids.

    An exact alnum equality always matches. A short mention (e.g.
    ``cas0001``) also matches a stored full number (``cas20260001``) when
    the mention's letter prefix is a prefix of the stored number and the
    mention's digits are a suffix of the stored digits — so "CAS-0001"
    lands on "CAS-2026-0001" deterministically.
    """
    if stored_alnum in mentioned:
        return True
    for m in mentioned:
        mm = re.match(r"([a-z]+)(\d+)", m)
        if not mm:
            continue
        letters, digits = mm.group(1), mm.group(2)
        if len(letters) >= 2 and len(digits) >= 2:
            if stored_alnum.startswith(letters) and stored_alnum.endswith(digits):
                return True
    return False


def _property_mentioned(
    query_normalized: str,
    address: str,
    city: str,
) -> bool:
    """True when the query mentions this property's address or city.

    Deterministic token matching:
    - A distinctive street-name token (len >= 3, not a street suffix) must
      appear in the query.
    - If the query carries a street number AND the stored address has one,
      the numbers must match — so "99 factpath ave" uniquely selects the
      "99 Factpath Ave" property even when another property shares the
      street name. The number is matched on the FULL normalized query (the
      token set strips tokens shorter than ``_MIN_TOKEN_LEN``, which would
      drop a 2-digit street number).
    - The city name is accepted as a fallback signal.
    """
    query_tokens = _normalize(query_normalized).split()
    addr_tokens = _normalize(address).split()
    name_tokens = [t for t in addr_tokens if len(t) >= _MIN_TOKEN_LEN and t not in _STREET_SUFFIXES]
    # Street number tie-break: when the query provides a number, it must
    # match the stored street number (digits-only address token).
    query_number = next((t for t in query_tokens if t.isdigit()), None)
    stored_number = next((t for t in addr_tokens if t.isdigit()), None)
    if query_number is not None and stored_number is not None and query_number != stored_number:
        return False
    if name_tokens and any(t in query_tokens for t in name_tokens):
        return True
    # City fallback: a query about a whole town/city with no street name.
    city_tokens = [t for t in _normalize(city).split() if len(t) >= _MIN_TOKEN_LEN]
    if city_tokens and any(t in query_tokens for t in city_tokens):
        return True
    return False


def _client_mentioned(query_tokens: set[str], full_name: str) -> bool:
    """True when the query contains the client's full name.

    Requires every significant token of the name to appear in the query
    ("client two" needs both "client" and "two") so a bare "client" never
    matches.
    """
    name_tokens = [t for t in _normalize(full_name).split() if len(t) >= _MIN_TOKEN_LEN]
    if not name_tokens:
        return False
    return all(t in query_tokens for t in name_tokens)


def _accessible_case_rows(conn: psycopg.Connection, user: dict) -> list[dict]:
    """All active cases the caller can see, with client + property context."""
    scope, params = _case_scope(user)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT c.id AS case_id, c.case_number, "
            f"cl.full_name AS client_name, p.address, p.city, p.state "
            f"FROM cases c "
            f"JOIN clients cl ON cl.id = c.client_id "
            f"LEFT JOIN properties p ON p.id = c.property_id "
            f"WHERE c.is_active = true AND {scope}",
            params,
        )
        return [dict(r) for r in cur.fetchall()]


def _single_or_candidates(
    rows: list[dict],
    matched_by: str,
) -> CaseResolution:
    if len(rows) == 1:
        return CaseResolution(case_id=rows[0]["case_id"], matched_by=matched_by)
    return CaseResolution(
        case_id=None,
        candidates=[
            CaseCandidate(
                case_id=r["case_id"],
                case_number=r["case_number"],
                client_name=r.get("client_name"),
                address=r.get("address"),
            )
            for r in rows
        ],
        matched_by=matched_by,
    )


def resolve_case_from_query(
    conn: psycopg.Connection,
    user: dict,
    query_text: str,
) -> CaseResolution:
    """Resolve a query's case mention to a case, scoped by the caller's RLS.

    Returns:
    - ``case_id`` when exactly one case matched.
    - ``candidates`` when several cases matched (ambiguous).
    - empty ``CaseResolution`` when no mention resolved.
    """
    query = _normalize(query_text)
    query_tokens = _tokens(query_text)
    if not query or not query_tokens:
        return CaseResolution()

    rows = _accessible_case_rows(conn, user)
    if not rows:
        return CaseResolution()

    # 1. Case number mention — most specific.
    mentioned = _extract_case_numbers(query_text)
    if mentioned:
        case_matches = [
            r for r in rows if _case_number_matches(_alnum(r["case_number"]), mentioned)
        ]
        if case_matches:
            return _single_or_candidates(case_matches, "case_number")

    # 2. Property address mention.
    prop_matches = [
        r for r in rows
        if r.get("address") and _property_mentioned(query, r["address"], r["city"] or "")
    ]
    if prop_matches:
        return _single_or_candidates(prop_matches, "property")

    # 3. Client name mention.
    client_matches = [
        r for r in rows
        if r.get("client_name") and _client_mentioned(query_tokens, r["client_name"])
    ]
    if client_matches:
        return _single_or_candidates(client_matches, "client_name")

    return CaseResolution()
