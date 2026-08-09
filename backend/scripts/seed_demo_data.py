"""One-off seed: demo data for verifying client-scoped search in dev.

Inserts a second client + property (to test RBAC isolation), plus approved and
pending documents for two clients and one company-wide doc. Finally backfills
embeddings for approved chunks so the vector leg matches.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import psycopg

from app.db.postgres.session import acquire
from app.documents.embedding import generate_embeddings

ADMIN_USER_ID = 1
CLIENT1_ID = 1
PROPERTY1_ID = 1


def sha(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _id(row) -> int:
    # psycopg default row factory here is dict-like; tolerate both tuple/dict.
    return int(row["id"] if isinstance(row, dict) else row[0])


def ensure_client(cur, email: str, full_name: str) -> int:
    cur.execute("SELECT id FROM clients WHERE email = %s", (email,))
    row = cur.fetchone()
    if row is not None:
        return _id(row)
    cur.execute(
        "SELECT password_hash FROM clients WHERE id = %s",
        (CLIENT1_ID,),
    )
    client1_hash = cur.fetchone()["password_hash"]
    cur.execute(
        "INSERT INTO clients (email, full_name, password_hash, is_active) "
        "VALUES (%s, %s, %s, true) RETURNING id",
        (email, full_name, client1_hash),
    )
    cid = _id(cur.fetchone())
    print(f"Inserted client {email} id={cid}")
    return cid


def ensure_property(cur, client_id: int, address: str) -> int:
    cur.execute("SELECT id FROM properties WHERE address = %s", (address,))
    row = cur.fetchone()
    if row is not None:
        return _id(row)
    cur.execute(
        "INSERT INTO properties (client_id, address, city, state, postal_code, property_type) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (client_id, address, "Shelbyville", "IL", "62565", "apartment"),
    )
    pid = _id(cur.fetchone())
    print(f"Inserted property {address} id={pid}")
    return pid


def ensure_case(cur, case_number: str, client_id: int, property_id: int | None, loan_amount, status: str) -> int:
    cur.execute("SELECT id FROM cases WHERE case_number = %s", (case_number,))
    row = cur.fetchone()
    if row is not None:
        return _id(row)
    cur.execute(
        "INSERT INTO cases (case_number, client_id, property_id, loan_amount, status) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (case_number, client_id, property_id, loan_amount, status),
    )
    cid = _id(cur.fetchone())
    print(f"Inserted case {case_number} id={cid}")
    return cid


def add_case_event(cur, case_id: int, status_label: str, note: str) -> None:
    cur.execute(
        "INSERT INTO case_events (case_id, status, note) VALUES (%s, %s, %s)",
        (case_id, status_label, note),
    )


def ensure_staff(cur, email: str, full_name: str, department: str) -> int:
    cur.execute("SELECT id FROM users WHERE email = %s", (email,))
    row = cur.fetchone()
    if row is not None:
        return _id(row)
    cur.execute(
        "SELECT password_hash FROM users WHERE id = %s",
        (ADMIN_USER_ID,),
    )
    admin_hash = cur.fetchone()["password_hash"]
    cur.execute(
        "INSERT INTO users (email, password_hash, full_name, role, department, allowed_departments) "
        "VALUES (%s, %s, %s, 'loan_officer', %s, ARRAY[%s]) RETURNING id",
        (email, admin_hash, full_name, department, department),
    )
    uid = _id(cur.fetchone())
    print(f"Inserted staff {email} id={uid}")
    return uid


def assign_staff(cur, user_id: int, client_id: int) -> None:
    cur.execute(
        "INSERT INTO staff_client_assignments (user_id, client_id) "
        "VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (user_id, client_id),
    )


def ensure_sop(cur, title: str, department: str, body: str, created_by: int) -> int:
    cur.execute("SELECT id FROM sops WHERE title = %s", (title,))
    row = cur.fetchone()
    if row is not None:
        return _id(row)
    cur.execute(
        "INSERT INTO sops (title, department, body, version, created_by) "
        "VALUES (%s, %s, %s, 1, %s) RETURNING id",
        (title, department, body, created_by),
    )
    sid = _id(cur.fetchone())
    print(f"Inserted SOP '{title}' id={sid}")
    return sid


def insert_doc(
    cur,
    title: str,
    doc_type: str,
    department: str,
    client_id: int | None,
    property_id: int | None,
    approval_status: str,
    is_approved: bool,
    chunks: list[str],
) -> int:
    cur.execute("SELECT id FROM documents WHERE title = %s", (title,))
    if cur.fetchone() is not None:
        print(f"Skip existing doc: {title}")
        return 0
    cur.execute(
        "INSERT INTO documents "
        "(title, doc_type, department, client_id, property_id, "
        " approval_status, is_approved, approved_by, approved_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW()) RETURNING id",
        (title, doc_type, department, client_id, property_id, approval_status, is_approved, ADMIN_USER_ID),
    )
    doc_id = _id(cur.fetchone())
    for chunk in chunks:
        cur.execute(
            "INSERT INTO document_chunks "
            "(document_id, content, content_hash, chunk_type, department, "
            " is_active, is_approved, approval_status, approved_by, approved_at) "
            "VALUES (%s, %s, %s, %s, %s, true, %s, %s, %s, NOW())",
            (doc_id, chunk, sha(chunk), "paragraph", department, is_approved, approval_status, ADMIN_USER_ID),
        )
    print(f"Inserted doc '{title}' id={doc_id} ({len(chunks)} chunks, approved={is_approved})")
    return doc_id


def main() -> None:
    with acquire() as conn:
        with conn.cursor() as cur:
            client2_id = ensure_client(cur, "client2@asto.local", "Client Two")
            property2_id = ensure_property(cur, client2_id, "456 Oak Ave")

            # Cases + status timelines for both clients.
            case1_id = ensure_case(cur, "CAS-2026-0001", CLIENT1_ID, PROPERTY1_ID, 275000.00, "under_review")
            add_case_event(cur, case1_id, "submitted", "Application submitted online")
            add_case_event(cur, case1_id, "under_review", "Documents received; underwriting review in progress")
            case2_id = ensure_case(cur, "CAS-2026-0002", client2_id, property2_id, 185000.00, "active")
            add_case_event(cur, case2_id, "submitted", "Application submitted")
            add_case_event(cur, case2_id, "active", "Loan approved and active")

            # Staff user for the portal demo (loan_officer, dept: general).
            staff_id = ensure_staff(cur, "staff@asto.local", "Dana Officer", "general")
            assign_staff(cur, staff_id, CLIENT1_ID)
            assign_staff(cur, staff_id, client2_id)

            # Collaboration note on client 1's case.
            cur.execute("SELECT 1 FROM case_notes WHERE case_id = %s", (case1_id,))
            if cur.fetchone() is None:
                cur.execute(
                    "INSERT INTO case_notes (case_id, user_id, body) VALUES (%s, %s, %s)",
                    (case1_id, staff_id, "Waiting on the borrower's most recent pay stubs."),
                )
                print("Inserted case note on CAS-2026-0001")

            # Active workflows.
            def ensure_workflow(title, department, case_id, status, assigned_to):
                cur.execute("SELECT id FROM workflows WHERE title = %s", (title,))
                if cur.fetchone() is not None:
                    return
                cur.execute(
                    "INSERT INTO workflows (title, department, case_id, status, assigned_to) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (title, department, case_id, status, assigned_to),
                )
                print(f"Inserted workflow '{title}'")

            ensure_workflow("Income verification", "general", case1_id, "in_progress", staff_id)
            ensure_workflow("Appraisal ordering", "general", case1_id, "review", staff_id)
            ensure_workflow("Title review", "property_management", case2_id, "in_progress", staff_id)

            # Official SOPs.
            ensure_sop(
                cur,
                "Mortgage Application Intake SOP",
                "general",
                "All applications must be logged in the case system within one business day. "
                "Collect proof of income, bank statements, and tax returns before submitting to underwriting.",
                staff_id,
            )
            ensure_sop(
                cur,
                "Late Payment Escalation SOP",
                "general",
                "When a payment is 5+ days late, send the standard notice, apply the 3% late fee, "
                "and flag the case for the collections workflow.",
                ADMIN_USER_ID,
            )

            # Pending SOP access request from the staff user (admin reviews).
            cur.execute(
                "SELECT 1 FROM sop_access_requests WHERE user_id = %s AND status = 'pending'",
                (staff_id,),
            )
            if cur.fetchone() is None:
                cur.execute(
                    "INSERT INTO sop_access_requests (user_id, action, department, reason) "
                    "VALUES (%s, 'create', 'general', 'Building out the intake runbook for our team.')",
                    (staff_id,),
                )
                print("Inserted pending SOP access request")

            insert_doc(
                cur,
                "123 Main St Lease & Policy Guide",
                "policy",
                "property_management",
                CLIENT1_ID,
                PROPERTY1_ID,
                "approved",
                True,
                [
                    "123 Main St — rent is due on the 1st of each month. A late fee of 3% is applied after 5 days.",
                    "To vacate, residents must give 30 days written notice before the end of the lease term.",
                    "Renters insurance is required. Proof of insurance must be submitted to the property office.",
                    "Lawn care and minor exterior maintenance at 123 Main St are the resident's responsibility.",
                ],
            )
            insert_doc(
                cur,
                "Lease Addendum - Pet Policy (Pending Review)",
                "policy",
                "property_management",
                CLIENT1_ID,
                PROPERTY1_ID,
                "pending",
                False,
                [
                    "Pets up to 50 lbs are allowed at 123 Main St with a one-time $300 non-refundable pet fee.",
                ],
            )
            insert_doc(
                cur,
                "Acme Residences Handbook",
                "policy",
                "property_management",
                client2_id,
                property2_id,
                "approved",
                True,
                [
                    "At 456 Oak Ave rent is due on the 1st of each month with a 5% late fee after 7 days.",
                    "Pets up to 40 lbs are allowed with a one-time $250 pet fee. No renters insurance required.",
                    "Office hours are Monday to Friday, 9am to 5pm. Submit maintenance requests through the portal.",
                ],
            )
            insert_doc(
                cur,
                "Asto Assist Company Handbook",
                "manual",
                "general",
                None,
                None,
                "approved",
                True,
                [
                    "Asto Assist provides 24/7 access to a knowledge assistant for all staff and clients.",
                    "Maintenance requests are triaged within 4 business hours. Submit them via the client portal.",
                ],
            )
        conn.commit()

    # Backfill embeddings for approved chunks only.
    with acquire() as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                "SELECT id, content FROM document_chunks "
                "WHERE is_approved = true AND embedding IS NULL ORDER BY id"
            )
            rows = cur.fetchall()
    if not rows:
        print("No chunks need embeddings.")
        return
    texts = [r["content"] for r in rows]
    print(f"Generating embeddings for {len(rows)} approved chunks...")
    embeddings = generate_embeddings(texts)
    with acquire() as conn:
        with conn.cursor() as cur:
            for row, emb in zip(rows, embeddings):
                cur.execute("UPDATE document_chunks SET embedding = %s WHERE id = %s", (emb, row["id"]))
        conn.commit()
    print(f"Backfilled embeddings for {len(rows)} chunks.")


if __name__ == "__main__":
    main()
