"""Bulk demo-data seeder — large volumes of realistic dummy data.

Populates the dev database at scale for UI/demos/load feel:
staff users, clients + properties + cases (with timelines), a knowledge
base of multi-chunk documents (embeddings backfilled), tasks, workflows
(some deliberately overdue), appointments, conversations, notifications,
audit history, knowledge gaps, feedback, synonyms, and saved searches.

Deterministic (fixed RNG seed) and re-runnable: every row is keyed by a
natural unique value so re-runs skip what already exists.

Usage (from backend/, with the repo-root embedding cache):
    ASTO_EMBEDDING_CACHE_DIR=../nlp_models/embeddings \
        python -m scripts.seed_bulk_demo [--clients 40] [--kb-docs 30]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
from psycopg.types.json import Json

from app.db.postgres.session import acquire

random.seed(42)

FIRST_NAMES = [
    "Ava", "Liam", "Noah", "Mia", "Ethan", "Zoe", "Lucas", "Emma", "Owen",
    "Sofia", "Caleb", "Isla", "Mason", "Ruby", "Logan", "Nora", "Jack",
    "Lily", "Henry", "Grace", "Leo", "Chloe", "Silas", "Hazel", "Jonah",
    "Violet", "Rhys", "Stella", "Micah", "Aurora", "Felix", "Daisy",
]
LAST_NAMES = [
    "Carter", "Nguyen", "Patel", "Gomez", "Brooks", "Okafor", "Sharma",
    "Kelly", "Moreau", "Tanaka", "Silva", "Novak", "Haddad", "Olsen",
    "Reyes", "Kowalski", "Mbeki", "Rossi", "Larsen", "Duarte",
]
STREETS = [
    "Maple St", "Oak Ave", "Cedar Ln", "Birchwood Dr", "Sunset Blvd",
    "River Rd", "Hillcrest Ave", "Willow Way", "Pine Hollow", "Elm Ct",
]
CITIES = [("Springfield", "IL", "62704"), ("Riverton", "IL", "62561"),
          ("Sherman", "IL", "62684"), ("Athens", "IL", "62613")]
DEPARTMENTS = ["general", "underwriting", "compliance"]
DOC_TYPES = ["policy", "faq", "checklist", "rate_sheet", "form", "manual"]
KB_TOPICS = {
    "policy": [
        "Loan servicing transfers require a 15-day advance written notice to the borrower.",
        "Escrow accounts are analyzed annually; shortages under $50 are waived automatically.",
        "Rate lock extensions cost 0.125 points per 7 days beyond the original expiration.",
        "Late charges post to the ledger the business day after the grace period ends.",
        "Payoff quotes remain valid for 10 calendar days from issuance.",
        "Insurance lapses trigger force-placed coverage at the borrower's expense after 45 days.",
    ],
    "faq": [
        "Biweekly payment plans split the monthly amount and post every 14 days.",
        "An APR reflects interest plus fees; the note rate covers interest only.",
        "Appraisal waivers are issued by the automated underwriting system, not by staff.",
        "Gift funds above 5% of the purchase price require a signed donor letter.",
        "Self-employed borrowers need two years of returns including all schedules.",
        "Subordination requests are answered within ten business days.",
    ],
    "checklist": [
        "Verify identity documents are current and legible before upload.",
        "Confirm employment history covers at least 24 contiguous months.",
        "Match every large deposit on bank statements to a documented source.",
        "Ensure the purchase agreement is signed by all parties on all pages.",
        "Check that the appraisal effective date precedes the clear-to-close.",
    ],
    "rate_sheet": [
        "30-year fixed pricing assumes a 740 median FICO and 25% down.",
        "Conforming loan limits adjust each January with the FHFA index.",
        "High-balance tiers add 0.25 points above base pricing.",
        "Investment properties carry a 1.75% LLPA surcharge at these tiers.",
    ],
    "form": [
        "Form 1003 sections VI-VIII must be complete before submission.",
        "Use the URLA 2021 edition; legacy forms are rejected at intake.",
        "Income calculations belong on the transcript request cover sheet.",
    ],
    "manual": [
        "Underwriters document every exception with a written justification memo.",
        "Quality control samples 10% of funded loans for full-file review monthly.",
        "Wire fraud warnings must appear on every payoff disbursement email.",
    ],
}
CLIENT_DOC_TEMPLATES = [
    ("Purchase Agreement — {street}", "Purchase Agreement signed by all parties; earnest money held in escrow."),
    ("Proof of Income — {name}", "Two most recent pay stubs totaling {amount} gross monthly income."),
    ("Bank Statements — {name}", "Statements for the last two months; largest deposit explained as {reason}."),
    ("Home Inspection Report — {street}", "Inspection found minor roof wear; recommendation to monitor annually."),
    ("Insurance Binder — {street}", "Hazard insurance binder effective at closing; deductible {deductible}."),
    ("Appraisal Summary — {street}", "Appraised value {value}; comparables within one mile and six months."),
]


def sha(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def rid(row) -> int:
    return int(row["id"] if isinstance(row, dict) else row[0])


def rid_pair(row) -> tuple[int, int]:
    """Read two aliased ids (doc_id, case_id) from a dict/tuple row."""
    if isinstance(row, dict):
        return int(row["doc_id"]), int(row["case_id"])
    return int(row[0]), int(row[1])


def person(i: int) -> tuple[str, str]:
    first = FIRST_NAMES[i % len(FIRST_NAMES)]
    last = LAST_NAMES[(i * 7) % len(LAST_NAMES)]
    return first, last


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clients", type=int, default=40)
    parser.add_argument("--staff", type=int, default=8)
    parser.add_argument("--kb-docs", type=int, default=30)
    args = parser.parse_args()

    admin_id = 1
    now = datetime.now(timezone.utc)

    with acquire() as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            # ---- Staff -------------------------------------------------
            staff_ids: list[int] = []
            for i in range(args.staff):
                first, last = person(i + 20)
                email = f"{first.lower()}.{last.lower()}@asto.local"
                role = ["loan_officer", "underwriter", "compliance"][i % 3]
                dept = DEPARTMENTS[i % len(DEPARTMENTS)]
                cur.execute("SELECT id FROM users WHERE email = %s", (email,))
                row = cur.fetchone()
                if row is None:
                    cur.execute(
                        "SELECT password_hash FROM users WHERE id = %s", (admin_id,)
                    )
                    pw_hash = cur.fetchone()["password_hash"]
                    cur.execute(
                        "INSERT INTO users (email, password_hash, full_name, role, "
                        "department, allowed_departments) "
                        "VALUES (%s, %s, %s, %s, %s, ARRAY[%s]) RETURNING id",
                        (email, pw_hash, f"{first} {last}", role, dept, dept),
                    )
                    row = cur.fetchone()
                staff_ids.append(rid(row))
            print(f"staff ready: {len(staff_ids)}")

            # ---- Clients + properties + cases --------------------------
            case_ids: list[tuple[int, int]] = []  # (case_id, client_id)
            client_ids: list[int] = []
            for i in range(args.clients):
                first, last = person(i)
                email = f"demo{i + 1}.{last.lower()}@client.local"
                cur.execute("SELECT id FROM clients WHERE email = %s", (email,))
                row = cur.fetchone()
                if row is None:
                    cur.execute(
                        "SELECT password_hash FROM clients WHERE id = %s", (admin_id,)
                    )
                    pw_hash = cur.fetchone()["password_hash"]
                    cur.execute(
                        "INSERT INTO clients (email, full_name, password_hash, is_active) "
                        "VALUES (%s, %s, %s, true) RETURNING id",
                        (email, f"{first} {last}", pw_hash),
                    )
                    row = cur.fetchone()
                client_id = rid(row)
                client_ids.append(client_id)

                city, state, zipc = CITIES[i % len(CITIES)]
                address = f"{100 + i * 7} {STREETS[i % len(STREETS)]}"
                cur.execute("SELECT id FROM properties WHERE address = %s", (address,))
                row = cur.fetchone()
                if row is None:
                    cur.execute(
                        "INSERT INTO properties (client_id, address, city, state, "
                        "postal_code, property_type) VALUES (%s, %s, %s, %s, %s, %s) "
                        "RETURNING id",
                        (client_id, address, city, state, zipc,
                         random.choice(["single_family", "condo", "townhouse"])),
                    )
                    row = cur.fetchone()
                property_id = rid(row)

                prefix = ["PUR", "REF", "HEL"][i % 3]
                case_number = f"{prefix}-2026-{1000 + i}"
                cur.execute("SELECT id FROM cases WHERE case_number = %s", (case_number,))
                row = cur.fetchone()
                if row is None:
                    status = random.choice(
                        ["submitted", "under_review", "active", "approved", "closed"]
                    )
                    loan = random.randrange(120_000, 750_000, 5000)
                    created = now - timedelta(days=random.randint(5, 120))
                    cur.execute(
                        "INSERT INTO cases (case_number, client_id, property_id, "
                        "loan_amount, status, created_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                        (case_number, client_id, property_id, float(loan), status,
                         created),
                    )
                    case_id = rid(cur.fetchone())
                    cur.execute(
                        "INSERT INTO case_events (case_id, status, note, created_at) "
                        "VALUES (%s, 'submitted', 'Application submitted online', %s)",
                        (case_id, created),
                    )
                    cur.execute(
                        "INSERT INTO case_events (case_id, status, note, created_at) "
                        "VALUES (%s, %s, %s, %s)",
                        (case_id, status,
                         random.choice([
                             "Documents received; review underway",
                             "Clear to close issued",
                             "Awaiting borrower uploads",
                             "Underwriting conditions satisfied",
                         ]),
                         created + timedelta(days=random.randint(1, 9))),
                    )
                else:
                    case_id = rid(row)
                case_ids.append((case_id, client_id))

                assignee = random.choice(staff_ids)
                cur.execute(
                    "INSERT INTO staff_client_assignments (user_id, client_id) "
                    "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (assignee, client_id),
                )
            print(f"clients/cases ready: {len(client_ids)}")

            # ---- Knowledge-base documents ------------------------------
            def insert_doc(title, doc_type, department, client_id, property_id,
                           approved, chunks, tags=None, review_days=None,
                           source_path=None):
                cur.execute("SELECT id FROM documents WHERE title = %s", (title,))
                if cur.fetchone() is not None:
                    return None
                review_due = (
                    (now + timedelta(days=review_days)).date()
                    if review_days is not None
                    else None
                )
                cur.execute(
                    "INSERT INTO documents (title, doc_type, department, client_id, "
                    "property_id, approval_status, is_approved, approved_by, "
                    "approved_at, review_due, tags, pii_flagged, source_path) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s) "
                    "RETURNING id",
                    (title, doc_type, department, client_id, property_id,
                     "approved" if approved else "pending", approved, admin_id,
                     review_due, tags or [], random.random() < 0.05, source_path),
                )
                doc_id = rid(cur.fetchone())
                for idx, chunk in enumerate(chunks):
                    cur.execute(
                        "INSERT INTO document_chunks (document_id, content, "
                        "content_hash, chunk_type, section, department, is_active, "
                        "is_approved, approval_status, approved_by, approved_at) "
                        "VALUES (%s, %s, %s, 'paragraph', %s, %s, true, %s, %s, "
                        "%s, NOW())",
                        (doc_id, chunk, sha(chunk),
                         f"Section {idx + 1}", department, approved, 
                         "approved" if approved else "pending", admin_id),
                    )
                return doc_id

            kb_new = 0
            for i in range(args.kb_docs):
                doc_type = DOC_TYPES[i % len(DOC_TYPES)]
                dept = DEPARTMENTS[i % len(DEPARTMENTS)]
                facts = KB_TOPICS[doc_type]
                version = i // len(DOC_TYPES) + 1
                title = f"{doc_type.replace('_', ' ').title()} KB v{version} — {dept.title()}"
                chunks = random.sample(facts, k=min(len(facts), random.randint(3, len(facts))))
                chunks += [
                    f"Applies to loans registered after {random.randint(2019, 2026)}.",
                    f"Questions route to the {dept} queue; SLA is two business days.",
                ]
                review_days = random.choice([None, 90, 180, -10, -30])
                if insert_doc(title, doc_type, dept, None, None, True, chunks,
                              tags=random.sample(["core", "reference", "training",
                                                  "external"], k=2),
                              review_days=review_days):
                    kb_new += 1
            print(f"KB documents inserted: {kb_new}")

            # ---- Client-specific documents -----------------------------
            client_new = 0
            for j, (case_id, client_id) in enumerate(case_ids[: max(1, len(case_ids) // 2)]):
                first, last = person(j)
                cur.execute(
                    "SELECT p.address FROM cases c JOIN properties p ON p.id = c.property_id "
                    "WHERE c.id = %s",
                    (case_id,),
                )
                row = cur.fetchone()
                street = (row["address"] if isinstance(row, dict) else row[0]) if row else "Main St"
                template, body = CLIENT_DOC_TEMPLATES[j % len(CLIENT_DOC_TEMPLATES)]
                title = template.format(street=street, name=f"{first} {last}")
                body_full = body.format(
                    amount=f"${random.randrange(4000, 12000)}",
                    reason=random.choice(["payroll", "tax refund", "gift from family"]),
                    value=f"${random.randrange(150, 600)},000",
                    deductible="$1,000",
                )
                approved = j % 4 != 0
                if insert_doc(title, "form", "general", client_id,
                              None, approved, [body_full],
                              source_path=f"processed/demo_{case_id}_{j}.pdf"):
                    client_new += 1
            print(f"client documents inserted: {client_new}")

            # ---- SOPs ----------------------------------------------------
            for i in range(6):
                dept = DEPARTMENTS[i % len(DEPARTMENTS)]
                title = f"SOP: {dept.title()} procedure {i + 1}"
                cur.execute("SELECT id FROM sops WHERE title = %s", (title,))
                if cur.fetchone() is None:
                    cur.execute(
                        "INSERT INTO sops (title, department, body, version, created_by) "
                        "VALUES (%s, %s, %s, 1, %s)",
                        (title, dept,
                         "Follow the intake checklist, verify all conditions, then "
                         "route to quality control for sign-off.",
                         random.choice(staff_ids)),
                    )

            # ---- Tasks / workflows / appointments ------------------------
            for i, (case_id, _client) in enumerate(case_ids[:60]):
                due = now + timedelta(days=random.randint(-14, 21))
                status = "overdue" if due < now else random.choice(
                    ["pending", "assigned", "in_progress"])
                cur.execute(
                    "SELECT 1 FROM tasks WHERE title = %s AND case_id = %s",
                    (f"Follow-up {i + 1}", case_id),
                )
                if cur.fetchone() is None:
                    cur.execute(
                        "INSERT INTO tasks (case_id, title, description, assignee_id, "
                        "due_at, status, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (case_id, f"Follow-up {i + 1}",
                         "Contact the borrower about outstanding conditions.",
                         random.choice(staff_ids), due, status, admin_id),
                    )

            for i, (case_id, _client) in enumerate(case_ids[:40]):
                title = f"Workflow: processing step {i + 1}"
                cur.execute("SELECT id FROM workflows WHERE title = %s", (title,))
                if cur.fetchone() is None:
                    due = now + timedelta(days=random.randint(-10, 20))
                    cur.execute(
                        "INSERT INTO workflows (title, department, case_id, status, "
                        "assigned_to, due_at, created_at, updated_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (title, random.choice(DEPARTMENTS), case_id,
                         random.choice(["in_progress", "review"]),
                         random.choice(staff_ids), due, now, now),
                    )

            for i in range(15):
                start = now + timedelta(days=random.randint(1, 10),
                                        hours=random.randint(0, 6))
                title = f"Borrower call {i + 1}"
                cur.execute("SELECT 1 FROM appointments WHERE title = %s AND staff_id = %s",
                            (title, staff_ids[i % len(staff_ids)]))
                if cur.fetchone() is None:
                    cur.execute(
                        "INSERT INTO appointments (title, description, start_at, end_at, "
                        "department, staff_id, status) VALUES (%s, %s, %s, %s, %s, %s, 'scheduled')",
                        (title, "Discuss closing timeline.", start,
                         start + timedelta(hours=1), "general",
                         staff_ids[i % len(staff_ids)]),
                    )

            # ---- Conversations + messages --------------------------------
            for i, (_case_id, client_id) in enumerate(case_ids[:20]):
                cur.execute(
                    "SELECT id FROM conversations WHERE client_id = %s LIMIT 1",
                    (client_id,),
                )
                row = cur.fetchone()
                if row is not None:
                    continue
                cur.execute(
                    "INSERT INTO conversations (client_id, subject) "
                    "VALUES (%s, %s) RETURNING id",
                    (client_id, random.choice([
                        "Question about my statement",
                        "Upload confirmation",
                        "Closing date",
                    ])),
                )
                conv_id = rid(cur.fetchone())
                staff_id = random.choice(staff_ids)
                msgs = [
                    ("client", "Hi, did my document come through okay?"),
                    ("staff", "Yes — it's in review. We'll update you within two business days."),
                    ("client", "Great, thanks!"),
                ]
                for sender, body in msgs:
                    cur.execute(
                        "INSERT INTO messages (conversation_id, sender_type, "
                        "sender_client_id, sender_user_id, body) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (conv_id, sender,
                         client_id if sender == "client" else None,
                         staff_id if sender == "staff" else None,
                         body),
                    )

            # ---- Audit history / gaps / feedback ---------------------------
            gap_queries = [
                "escrow waiver deadline", "pmi removal steps", "waver form",
                "heloc draw period", "appraisal dispute proccess",
                "escrow acount analysis", "how do i remove pmi early",
                "recast mortgage payment", "impound account rules",
                "streamline refinance checklist",
            ]
            for day in range(13, -1, -1):
                ts = now - timedelta(days=day, hours=random.randint(0, 8))
                for q in range(random.randint(2, 5)):
                    outcome = random.choices(
                        ["answer", "partial", "no_answer"],
                        weights=[7, 2, 1], k=1)[0]
                    confidence = {"answer": random.uniform(88, 99),
                                  "partial": random.uniform(55, 80),
                                  "no_answer": random.uniform(5, 40)}[outcome]
                    cur.execute(
                        "INSERT INTO audit_log (user_id, audience, query, sub_queries, "
                        "retrieved_ids, confidence, response_id, outcome, latency_ms, "
                        "created_at) VALUES (%s, 'staff', %s, %s, %s, %s, %s, %s, %s, %s)",
                        (random.choice(staff_ids),
                         random.choice(KB_TOPICS[random.choice(list(KB_TOPICS))]).split(";")[0].lower(),
                         Json([]), [], round(confidence, 1),
                         f"seed{day}{q}{random.randint(1000, 9999)}",
                         outcome, random.uniform(8, 40), ts),
                    )

            for gq in gap_queries:
                for _ in range(random.randint(2, 5)):
                    cur.execute(
                        "INSERT INTO knowledge_gaps (query, intent, confidence, created_at) "
                        "VALUES (%s, 'general', %s, %s)",
                        (gq, round(random.uniform(10, 45), 1),
                         now - timedelta(days=random.randint(0, 29))),
                    )

            for i in range(18):
                cur.execute(
                    "INSERT INTO feedback (user_id, response_id, rating, comment, created_at) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (random.choice(staff_ids), f"seedfb{i}",
                     1 if i % 3 else -1,
                     None if i % 3 else "Did not answer the question fully.",
                     now - timedelta(days=random.randint(0, 14))),
                )

            # ---- Synonyms / saved searches / templates ---------------------
            synonym_pairs = [
                ("earnest money", "deposit"),
                ("escrow", "impound"),
                ("closing costs", "settlement fees"),
                ("PMI", "private mortgage insurance"),
                ("clear to close", "CTC"),
            ]
            for canonical, alias in synonym_pairs:
                cur.execute(
                    "SELECT 1 FROM synonyms WHERE canonical = %s AND alias = %s",
                    (canonical, alias),
                )
                if cur.fetchone() is None:
                    cur.execute(
                        "INSERT INTO synonyms (canonical, alias) VALUES (%s, %s)",
                        (canonical, alias),
                    )

            for i, sid in enumerate(staff_ids[:4]):
                cur.execute(
                    "SELECT 1 FROM saved_searches WHERE user_id = %s AND query = %s",
                    (sid, f"escrow analysis rules {i}"),
                )
                if cur.fetchone() is None:
                    cur.execute(
                        "INSERT INTO saved_searches (user_id, query, filters) "
                        "VALUES (%s, %s, %s)",
                        (sid, f"escrow analysis rules {i}", Json({})),
                    )

            templates = [
                ("Docs received", "Thanks! Your documents arrived and are in review."),
                ("Closing reminder", "Your closing is scheduled. Please bring ID and the cashier's check."),
            ]
            for name, body in templates:
                cur.execute("SELECT 1 FROM message_templates WHERE name = %s", (name,))
                if cur.fetchone() is None:
                    cur.execute(
                        "INSERT INTO message_templates (name, body, department) "
                        "VALUES (%s, %s, 'general')",
                        (name, body),
                    )

            # ---- Notifications for admins ----------------------------------
            for i in range(5):
                cur.execute(
                    "INSERT INTO notifications (user_id, type, title, body, link, is_read) "
                    "VALUES (%s, 'info', %s, %s, '/admin', %s)",
                    (admin_id, f"Demo notification {i + 1}",
                     "Seeded by scripts.seed_bulk_demo.", i > 2),
                )

            # ---- Signature requests ----------------------------------------
            cur.execute(
                "SELECT d.id AS doc_id, c.id AS case_id FROM documents d "
                "JOIN cases c ON c.client_id = d.client_id "
                "WHERE d.approval_status = 'approved' AND d.client_id IS NOT NULL "
                "LIMIT 3"
            )
            for row in cur.fetchall():
                doc_id, case_id = rid_pair(row)
                token_seed = f"seed-sig-{doc_id}-{case_id}"
                cur.execute(
                    "SELECT 1 FROM signature_requests WHERE document_id = %s AND case_id = %s",
                    (doc_id, case_id),
                )
                if cur.fetchone() is None:
                    cur.execute(
                        "INSERT INTO signature_requests (case_id, document_id, "
                        "requested_from, token, status) VALUES (%s, %s, 'client', %s, 'pending')",
                        (case_id, doc_id, hashlib.sha256(token_seed.encode()).hexdigest()[:32]),
                    )

        conn.commit()
    print("Bulk seed complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
