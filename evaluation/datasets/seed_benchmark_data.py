"""Seed documents and chunks for benchmark retrieval testing.

Creates predictable content matching the eval dataset topics, then
returns a mapping of topic-key -> set of chunk_ids so the benchmark
can compute recall, MRR, nDCG, hit rate, precision.

The content is designed to match the questions in eval_questions.py.
Run this before running the retrieval phase of run_benchmark.py.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict

from app.db.postgres.session import acquire


# Marker written to documents.source_path for every row this seeder
# creates. clear_benchmark_data() deletes ONLY rows carrying this marker,
# so it can never wipe unrelated (dev/production) documents — see the
# docstring of clear_benchmark_data (design decision 2026-08-09).
BENCHMARK_SOURCE = "__benchmark_seed__"


BENCHMARK_DOCS = [
    {
        "title": "Mortgage Eligibility Guidelines",
        "doc_type": "policy",
        "department": "general",
        "chunks": [
            ("Credit score requirements", "paragraph",
             "The minimum credit score for a conventional loan is 620. For FHA loans, a score of 580 or higher is required with a 3.5% down payment. VA loans typically require a minimum credit score of 580."),
            ("LTV limits", "paragraph",
             "The maximum loan-to-value ratio for a conventional loan is 80% without private mortgage insurance. With PMI, borrowers can qualify with up to 97% LTV. Investment properties typically require a lower LTV of 75% or less."),
            ("Down payment", "paragraph",
             "Conventional loans typically require a minimum down payment of 3%. FHA loans require as little as 3.5%. VA loans require no down payment for eligible veterans."),
            ("Employment", "paragraph",
             "Borrowers must demonstrate stable employment history for at least two years. Income and employment verification includes recent pay stubs, W-2 forms, and tax returns."),
        ],
    },
    {
        "title": "Required Documentation for Loan Applications",
        "doc_type": "checklist",
        "department": "general",
        "chunks": [
            ("Documentation requirements", "checklist",
             "Required documents include: proof of income (pay stubs, W-2s, tax returns), bank statements for the past two months, employment verification letter, government-issued photo ID, and proof of residence."),
        ],
    },
    {
        "title": "FHA and VA Loan Comparison Guide",
        "doc_type": "reference",
        "department": "general",
        "chunks": [
            ("FHA loans", "paragraph",
             "Federal Housing Administration (FHA) loans are government-backed mortgages with lower credit score requirements and smaller down payments. Key benefits include lower credit score thresholds and higher debt-to-income ratios allowed."),
            ("VA loans", "paragraph",
             "Veterans Affairs (VA) loans are available to eligible veterans, active-duty service members, and qualifying spouses. These loans require no down payment and no private mortgage insurance, with competitive interest rates."),
            ("FHA vs VA differences", "table",
             "FHA loans require a 3.5% down payment and have annual mortgage insurance premiums. VA loans require no down payment and no PMI, but include a funding fee. FHA is for primary residences only; VA also allows secondary residences."),
        ],
    },
    {
        "title": "Closing Process and Fee Schedule",
        "doc_type": "process",
        "department": "general",
        "chunks": [
            ("Closing process", "paragraph",
             "The closing process involves a final walk-through, signing of loan documents, and payment of closing costs. The closing disclosure must be provided at least three business days before closing."),
            ("Closing costs", "paragraph",
             "Typical closing costs include loan origination fees, appraisal fees, title insurance, credit report fees, and prepaid items like property taxes and homeowner's insurance. Total closing costs typically range from 2% to 5% of the loan amount."),
            ("Fees", "checklist",
             "Common fees paid at closing: loan origination fee, discount points, appraisal fee, credit report fee, title search and insurance, attorney fees, recording fees, and prepaid interest."),
        ],
    },
    {
        "title": "Debt-to-Income and Credit Guidelines",
        "doc_type": "policy",
        "department": "underwriting",
        "chunks": [
            ("Debt-to-income limits", "paragraph",
             "The maximum debt-to-income (DTI) ratio for a conventional loan is 43%. FHA loans may allow a debt-to-income ratio up to 57% with compensating factors. A lower DTI ratio improves your chances of approval."),
            ("Credit report review", "paragraph",
             "Lenders pull a tri-merge credit report at application. The credit report shows payment history, outstanding balances, and hard inquiries, and it is used to calculate your credit score."),
        ],
    },
    {
        "title": "Interest Rates and Mortgage Insurance",
        "doc_type": "reference",
        "department": "underwriting",
        "chunks": [
            ("Interest rates", "paragraph",
             "Mortgage interest rates vary with market conditions, credit score, and loan term. A fixed-rate mortgage locks in one interest rate for the full term, while an adjustable-rate mortgage changes after an initial period."),
            ("APR explained", "paragraph",
             "The annual percentage rate (APR) includes the interest rate plus lender fees and discount points, giving a fuller picture of the total cost of credit than the nominal interest rate alone."),
            ("Private mortgage insurance", "paragraph",
             "Private mortgage insurance (PMI) is required when the down payment is less than 20% of the purchase price. PMI protects the lender, and it is typically cancelled once you reach 20% equity."),
            ("FHA mortgage insurance premium", "paragraph",
             "FHA loans charge an upfront mortgage insurance premium (MIP) of 1.75% plus an annual MIP for the life of the loan in most cases. The MIP protects the lender against default."),
        ],
    },
    {
        "title": "Property Types and Occupancy Guide",
        "doc_type": "reference",
        "department": "underwriting",
        "chunks": [
            ("Investment properties", "paragraph",
             "Investment properties require a minimum down payment of 15% to 20% and often carry higher interest rates. Rental income from the investment property may be used to qualify for the loan."),
            ("Second homes", "paragraph",
             "A second home or vacation home typically requires a 10% down payment and cannot be rented for most of the year. Second-home financing rules differ from investment property rules."),
            ("Multi-unit properties", "paragraph",
             "Multi-unit properties up to four units are eligible for FHA financing when the borrower occupies one of the units. The loan-to-value limit is lower for higher unit counts."),
            ("Manufactured homes", "paragraph",
             "Manufactured and mobile homes may be financed with FHA Title I or conventional loans when they meet HUD installation requirements. A permanent foundation is generally required."),
            ("Occupancy requirements", "paragraph",
             "Owner-occupied primary residences generally qualify for the best rates and lowest down-payment requirements. Occupancy is verified at closing and shortly after move-in."),
        ],
    },
    {
        "title": "Loan Process and Timeline Guide",
        "doc_type": "process",
        "department": "operations",
        "chunks": [
            ("Pre-approval", "paragraph",
             "Pre-approval verifies your income, assets, and credit before you shop for a home. A pre-approval letter is typically valid for about 90 days and strengthens your offer."),
            ("Appraisal", "paragraph",
             "An appraisal determines the fair market value of the property being purchased. The appraisal report is reviewed by the underwriter before final approval of the loan."),
            ("Escrow", "paragraph",
             "Escrow holds the buyer's earnest money deposit and coordinates the transfer of funds at closing. The escrow account also collects property taxes and homeowner's insurance payments for the lender."),
            ("Underwriting", "paragraph",
             "Underwriting is the process of reviewing the complete loan file, including credit, income, assets, and the appraisal. The underwriter may issue conditions requiring additional documentation before approval."),
            ("Rate lock", "paragraph",
             "A rate lock holds your interest rate for a set period, typically 30 to 60 days, protecting you from market changes while your loan is processed."),
        ],
    },
    {
        "title": "Refinance and Cash-Out Guide",
        "doc_type": "process",
        "department": "operations",
        "chunks": [
            ("Refinance overview", "paragraph",
             "A refinance replaces your existing mortgage with a new loan, often to lower the interest rate or change the loan term. Refinancing can also consolidate debt or shorten your repayment timeline."),
            ("Cash-out refinance", "paragraph",
             "Cash-out refinancing allows you to borrow against the equity in your home. Most lenders cap cash-out refinances at 80% loan-to-value, meaning you keep 20% equity in the home."),
        ],
    },
    {
        "title": "Specialty Loan Programs",
        "doc_type": "program_guide",
        "department": "general",
        "chunks": [
            ("Jumbo loans", "paragraph",
             "Jumbo loans exceed the conforming loan limits set by Fannie Mae and Freddie Mac. They require higher credit scores, larger reserves, and typically a larger down payment."),
            ("Adjustable-rate mortgages", "paragraph",
             "An adjustable-rate mortgage (ARM) has a fixed interest rate for an initial period, such as five years for a 5/1 ARM, and then adjusts annually based on an index."),
            ("Reverse mortgages", "paragraph",
             "A reverse mortgage, also known as a home equity conversion mortgage (HECM), allows homeowners aged 62 and older to convert home equity into cash with no monthly mortgage payment required."),
            ("Home equity line of credit", "paragraph",
             "A home equity line of credit (HELOC) is a revolving line of credit secured by your home. You can draw funds as needed during the draw period and repay over time."),
            ("USDA loans", "paragraph",
             "USDA loans are available to low and moderate income buyers in eligible rural and suburban areas. USDA loans require no down payment and feature low mortgage insurance premiums."),
            ("Gift funds", "paragraph",
             "Gift funds from a family member may be used toward the down payment. A signed gift letter confirming the funds are a gift and not a loan is required, along with proof the funds were transferred."),
            ("Bankruptcy history", "paragraph",
             "After a Chapter 7 bankruptcy, most loan programs require a two-year waiting period before a new mortgage is allowed. Chapter 13 borrowers may qualify after one year of on-time payments."),
            ("Foreclosure history", "paragraph",
             "A prior foreclosure typically requires a three- to seven-year waiting period before you can get a new mortgage, depending on the loan program and the circumstances."),
        ],
    },
]


def seed_benchmark_data() -> dict[str, set[int]]:
    """Seed documents and chunks, returning a mapping of topic -> chunk_ids.

    The keys correspond to topics referenced in the eval dataset:
    - credit_score, documents, ltv, down_payment, employment
    - fha, va, fha_va, closing, fees
    - dti, credit_report, interest_rate, apr, pmi, mip
    - investment, second_home, multi_unit, manufactured, occupancy
    - pre_approval, appraisal, escrow, underwriting, rate_lock
    - refinance, cash_out, jumbo, arm, reverse, heloc, usda
    - gift_funds, bankruptcy, foreclosure
    """
    topic_to_chunks: dict[str, set[int]] = defaultdict(set)

    with acquire() as conn:
        with conn.cursor() as cur:
            for doc in BENCHMARK_DOCS:
                cur.execute(
                    "INSERT INTO documents (title, doc_type, department, is_active, is_approved, version, source_path) "
                    "VALUES (%s, %s, %s, true, true, 1, %s) RETURNING id",
                    (doc["title"], doc["doc_type"], doc["department"], BENCHMARK_SOURCE),
                )
                doc_id = cur.fetchone()["id"]

            for doc in BENCHMARK_DOCS:
                cur.execute(
                    "SELECT id FROM documents WHERE title = %s AND source_path = %s",
                    (doc["title"], BENCHMARK_SOURCE),
                )
                doc_id = cur.fetchone()["id"]

                for section, chunk_type, content in doc["chunks"]:
                    content_hash = hashlib.md5(content.encode()).hexdigest()
                    cur.execute(
                        "INSERT INTO document_chunks "
                        "(document_id, content, content_hash, section, chunk_type, department, is_active, is_approved) "
                        "VALUES (%s, %s, %s, %s, %s, %s, true, true) RETURNING id",
                        (doc_id, content, content_hash, section, chunk_type, doc["department"]),
                    )
                    chunk_id = cur.fetchone()["id"]

                    # Categorize chunk by topic for the mapping
                    lower = content.lower()
                    if "credit score" in lower:
                        topic_to_chunks["credit_score"].add(chunk_id)
                    if "documents" in lower or "documentation" in lower or "required documents" in lower:
                        topic_to_chunks["documents"].add(chunk_id)
                    if "loan-to-value" in lower or "ltv" in lower:
                        topic_to_chunks["ltv"].add(chunk_id)
                    if "down payment" in lower:
                        topic_to_chunks["down_payment"].add(chunk_id)
                    if "employment" in lower or "income" in lower:
                        topic_to_chunks["employment"].add(chunk_id)
                    if "federal housing administration" in lower or "fha" in lower:
                        topic_to_chunks["fha"].add(chunk_id)
                    if "veterans affairs" in lower or "va loan" in lower:
                        topic_to_chunks["va"].add(chunk_id)
                    if "fha" in lower and "va" in lower:
                        topic_to_chunks["fha_va"].add(chunk_id)
                    if "closing" in lower:
                        topic_to_chunks["closing"].add(chunk_id)
                    if "fees" in lower or "fee" in lower:
                        topic_to_chunks["fees"].add(chunk_id)
                    if "debt-to-income" in lower or "dti" in lower:
                        topic_to_chunks["dti"].add(chunk_id)
                    if "credit report" in lower:
                        topic_to_chunks["credit_report"].add(chunk_id)
                    if "interest rate" in lower:
                        topic_to_chunks["interest_rate"].add(chunk_id)
                    if "annual percentage rate" in lower or "apr" in lower:
                        topic_to_chunks["apr"].add(chunk_id)
                    if "private mortgage insurance" in lower or "pmi" in lower:
                        topic_to_chunks["pmi"].add(chunk_id)
                    if "mortgage insurance premium" in lower or "mip" in lower:
                        topic_to_chunks["mip"].add(chunk_id)
                    if "investment properties" in lower:
                        topic_to_chunks["investment"].add(chunk_id)
                    if "second home" in lower or "vacation home" in lower:
                        topic_to_chunks["second_home"].add(chunk_id)
                    if "multi-unit" in lower or "four units" in lower:
                        topic_to_chunks["multi_unit"].add(chunk_id)
                    if "manufactured" in lower or "mobile homes" in lower:
                        topic_to_chunks["manufactured"].add(chunk_id)
                    if "occupancy" in lower or "owner-occupied" in lower:
                        topic_to_chunks["occupancy"].add(chunk_id)
                    if "pre-approval" in lower or "pre approval" in lower:
                        topic_to_chunks["pre_approval"].add(chunk_id)
                    if "appraisal" in lower:
                        topic_to_chunks["appraisal"].add(chunk_id)
                    if "escrow" in lower:
                        topic_to_chunks["escrow"].add(chunk_id)
                    if "underwriting" in lower:
                        topic_to_chunks["underwriting"].add(chunk_id)
                    if "rate lock" in lower:
                        topic_to_chunks["rate_lock"].add(chunk_id)
                    if "refinance" in lower:
                        topic_to_chunks["refinance"].add(chunk_id)
                    if "cash-out" in lower:
                        topic_to_chunks["cash_out"].add(chunk_id)
                    if "jumbo" in lower:
                        topic_to_chunks["jumbo"].add(chunk_id)
                    if "adjustable-rate" in lower or "arm" in lower:
                        topic_to_chunks["arm"].add(chunk_id)
                    if "reverse mortgage" in lower or "hecm" in lower:
                        topic_to_chunks["reverse"].add(chunk_id)
                    if "home equity line of credit" in lower or "heloc" in lower:
                        topic_to_chunks["heloc"].add(chunk_id)
                    if "usda" in lower:
                        topic_to_chunks["usda"].add(chunk_id)
                    if "gift funds" in lower or "gift letter" in lower:
                        topic_to_chunks["gift_funds"].add(chunk_id)
                    if "bankruptcy" in lower:
                        topic_to_chunks["bankruptcy"].add(chunk_id)
                    if "foreclosure" in lower:
                        topic_to_chunks["foreclosure"].add(chunk_id)

            # Generate embedding vectors for all chunks (required for vector search)
            try:
                from app.search.pgvector_search import embed_query
                import numpy as np

                cur.execute("SELECT id, content FROM document_chunks WHERE embedding IS NULL")
                rows = cur.fetchall()
                for row in rows:
                    chunk_id = row["id"]
                    content = row["content"]
                    embedding = embed_query(content)
                    cur.execute(
                        "UPDATE document_chunks SET embedding = %s WHERE id = %s",
                        (embedding, chunk_id),
                    )
            except Exception:
                pass

            conn.commit()

    return dict(topic_to_chunks)


def clear_benchmark_data() -> None:
    """Remove benchmark-seeded rows, leaving unrelated data untouched.

    Deletes only documents/chunks/approval entries marked with
    ``BENCHMARK_SOURCE`` in ``documents.source_path``. A previous version
    deleted ALL documents and chunks so the benchmark always measured
    retrieval against exactly the seeded corpus — safe in CI (ephemeral
    Postgres container) but destructive when run against a developer's
    real database. Scoping to the seeder's own rows keeps both safe: CI's
    container is empty anyway, so the corpus is still exactly the seeded
    content (design decision 2026-08-09).
    """
    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM approval_log WHERE document_id IN "
                "(SELECT id FROM documents WHERE source_path = %s)",
                (BENCHMARK_SOURCE,),
            )
            cur.execute(
                "DELETE FROM document_chunks WHERE document_id IN "
                "(SELECT id FROM documents WHERE source_path = %s)",
                (BENCHMARK_SOURCE,),
            )
            cur.execute(
                "DELETE FROM documents WHERE source_path = %s",
                (BENCHMARK_SOURCE,),
            )
            conn.commit()


if __name__ == "__main__":
    topics = seed_benchmark_data()
    print(f"Seeded benchmark data. Topic mapping:")
    for topic, ids in sorted(topics.items()):
        print(f"  {topic}: {ids}")
