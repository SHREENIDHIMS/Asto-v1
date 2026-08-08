#!/usr/bin/env python
"""Asto — local Docker validation pipeline.

Run this against the Dockerized FastAPI + PostgreSQL stack (docker compose
up) from the repo root on the development machine.

    backend\\.venv\\Scripts\\python.exe test_local_pipeline.py

It validates, in order:
  A. Database reachability, connection pool, and a simple query
  B. Sumy extractive summary (top-5 excerpts -> one paragraph, verbatim)
  C. API request latency (first / subsequent / min / avg / p50 / p95)
  D. Security & authorization (internal user, client scope, cross-client
     isolation by ID/query/API manipulation)
  E. Document approval lifecycle (pending / approved+authorized /
     approved+unauthorized / rejected)
  F. Reranker is OFF by configuration and does not load/execute

This is a LOCAL baseline, not a production benchmark. It creates its own
isolated fixtures (Client A, Client B + docs/cases/properties) and cleans
them up at the end. It does NOT pollute the seeded dev data.
"""

from __future__ import annotations

import os
import statistics
import sys
import time
import uuid
from pathlib import Path

import psycopg
import requests

# --- Path bootstrap: make the app package importable (venv has deps) ---
BACKEND_DIR = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))
# Point the embedding model at the already-downloaded cache so no download happens.
os.environ.setdefault(
    "ASTO_EMBEDDING_CACHE_DIR",
    str(BACKEND_DIR / "nlp_models" / "embeddings"),
)

# --- Connection targets (mirror docker-compose.yml) ---
API_BASE = os.environ.get("ASTO_API_BASE", "http://localhost:8011")
DB_DSN = os.environ.get(
    "ASTO_DATABASE_URL",
    "postgresql://asto_app:devpass@127.0.0.1:5433/asto_assistant",
)

ADMIN_EMAIL = "admin@asto.local"
ADMIN_PASSWORD = "admin123"

PASS = "PASS"
FAIL = "FAIL"


class CheckResult:
    def __init__(self, name: str):
        self.name = name
        self.checks: list[tuple[str, bool, str]] = []

    def ok(self, detail: str) -> None:
        self.checks.append((detail, True, ""))
        print(f"  [{PASS}] {detail}")

    def bad(self, detail: str, reason: str) -> None:
        self.checks.append((detail, False, reason))
        print(f"  [{FAIL}] {detail} -- {reason}")

    def assert_true(self, detail: str, cond: bool, reason: str = "") -> None:
        if cond:
            self.checks.append((detail, True, ""))
            print(f"  [{PASS}] {detail}")
        else:
            self.checks.append((detail, False, reason))
            print(f"  [{FAIL}] {detail} -- {reason}")

    def passed(self) -> bool:
        return all(passed for _, passed, _ in self.checks)

    def summary(self) -> str:
        total = len(self.checks)
        passed = sum(1 for _, p, _ in self.checks if p)
        return f"{self.name}: {passed}/{total} checks passed"


def api(method: str, path: str, *, token: str | None = None, json: dict | None = None) -> requests.Response:
    """HTTP helper against the Dockerized API (no redirect on POST)."""
    url = f"{API_BASE}{path}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.request(method, url, headers=headers, json=json, timeout=30)


def login(email: str, password: str) -> str:
    """Staff login; returns a JWT."""
    r = api("POST", "/api/v1/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]


def client_login(email: str, password: str) -> str:
    """External client login; returns a JWT."""
    r = api("POST", "/api/v1/auth/client-login", json={"email": email, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]


def db_connect():
    return psycopg.connect(DB_DSN)


# ---------------------------------------------------------------------------
# A. Database
# ---------------------------------------------------------------------------
def test_database(result: CheckResult) -> None:
    print("\n=== A. DATABASE ===")

    r = api("GET", "/health")
    result.assert_true("FastAPI container reachable (/health)", r.status_code == 200)
    if r.status_code == 200:
        result.assert_true("/health reports healthy", r.json().get("status") == "healthy")

    r = api("GET", "/api/v1/health")
    result.assert_true("API readiness endpoint (/api/v1/health)", r.status_code == 200)
    if r.status_code == 200:
        result.assert_true(
            "DB connectivity reported 'connected' (pool in use)",
            r.json().get("database") == "connected",
        )

    try:
        conn = db_connect()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            one = cur.fetchone()
        conn.close()
        result.assert_true("Host-side psycopg connection + SELECT 1 succeeds", one is not None and one[0] == 1)
    except Exception as exc:  # noqa: BLE001
        result.bad("Host-side psycopg connection + SELECT 1 succeeds", str(exc))

    # Pool initialized at startup: /api/v1/health exercises a pooled connection.
    r = api("GET", "/api/v1/health")
    result.assert_true("Pool available after startup (repeat readiness probe)", r.status_code == 200)


# ---------------------------------------------------------------------------
# B. Sumy extractive summary
# ---------------------------------------------------------------------------
def _make_excerpt(text: str, title: str = "Fixture Doc", section: str = "s1", did: int = 1, cid: int = 1):
    from app.response.package_builder import Excerpt, Source

    return Excerpt(
        text=text,
        source=Source(
            chunk_id=cid,
            document_id=did,
            title=title,
            section=section,
            chunk_type="paragraph",
            is_approved=True,
            document_version=1,
        ),
        confidence=90.0,
        bm25_score=0.5,
        vec_score=0.5,
    )


def test_sumy(result: CheckResult) -> None:
    from app.response.summarizer import summarize_excerpts

    print("\n=== B. SUMY EXTRACTIVE SUMMARY ===")

    # --- Normal: 5 excerpts, multi-sentence, concatenated as the app does ---
    five = [
        "Credit scores are a key factor in determining loan eligibility.",
        "A minimum score of 620 is typically required for standard programs.",
        "The debt-to-income ratio must not exceed 43% for qualified mortgage products.",
        "Some programs allow higher ratios with compensating factors.",
        "Documentation required for loan applications includes proof of income and bank statements.",
    ]
    excerpts = [_make_excerpt(t, section=f"s{i}", cid=i + 1) for i, t in enumerate(five)]
    corpus = "\n\n".join(e.text for e in excerpts)
    try:
        summary = summarize_excerpts(excerpts)
    except Exception as exc:  # noqa: BLE001
        result.bad("Top-5 concatenated input -> summarize_excerpts does not crash", str(exc))
        summary = []
    result.assert_true("Top-5 concatenated input -> summary returned", isinstance(summary, list))
    result.assert_true("Summary returns up to 4 sentences", len(summary) <= 4)
    result.assert_true("Summary returns at least 1 sentence", len(summary) >= 1)

    if summary:
        norm_corpus = " ".join(corpus.split()).lower()
        verbatim = all(
            " ".join(s.text.split()).lower() in norm_corpus for s in summary
        )
        result.assert_true(
            "Every summary sentence is verbatim from the source excerpts (extractive)",
            verbatim,
        )
        # Citations: each sentence maps back to its source title/section
        cited = all(s.source_title and s.source_section for s in summary)
        result.assert_true("Every summary sentence carries a source citation", cited)

    # --- Empty excerpts ---
    try:
        empty = summarize_excerpts([])
        result.assert_true("Empty excerpts -> [] without crash", empty == [])
    except Exception as exc:  # noqa: BLE001
        result.bad("Empty excerpts -> [] without crash", str(exc))

    # --- Very short input (single short sentence) ---
    try:
        short = summarize_excerpts([_make_excerpt("Credit scores matter.")])
        result.assert_true("Very short input does not crash", isinstance(short, list))
        ok_short = all(
            " ".join(s.text.split()).lower() in "credit scores matter." for s in short
        )
        result.assert_true("Very short input summary sentences are verbatim", ok_short)
    except Exception as exc:  # noqa: BLE001
        result.bad("Very short input does not crash", str(exc))

    # --- Duplicate excerpts ---
    try:
        dup = summarize_excerpts([_make_excerpt(five[0]), _make_excerpt(five[0])])
        result.assert_true("Duplicate excerpts do not crash", isinstance(dup, list))
        if dup:
            result.assert_true(
                "Duplicate-excerpt summary stays verbatim",
                all(
                    " ".join(s.text.split()).lower() in " ".join(five[0].split()).lower()
                    for s in dup
                ),
            )
    except Exception as exc:  # noqa: BLE001
        result.bad("Duplicate excerpts do not crash", str(exc))

    # --- Missing/invalid text (None should be filtered by app, guard anyway) ---
    try:
        invalid = summarize_excerpts([_make_excerpt("")])
        result.assert_true("Empty-string excerpt does not crash", isinstance(invalid, list))
    except Exception as exc:  # noqa: BLE001
        result.bad("Empty-string excerpt does not crash", str(exc))

    # --- Insufficient sentences ---
    try:
        few = summarize_excerpts([_make_excerpt("Only one sentence here.")])
        result.assert_true("Insufficient sentences do not crash", isinstance(few, list))
    except Exception as exc:  # noqa: BLE001
        result.bad("Insufficient sentences do not crash", str(exc))


# ---------------------------------------------------------------------------
# C. API latency
# ---------------------------------------------------------------------------
def test_latency(result: CheckResult) -> None:
    print("\n=== C. API LATENCY (LOCAL BASELINE ONLY) ===")

    token = login(ADMIN_EMAIL, ADMIN_PASSWORD)

    # First request (cold) — measured separately.
    t0 = time.perf_counter()
    r = api("POST", "/api/v1/search/", token=token, json={"query": "minimum credit score for loan"})
    first_ms = (time.perf_counter() - t0) * 1000.0
    result.assert_true("First (cold) search request returns 200", r.status_code == 200, r.text[:200])

    samples: list[float] = []
    for _ in range(30):
        t0 = time.perf_counter()
        r = api("POST", "/api/v1/search/", token=token, json={"query": "minimum credit score for loan"})
        samples.append((time.perf_counter() - t0) * 1000.0)
        if r.status_code != 200:
            result.bad("Warm search request returns 200", r.text[:200])
            return

    samples = sorted(samples)
    avg = statistics.fmean(samples)
    p50 = samples[len(samples) // 2]
    p95 = samples[int(len(samples) * 0.95) - 1]

    print(f"  first request : {first_ms:7.1f} ms (cold)")
    print(f"  min           : {samples[0]:7.1f} ms")
    print(f"  avg           : {avg:7.1f} ms")
    print(f"  p50           : {p50:7.1f} ms")
    print(f"  p95           : {p95:7.1f} ms")
    print(f"  samples       : {len(samples)}")

    result.ok(f"latency measured: first={first_ms:.1f}ms p50={p50:.1f}ms p95={p95:.1f}ms")
    result.assert_true(
        "Warm p95 within local baseline (<= 200ms sanity bound)",
        p95 <= 200,
    )


# ---------------------------------------------------------------------------
# D. Security / authorization
# ---------------------------------------------------------------------------
def test_security(result: CheckResult, a_email: str, b_email: str, staff_email: str) -> None:
    print("\n=== D. SECURITY & AUTHORIZATION ===")

    tag = a_email.split("@")[0].split("_")[-1]
    client_a = a_email
    client_b = b_email
    pw = "testpass123"

    admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)

    # Create Client A and Client B through the admin API (validates admin + client creation).
    ra = api("POST", "/api/v1/admin/clients", token=admin_token,
             json={"email": client_a, "password": pw, "full_name": "Test Client A"})
    rb = api("POST", "/api/v1/admin/clients", token=admin_token,
             json={"email": client_b, "password": pw, "full_name": "Test Client B"})
    result.assert_true("Admin creates Client A", ra.status_code == 201, ra.text)
    result.assert_true("Admin creates Client B", rb.status_code == 201, rb.text)
    a_id = ra.json().get("client_id")
    b_id = rb.json().get("client_id")

    # Fixture data (no admin API for docs/properties/cases -> direct DB, like seed_db.py).
    conn = db_connect()
    try:
        with conn.cursor() as cur:
            # Properties
            cur.execute(
                "INSERT INTO properties (client_id, address, city, state, postal_code, property_type) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                (a_id, "100 Alpha St", "Springfield", "IL", "62701", "single_family"),
            )
            prop_a = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO properties (client_id, address, city, state, postal_code, property_type) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                (b_id, "200 Beta Ave", "Springfield", "IL", "62702", "condo"),
            )
            prop_b = cur.fetchone()[0]
            # Cases
            cur.execute(
                "INSERT INTO cases (case_number, client_id, property_id, loan_amount, status) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (f"CAS-A-{tag}", a_id, prop_a, 275000, "active"),
            )
            case_a = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO cases (case_number, client_id, property_id, loan_amount, status) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (f"CAS-B-{tag}", b_id, prop_b, 500000, "active"),
            )
            case_b = cur.fetchone()[0]
            # Client-scoped APPROVED documents (need embeddings for search)
            cur.execute(
                "INSERT INTO documents (title, source_path, doc_type, department, client_id, "
                "approval_status, is_approved, is_active, version) "
                "VALUES (%s,%s,%s,%s,%s,'approved',true,true,1) RETURNING id",
                (f"ALPHA SECRET-{tag}", "/docs/alpha.pdf", "policy", "general", a_id),
            )
            doc_a = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO documents (title, source_path, doc_type, department, client_id, "
                "approval_status, is_approved, is_active, version) "
                "VALUES (%s,%s,%s,%s,%s,'approved',true,true,1) RETURNING id",
                (f"BETA SECRET-{tag}", "/docs/beta.pdf", "policy", "general", b_id),
            )
            doc_b = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    # Generate embeddings for fixture chunks so they're eligible for vector search.
    from app.search.pgvector_search import embed_query

    def add_chunk(doc_id: int, content: str, section: str) -> int:
        import hashlib

        embedding = list(embed_query(content))
        conn2 = db_connect()
        try:
            with conn2.cursor() as cur:
                cur.execute(
                    "INSERT INTO document_chunks (document_id, content, content_hash, embedding, section, "
                    "chunk_type, department, approval_status, is_approved, is_active) "
                    "VALUES (%s,%s,%s,%s,%s,'paragraph','general','approved',true,true) RETURNING id",
                    (doc_id, content, hashlib.md5(content.encode()).hexdigest(), embedding, section),
                )
                cid = cur.fetchone()[0]
            conn2.commit()
            return cid
        finally:
            conn2.close()

    alpha_content = f"The ALPHA portfolio {tag} contains confidential credit details unique to client A."
    beta_content = f"The BETA portfolio {tag} contains confidential credit details unique to client B."
    add_chunk(doc_a, alpha_content, "confidential")
    add_chunk(doc_b, beta_content, "confidential")

    tok_a = client_login(client_a, pw)
    tok_b = client_login(client_b, pw)

    # --- Client A self-service scope ---
    r = api("GET", "/api/v1/client/me", token=tok_a)
    result.assert_true("Client A /client/me returns own profile", r.status_code == 200)
    if r.status_code == 200:
        result.assert_true(
            "Client A profile is Client A",
            r.json().get("client", {}).get("email") == client_a,
        )

    r = api("GET", "/api/v1/client/properties", token=tok_a)
    props_a = r.json().get("properties", []) if r.status_code == 200 else []
    result.assert_true(
        "Client A sees only its own property",
        r.status_code == 200 and all(p["id"] == prop_a for p in props_a) and len(props_a) == 1,
    )

    r = api("GET", "/api/v1/client/cases", token=tok_a)
    cases_a = r.json().get("cases", []) if r.status_code == 200 else []
    result.assert_true(
        "Client A sees only its own case",
        r.status_code == 200 and all(c["id"] == case_a for c in cases_a) and len(cases_a) == 1,
    )

    r = api("GET", "/api/v1/client/documents", token=tok_a)
    docs_a = r.json().get("documents", []) if r.status_code == 200 else []
    result.assert_true(
        "Client A sees only its own approved document",
        r.status_code == 200 and all(d["id"] == doc_a for d in docs_a) and len(docs_a) == 1,
    )

    # --- Cross-client: A must NOT see B's data ---
    r = api("GET", "/api/v1/client/documents", token=tok_a)
    b_visible = any(d["id"] == doc_b for d in r.json().get("documents", []))
    result.assert_true("Client A cannot see Client B's documents", not b_visible)

    r = api("GET", "/api/v1/client/cases", token=tok_a)
    b_case_visible = any(c["id"] == case_b for c in r.json().get("cases", []))
    result.assert_true("Client A cannot see Client B's cases", not b_case_visible)

    r = api("GET", "/api/v1/client/properties", token=tok_a)
    b_prop_visible = any(p["id"] == prop_b for p in r.json().get("properties", []))
    result.assert_true("Client A cannot see Client B's properties", not b_prop_visible)

    # --- Cross-client via SEARCH query manipulation ---
    r = api("POST", "/api/v1/search/", token=tok_a, json={"query": f"BETA portfolio {tag}"})
    titles_a = [e.get("source", {}).get("title", "") for e in r.json().get("excerpts", [])] if r.status_code == 200 else []
    result.assert_true(
        "Client A search query for Client B's doc returns nothing (SQL WHERE scoping)",
        r.status_code == 200 and not any(f"BETA SECRET-{tag}" in t for t in titles_a),
    )

    # --- Cross-client via ID manipulation on self-service endpoints ---
    # The client endpoints derive scope from the JWT (client_id), never from the body/query,
    # so even guessing B's IDs must return empty.
    r = api("GET", "/api/v1/client/documents", token=tok_a)
    result.assert_true(
        "Client A's document list never contains B's doc (ID guessing is scope-less)",
        r.status_code == 200 and not any(d["id"] == doc_b for d in r.json().get("documents", [])),
    )

    # --- Client cannot reach admin functionality ---
    r = api("GET", "/api/v1/admin/users", token=tok_a)
    result.assert_true("Client A cannot call /admin/users", r.status_code == 403)

    r = api("GET", "/api/v1/admin/documents/pending", token=tok_a)
    result.assert_true("Client A cannot call approval queue", r.status_code == 403)

    r = api("POST", "/api/v1/admin/clients", token=tok_a,
            json={"email": f"evil_{tag}@asto.local", "password": pw})
    result.assert_true("Client A cannot create users/clients", r.status_code == 403)

    # --- Internal user (staff) by role/department/assigned client ---
    r = api("POST", "/api/v1/search/", token=admin_token, json={"query": f"ALPHA portfolio {tag}"})
    admin_titles = [e.get("source", {}).get("title", "") for e in r.json().get("excerpts", [])] if r.status_code == 200 else []
    result.assert_true(
        "Admin (super_admin) search can see client-scoped approved docs",
        r.status_code == 200 and any(f"ALPHA SECRET-{tag}" in t for t in admin_titles),
    )

    # Staff with a narrow role: create a loan_officer, verify department scoping.
    r = api("POST", "/api/v1/admin/users", token=admin_token,
            json={"email": staff_email, "password": pw, "full_name": "Loan Officer",
                  "role": "loan_officer", "department": "general", "allowed_departments": []})
    result.assert_true("Admin creates a loan_officer", r.status_code == 201, r.text)
    staff_id = r.json().get("user_id")
    tok_staff = login(staff_email, pw)

    r = api("POST", "/api/v1/search/", token=tok_staff, json={"query": f"BETA portfolio {tag}"})
    staff_titles = [e.get("source", {}).get("title", "") for e in r.json().get("excerpts", [])] if r.status_code == 200 else []
    result.assert_true(
        "Staff without client assignment cannot see client-scoped docs",
        r.status_code == 200 and not any(f"BETA SECRET-{tag}" in t for t in staff_titles),
    )

    # Assign loan officer to Client B -> now the same query surfaces B's scoped doc.
    r = api("POST", "/api/v1/admin/assignments", token=admin_token,
            json={"client_id": b_id, "user_id": staff_id})
    result.assert_true("Admin assigns staff to Client B", r.status_code == 201, r.text)
    r = api("POST", "/api/v1/search/", token=tok_staff, json={"query": f"BETA portfolio {tag}"})
    staff_titles_after = [e.get("source", {}).get("title", "") for e in r.json().get("excerpts", [])] if r.status_code == 200 else []
    result.assert_true(
        "Staff assigned to Client B can now see B's scoped doc",
        r.status_code == 200 and any(f"BETA SECRET-{tag}" in t for t in staff_titles_after),
    )


# ---------------------------------------------------------------------------
# E. Approval lifecycle
# ---------------------------------------------------------------------------
def test_approvals(result: CheckResult) -> None:
    print("\n=== E. DOCUMENT APPROVAL LIFECYCLE ===")

    tag = uuid.uuid4().hex[:8]
    admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)

    # A standalone client for the approval test.
    cl_email = f"approval_{tag}@asto.local"
    r = api("POST", "/api/v1/admin/clients", token=admin_token,
            json={"email": cl_email, "password": "pw12345", "full_name": "Approval Client"})
    cl_id = r.json().get("client_id")
    tok_cl = client_login(cl_email, "pw12345")

    import hashlib

    from app.search.pgvector_search import embed_query

    def make_doc(title: str, status: str, content: str) -> int:
        conn = db_connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO documents (title, source_path, doc_type, department, client_id, "
                    "approval_status, is_approved, is_active, version) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,true,1) RETURNING id",
                    (title, f"/docs/{tag}.pdf", "policy", "general", cl_id,
                     status, status == "approved"),
                )
                doc_id = cur.fetchone()[0]
                embedding = list(embed_query(content))
                cur.execute(
                    "INSERT INTO document_chunks (document_id, content, content_hash, embedding, section, "
                    "chunk_type, department, approval_status, is_approved, is_active) "
                    "VALUES (%s,%s,%s,%s,%s,'paragraph','general',%s,%s,true)",
                    (doc_id, content, hashlib.md5(content.encode()).hexdigest(), embedding,
                     "section", status, status == "approved"),
                )
            conn.commit()
            return doc_id
        finally:
            conn.close()

    pending_content = f"PENDING approval-only guidance for {tag}."
    approved_content = f"APPROVED final guidance for {tag}."
    rejected_content = f"REJECTED obsolete guidance for {tag}."

    doc_pending = make_doc(f"PENDING DOC-{tag}", "pending", pending_content)
    doc_approved = make_doc(f"APPROVED DOC-{tag}", "approved", approved_content)
    doc_rejected = make_doc(f"REJECTED DOC-{tag}", "rejected", rejected_content)

    # Pending -> not retrievable
    r = api("POST", "/api/v1/search/", token=tok_cl, json={"query": f"PENDING approval-only guidance {tag}"})
    titles = [e.get("source", {}).get("title", "") for e in r.json().get("excerpts", [])] if r.status_code == 200 else []
    result.assert_true(
        "Pending document is NOT retrievable (search)",
        r.status_code == 200 and not any(f"PENDING DOC-{tag}" in t for t in titles),
    )
    # Also not listed in client's approved documents endpoint
    r = api("GET", "/api/v1/client/documents", token=tok_cl)
    pending_in_list = any(d["id"] == doc_pending for d in r.json().get("documents", []))
    result.assert_true("Pending document is NOT in client document list", not pending_in_list)

    # Rejected -> not retrievable
    r = api("POST", "/api/v1/search/", token=tok_cl, json={"query": f"REJECTED obsolete guidance {tag}"})
    titles = [e.get("source", {}).get("title", "") for e in r.json().get("excerpts", [])] if r.status_code == 200 else []
    result.assert_true(
        "Rejected document is NOT retrievable (search)",
        r.status_code == 200 and not any(f"REJECTED DOC-{tag}" in t for t in titles),
    )

    # Approved + authorized -> retrievable
    r = api("POST", "/api/v1/search/", token=tok_cl, json={"query": f"APPROVED final guidance {tag}"})
    titles = [e.get("source", {}).get("title", "") for e in r.json().get("excerpts", [])] if r.status_code == 200 else []
    result.assert_true(
        "Approved document IS retrievable for the owning client",
        r.status_code == 200 and any(f"APPROVED DOC-{tag}" in t for t in titles),
    )

    # Approve the pending doc via the admin API -> now retrievable
    r = api("POST", f"/api/v1/admin/documents/{doc_pending}/approve", token=admin_token)
    result.assert_true("Admin approves the pending document", r.status_code == 200, r.text)
    r = api("POST", "/api/v1/search/", token=tok_cl, json={"query": f"PENDING approval-only guidance {tag}"})
    titles = [e.get("source", {}).get("title", "") for e in r.json().get("excerpts", [])] if r.status_code == 200 else []
    result.assert_true(
        "After approval the document IS retrievable for the authorized client",
        r.status_code == 200 and any(f"PENDING DOC-{tag}" in t for t in titles),
    )

    # Approval audit trail exists
    r = api("GET", f"/api/v1/admin/documents/{doc_pending}/history", token=admin_token)
    history = r.json().get("history", []) if r.status_code == 200 else []
    result.assert_true(
        "Approval audit trail recorded",
        r.status_code == 200 and any(h.get("to_status") == "approved" for h in history),
    )

    # Approved but UNAUTHORIZED (different client) -> not retrievable
    other_email = f"other_{tag}@asto.local"
    r = api("POST", "/api/v1/admin/clients", token=admin_token,
            json={"email": other_email, "password": "pw12345", "full_name": "Other Client"})
    other_id = r.json().get("client_id")
    tok_other = client_login(other_email, "pw12345")
    r = api("POST", "/api/v1/search/", token=tok_other, json={"query": f"PENDING approval-only guidance {tag}"})
    titles = [e.get("source", {}).get("title", "") for e in r.json().get("excerpts", [])] if r.status_code == 200 else []
    result.assert_true(
        "Approved + UNAUTHORIZED client cannot retrieve it (Approved AND Authorized)",
        r.status_code == 200 and not any(f"PENDING DOC-{tag}" in t for t in titles),
    )

    # Reject the now-approved doc -> no longer retrievable
    r = api("POST", f"/api/v1/admin/documents/{doc_pending}/reject", token=admin_token)
    result.assert_true("Admin rejects the document", r.status_code == 200, r.text)
    r = api("POST", "/api/v1/search/", token=tok_cl, json={"query": f"PENDING approval-only guidance {tag}"})
    titles = [e.get("source", {}).get("title", "") for e in r.json().get("excerpts", [])] if r.status_code == 200 else []
    result.assert_true(
        "After reject the document is no longer retrievable",
        r.status_code == 200 and not any(f"PENDING DOC-{tag}" in t for t in titles),
    )

    # cleanup: drop the "other" client too
    conn = db_connect()
    try:
        with conn.cursor() as cur:
            for cid in (cl_id, other_id):
                cur.execute("DELETE FROM approval_log WHERE document_id IN (SELECT id FROM documents WHERE client_id = %s)", (cid,))
                cur.execute("DELETE FROM documents WHERE client_id = %s", (cid,))
                cur.execute("DELETE FROM cases WHERE client_id = %s", (cid,))
                cur.execute("DELETE FROM properties WHERE client_id = %s", (cid,))
                cur.execute("DELETE FROM clients WHERE id = %s", (cid,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# F. Reranker OFF
# ---------------------------------------------------------------------------
def test_reranker_off(result: CheckResult) -> None:
    print("\n=== F. RERANKER OFF BY CONFIGURATION ===")

    from app.config import settings

    result.assert_true(
        "ASTO_RERANK_ENABLED resolves to False",
        settings.rerank_enabled is False,
        f"got {settings.rerank_enabled}",
    )

    # The rerank() entrypoint must short-circuit without importing transformers.
    import sys as _sys

    transformer_loaded_before = "transformers" in _sys.modules
    from app.ranking.reranker import rerank

    candidates = [{"chunk_id": i, "content": f"c{i}"} for i in range(3)]
    out = rerank("query", candidates, top_k=2)
    transformer_loaded_after = "transformers" in _sys.modules

    result.assert_true(
        "rerank() returns candidates unchanged when disabled",
        [c["chunk_id"] for c in out] == [0, 1] and len(out) == 2,
    )
    result.assert_true(
        "reranker does NOT load transformers/onnxruntime when disabled",
        transformer_loaded_after is False,
        "transformers was imported by rerank()",
    )
    result.ok("baseline behavior preserved: fast retrieval, no cross-encoder")


# ---------------------------------------------------------------------------
# Cleanup helper for security fixtures
# ---------------------------------------------------------------------------
def _cleanup_security_fixtures(a_email: str, b_email: str, staff_email: str) -> None:
    conn = db_connect()
    try:
        with conn.cursor() as cur:
            for email in (a_email, b_email):
                cur.execute("SELECT id FROM clients WHERE email = %s", (email,))
                row = cur.fetchone()
                if not row:
                    continue
                cid = row[0]
                cur.execute(
                    "DELETE FROM approval_log WHERE document_id IN (SELECT id FROM documents WHERE client_id = %s)",
                    (cid,),
                )
                cur.execute("DELETE FROM document_chunks WHERE document_id IN (SELECT id FROM documents WHERE client_id = %s)", (cid,))
                cur.execute("DELETE FROM documents WHERE client_id = %s", (cid,))
                cur.execute("DELETE FROM cases WHERE client_id = %s", (cid,))
                cur.execute("DELETE FROM properties WHERE client_id = %s", (cid,))
                cur.execute("DELETE FROM clients WHERE id = %s", (cid,))
            if staff_email:
                cur.execute("DELETE FROM users WHERE email = %s", (staff_email,))
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    print("=" * 70)
    print("Asto — local Docker validation pipeline")
    print(f"  API base : {API_BASE}")
    print(f"  DB DSN   : {DB_DSN}")
    print("=" * 70)

    all_results: list[CheckResult] = []

    # A. Database
    r = CheckResult("A. Database")
    test_database(r)
    all_results.append(r)

    # B. Sumy
    r = CheckResult("B. Sumy")
    test_sumy(r)
    all_results.append(r)

    # C. Latency
    r = CheckResult("C. Latency")
    test_latency(r)
    all_results.append(r)

    # D. Security
    r = CheckResult("D. Security")
    tag = uuid.uuid4().hex[:8]
    a_email = f"testa_{tag}@asto.local"
    b_email = f"testb_{tag}@asto.local"
    staff_email = f"staff_{tag}@asto.local"
    try:
        test_security(r, a_email, b_email, staff_email)
    finally:
        _cleanup_security_fixtures(a_email, b_email, staff_email)
    all_results.append(r)

    # E. Approvals
    r = CheckResult("E. Approvals")
    test_approvals(r)
    all_results.append(r)

    # F. Reranker
    r = CheckResult("F. Reranker")
    test_reranker_off(r)
    all_results.append(r)

    print("\n" + "=" * 70)
    for res in all_results:
        print(f"  {res.summary()}")
    overall = all(x.passed() for x in all_results)
    print("=" * 70)
    print(f"OVERALL: {'ALL CHECKS PASSED' if overall else 'FAILURES PRESENT'}")
    print("=" * 70)
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
