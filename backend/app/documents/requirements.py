"""Case document requirements (K1: document checklist).

Derives which documents are needed, pending, received, or approved for each
case. Admins can define the required requirement names per case type; the
checklist for a given case is computed by matching its approved documents
against the requirement list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from psycopg import Connection

from app.db.postgres.models import dict_row_to_case  # we'll reference models


# ---- Default requirement sets per case type ----

# A mortgage typically needs these documents. Admins can add/remove items
# via the admin endpoints; the list below is the seed default.
DEFAULT_REQUIREMENTS: dict[str, list[dict]] = {
    "purchase": [
        {"name": "Purchase Agreement", "description": "Signed purchase agreement / sales contract"},
        {"name": "Driver's License", "description": "Government-issued ID"},
        {"name": "Proof of Income", "description": "Last 2 pay stubs or tax return"},
        {"name": "Bank Statements", "description": "Last 2 months bank statements"},
        {"name": "Credit Report", "description": "Current credit report"},
        {"name": "Appraisal Report", "description": "Home appraisal"},
        {"name": "Title Insurance", "description": "Title insurance policy / commitment"},
    ],
    "refinance": [
        {"name": "Current Mortgage Statement", "description": "Latest mortgage statement"},
        {"name": "Proof of Income", "description": "Last 2 pay stubs or tax return"},
        {"name": "Bank Statements", "description": "Last 2 months bank statements"},
        {"name": "Credit Report", "description": "Current credit report"},
        {"name": "Appraisal Report", "description": "Home appraisal"},
        {"name": "Title Insurance", "description": "Title insurance policy / commitment"},
        {"name": "Loan Estimate", "description": "Original loan estimate"},
    ],
    "home equity": [
        {"name": "Current Mortgage Statement", "description": "Latest mortgage statement"},
        {"name": "Proof of Income", "description": "Last 2 pay stubs or tax return"},
        {"name": "Bank Statements", "description": "Last 2 months bank statements"},
        {"name": "Appraisal Report", "description": "Home appraisal"},
        {"name": "Title Insurance", "description": "Title insurance policy / commitment"},
    ],
}


def _requirements_for_case_type(case_type: str) -> list[dict]:
    """Return the default requirement list for a case type, or empty list."""
    return DEFAULT_REQUIREMENTS.get(case_type, [])


def derive_case_checklist(
    conn: Connection,
    case_id: int,
) -> list[dict]:
    """Derive the document checklist for a case.

    Returns a list of dicts, each with:
    - name: requirement name
    - description: from the requirement definition
    - status: "required" / "pending" / "received" / "approved"
    - has_document: whether any approved document matches this requirement
    - matching_document: the best-matching document (title, version, approved_by)

    Logic:
    - "required"   : always in the list (from the default set)
    - "pending"    : no approved document yet matching this requirement
    - "received"   : at least one approved document whose title contains
      the requirement name (case-insensitive substring match)
    - "approved"   : same as "received" but the matched document is approved
      (which all search-visible docs are, by definition)
    """
    from app.db.postgres import session

    # Get the default requirements for the case's type
    # We need to look up the case to find its type
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, client_id, property_id, status FROM cases WHERE id = %s",
            (case_id,),
        )
        case_row = cur.fetchone()
    if case_row is None:
        return []

    case_type = _infer_case_type(case_row)
    requirements = _requirements_for_case_type(case_type)

    # Build the result: every default requirement appears, with status derived
    # from whether we have a matching approved document.
    result: list[dict] = []

    # Get all approved documents for this case (via client_id / property_id)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, title, version, approved_by, approved_at
            FROM documents
            WHERE is_active = true
              AND approval_status = 'approved'
              AND client_id = %s
            """,
            (case_row["client_id"],),
        )
        approved_docs = cur.fetchall()

    # Build a map: lowercase title -> doc info for matching
    doc_map: dict[str, dict] = {}
    for doc in approved_docs:
        doc_map[doc["title"].lower()] = {
            "id": doc["id"],
            "title": doc["title"],
            "version": doc.get("version") or 1,
            "approved_by": doc.get("approved_by"),
            "approved_at": doc.get("approved_at"),
        }

    for req in requirements:
        req_name_lower = req["name"].lower()
        # Check if any approved document title contains the requirement name
        matched_doc = None
        for doc_lower, doc_info in doc_map.items():
            if req_name_lower in doc_lower or doc_lower in req_name_lower:
                matched_doc = doc_info
                break

        if matched_doc:
            status = "approved"  # doc is approved, so requirement is satisfied
        else:
            # Check if any document (approved or pending) exists with similar title
            # For "pending" status, we look at all active docs
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, title, approval_status
                    FROM documents
                    WHERE is_active = true
                      AND client_id = %s
                    """,
                    (case_row["client_id"],),
                )
                all_docs = cur.fetchall()

            pending_match = None
            for doc in all_docs:
                if req_name_lower in doc["title"].lower() or doc["title"].lower() in req_name_lower:
                    pending_match = {
                        "id": doc["id"],
                        "title": doc["title"],
                        "approval_status": doc["approval_status"],
                    }
                    break

            if pending_match and pending_match["approval_status"] == "pending":
                status = "received"  # pending doc exists, consider it "received" for checklist
            else:
                status = "pending"

        result.append(
            {
                "name": req["name"],
                "description": req.get("description", ""),
                "status": status,
                "has_document": matched_doc is not None,
                "matching_document": matched_doc,
            }
        )

    return result


def _infer_case_type(case_row: dict) -> str:
    """Infer the case type from the case row data."""
    # Simple inference based on available fields
    # In a full implementation, this would come from a case_type column
    # or the case number prefix
    case_number = case_row.get("case_number", "")
    if case_number.startswith("PUR"):
        return "purchase"
    elif case_number.startswith("REF"):
        return "refinance"
    elif case_number.startswith("HEL"):
        return "home equity"
    else:
        # Default to purchase if we can't infer
        return "purchase"


def seed_default_requirements(
    conn: Connection,
    case_type: str | None = None,
) -> int:
    """Seed the default requirements into the DB for a case type.

    Returns the number of requirement rows inserted (idempotent - skips
    if they already exist).
    """
    requirements = _requirements_for_case_type(case_type or "purchase")

    with conn.cursor() as cur:
        inserted = 0
        for req in requirements:
            # Check if already exists
            cur.execute(
                "SELECT id FROM case_document_requirements WHERE name = %s AND case_type = %s",
                (req["name"], case_type or "purchase"),
            )
            if cur.fetchone():
                continue
            cur.execute(
                """INSERT INTO case_document_requirements
                   (case_type, name, description, required_from, status)
                   VALUES (%s, %s, %s, %s, %s)""",
                (
                    case_type or "purchase",
                    req["name"],
                    req.get("description", ""),
                    "client",
                    "required",
                ),
            )
            inserted += 1
        conn.commit()
    return inserted