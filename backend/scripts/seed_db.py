"""Seed the database with an admin user and test documents."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from passlib.hash import bcrypt
from app.db.postgres.session import acquire

ADMIN_PASSWORD_HASH = "$2b$12$B5z08U8N66Hn2E/s6RIuZuti.MxB5wpWjWNySk2h6qXooQSAUOnHK"

# client@asto.local / client123
CLIENT_PASSWORD_HASH = bcrypt.hash("client123")


def seed() -> None:
    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM users WHERE email = %s",
                ("admin@asto.local",),
            )
            existing = cur.fetchone()
            if existing:
                print("Admin user already exists, skipping.")
            else:
                cur.execute(
                    "INSERT INTO users (email, password_hash, full_name, role, department, allowed_departments) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                    (
                        "admin@asto.local",
                        ADMIN_PASSWORD_HASH,
                        "Admin User",
                        "super_admin",
                        "general",
                        ["general", "compliance", "underwriting"],
                    ),
                )
                print("Admin user created.")

            # --- Client audience seed (Phase B/C) ---
            cur.execute(
                "SELECT id FROM clients WHERE email = %s",
                ("client@asto.local",),
            )
            client_row = cur.fetchone()
            if client_row:
                client_id = client_row["id"]
                print("Seed client already exists, skipping.")
            else:
                cur.execute(
                    "INSERT INTO clients (email, password_hash, full_name) "
                    "VALUES (%s, %s, %s) RETURNING id",
                    ("client@asto.local", CLIENT_PASSWORD_HASH, "Client User"),
                )
                client_id = cur.fetchone()["id"]
                print(f"Client created (id={client_id}).")

                cur.execute(
                    "INSERT INTO properties (client_id, address, city, state, postal_code, property_type) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (client_id, "123 Main St", "Springfield", "IL", "62701", "single_family"),
                )
                cur.execute(
                    "INSERT INTO cases (case_number, client_id, loan_amount, status) "
                    "VALUES (%s, %s, %s, %s)",
                    ("CAS-2026-0001", client_id, 275000.00, "active"),
                )
                cur.execute(
                    "SELECT id FROM users WHERE email = 'admin@asto.local'",
                )
                admin = cur.fetchone()
                if admin:
                    cur.execute(
                        "INSERT INTO staff_client_assignments (user_id, client_id) "
                        "VALUES (%s, %s) ON CONFLICT (user_id, client_id) DO NOTHING",
                        (admin["id"], client_id),
                    )
                    print("Assigned admin to seed client.")

            # --- A document pending review (Phase B3 demo) ---
            cur.execute(
                "SELECT id FROM documents WHERE title = %s",
                ("Draft Credit Policy (Pending Review)",),
            )
            if cur.fetchone():
                print("Pending review document already exists, skipping.")
            else:
                cur.execute(
                    "INSERT INTO documents (title, source_path, doc_type, department, "
                    "approval_status, is_approved) "
                    "VALUES (%s, %s, %s, %s, 'pending', false) RETURNING id",
                    ("Draft Credit Policy (Pending Review)", "/docs/draft_credit_policy.pdf",
                     "policy", "general"),
                )
                pending_doc_id = cur.fetchone()["id"]
                cur.execute(
                    "INSERT INTO document_chunks (document_id, content, content_hash, section, chunk_type, department, approval_status, is_approved) "
                    "VALUES (%s, %s, md5(%s), %s, %s, %s, 'pending', false)",
                    (
                        pending_doc_id,
                        "This draft credit policy is awaiting review and must not be "
                        "searchable until approved.",
                        "This draft credit policy is awaiting review and must not be "
                        "searchable until approved.",
                        "draft policy",
                        "paragraph",
                        "general",
                    ),
                )
                print("Pending review document created.")

            cur.execute(
                "SELECT id FROM documents WHERE title = %s",
                ("Sample Policy Document",),
            )
            if cur.fetchone():
                print("Sample document already exists, skipping.")
                return

            cur.execute(
                "INSERT INTO documents (title, source_path, doc_type, department) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                ("Sample Policy Document", "/docs/sample_policy.pdf", "policy", "general"),
            )
            doc_id = cur.fetchone()["id"]

            cur.execute(
                "INSERT INTO documents (title, source_path, doc_type, department) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                ("Eligibility Guidelines", "/docs/eligibility.pdf", "policy", "general"),
            )
            doc2_id = cur.fetchone()["id"]

            chunks = [
                (doc_id, "Credit scores are a key factor in determining loan eligibility. A minimum score of 620 is typically required for standard programs.", "credit score requirements", "paragraph"),
                (doc_id, "Documentation required for loan applications includes proof of income, tax returns, bank statements, and employment verification.", "required documents", "paragraph"),
                (doc_id, "The debt-to-income ratio must not exceed 43% for qualified mortgage products. Some programs allow higher ratios with compensating factors.", "dti requirements", "paragraph"),
                (doc2_id, "First-time homebuyers may qualify for programs with lower down payment requirements and reduced closing costs.", "first-time buyer programs", "paragraph"),
                (doc2_id, "Employment history of at least two years is preferred. Gaps in employment should be explained and documented.", "employment requirements", "paragraph"),
                (doc2_id, "All applicants must provide valid government-issued identification and proof of residency.", "identity verification", "paragraph"),
            ]

            for doc_id, content, section, chunk_type in chunks:
                cur.execute(
                    "INSERT INTO document_chunks (document_id, content, content_hash, section, chunk_type, department) "
                    "VALUES (%s, %s, md5(%s), %s, %s, %s)",
                    (doc_id, content, content, section, chunk_type, "general"),
                )

            print(f"Created 2 documents with {len(chunks)} chunks.")
        conn.commit()


if __name__ == "__main__":
    seed()

