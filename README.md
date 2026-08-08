# Asto — Knowledge-Based AI Assistant

A lightweight, retrieval-only AI assistant for compliance and document queries. **No LLM generation anywhere** — every response is a verbatim excerpt from retrieved documents. Designed for shared AWS EC2 micro-tier deployment (1 GiB RAM) where latency, compliance, and cost matter.

**Dual-audience:** internal staff (role/department/client-scoped search) **and** authenticated external clients (self-service access to their own documents, properties, and cases). New documents enter a **pending approval workflow** and are not searchable until an admin approves them.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Tech Stack](#tech-stack)
- [How It Works](#how-it-works)
- [Project Structure](#project-structure)
- [Quick Start (Development)](#quick-start-development)
- [Production Deployment](#production-deployment)
- [Testing](#testing)
- [Evaluation & Benchmarks](#evaluation--benchmarks)

---

## Architecture Overview

```
Browser → Nginx (30MB) → FastAPI (socket-activated, 200MB cap, idle-stops)
                                    │
                    ┌───────────────┼────────────────┐
                    ▼               ▼                ▼
           Query Processing   Hybrid Postgres      Audit Logger
           (pure, deterministic) Query             (every query)
           normalize→spell-correct BM25 + pgvector  user, query, docs, ts,
           →split→entity→intent→  RBAC + approval   confidence, response_id
           →expand               filter in WHERE
                    │               clause
                    ▼
              JWT Auth (both audiences)
              staff → users table (role, department, client assignments)
              client → clients table (own client_id only)
```

```
Document Ingestion (batch only — never in API path)
  Upload → Validate → Pending approval → Extract text → Chunk → Embed → Index to pgvector

Admin Approval Workflow (writes approval_log audit trail)
  pending → approved (searchable)  |  pending → rejected (never searchable)
```

### Key Architectural Constraints

| Constraint | Detail |
|---|---|
| **No LLM generation** | Every response is verbatim excerpts from retrieved documents |
| **Single Postgres** | One instance per host, one database per project (`asto_assistant`) |
| **pgvector, not Qdrant** | Vector search runs in the same SQL query as BM25 + RBAC |
| **RBAC in WHERE clause** | Department + client scope enforced by Postgres filtering, not post-hoc checks |
| **Pending-by-default ingestion** | New docs enter `pending`; only `is_approved = true` docs are searchable |
| **Socket-activated backend** | FastAPI runs with `--workers 1`, idle-stops after 10 minutes |
| **Batch ingestion only** | OCR, embedding, and NLP run in `ingest_batch.py`, never in API process |
| **Memory caps** | Postgres ~200MB, Nginx ~30MB, Backend ~200MB |
| **Audit logging** | Every query logged with user, retrieved docs, confidence, timestamp |
| **Approval audit trail** | Every approve/reject transition logged to `approval_log` with reviewer |

---

## Tech Stack

### Backend (FastAPI)
| Component | Technology | Purpose |
|---|---|---|
| Web framework | **FastAPI 0.141.1** | REST API with automatic OpenAPI docs |
| Server | **Uvicorn 0.52.1** | ASGI server, `--workers 1` (socket-activated) |
| Database | **PostgreSQL 16 + pgvector** | BM25 search + vector similarity in single query |
| Driver | **psycopg 3.3.4** | Connection pooling, cursor access |
| Embeddings | **FastEmbed 0.8.0** | `bge-small-en-v1.5` (384-dim, ~66MB) |
| Inference runtime | **ONNX Runtime 1.28.0** | Runs FastEmbed model |
| Auth | **PyJWT 2.13.0** | HS256-signed tokens with RBAC claims |
| Config | **Pydantic 2.13.4** | Type-safe settings with env-var binding |
| Text processing | **RapidFuzz 3.14.5** | Fuzzy matching for spell correction |
| Batch ingestion | **pdfplumber 0.11.6**, **python-docx 1.2.0** | Text extraction from PDF/DOCX |

### Frontend (Next.js)
| Component | Technology | Purpose |
|---|---|---|
| Framework | **Next.js 14** | Static export (no SSR) |
| Styling | **Tailwind CSS** | Utility-first styling |
| Language | **TypeScript** | Type safety |
| Auth | Custom JWT client | Browser-side token management |
| Pages | `/` (chat), `/login` (staff/client), `/portal` (client), `/admin` | Dual-audience UI |
| Chat history | localStorage (24h TTL) | `hooks/use-chat-history.ts`, no server persistence |

### Infrastructure
| Layer | Technology | Purpose |
|---|---|---|
| Reverse proxy | **Nginx (alpine)** | TLS termination, static file serving |
| Container | **Docker Compose** | Postgres + Nginx shared service |
| Process manager | **systemd socket-activation** | Backend starts on-demand, idle-stops |
| CI/CD | **GitHub Actions** | Unit tests + evaluation benchmarks |

---

## How It Works

The request-serving path has **zero LLM calls**. Here's the complete flow from query to response:

### 1. Request Reception (`main.py`)
- Nginx receives the HTTP request
- Socket-activated FastAPI starts on-demand (avoids idle resource usage)
- JWT extracted from Authorization header, verified via `auth/jwt_handler.py`
- Two audiences resolved by `dependencies.get_current_user`:
  - **staff** (`audience="staff"`) → `users` table (role, department, allowed_departments, assigned clients)
  - **client** (`audience="client"`, JWT carries `client_id`) → `clients` table; their search scope is
    their own client_id only
- RBAC claims (role, department, allowed_departments, audience, client_id) extracted from token

### 1b. Document Approval Workflow (`api/v1/approvals.py`)
Admin-only review queue. Ingestion inserts new documents as `pending`
(`is_approved = false`) and they are **invisible to search** until approved:

- `GET  /admin/documents/pending` — review queue
- `POST /admin/documents/{id}/approve` — marks doc + all chunks approved (searchable)
- `POST /admin/documents/{id}/reject` — marks doc + all chunks rejected (never searchable)
- `GET  /admin/documents/{id}/history` — reviewer audit trail (`approval_log`)

State changes are transactional: the document **and** every chunk move together,
so a partially-approved document can never leak into search. The approval filter
(`is_approved = true`) is part of the search `WHERE` clause alongside RBAC.

### 2. Query Processing (`query_processing/pipeline.py`)
Pure, deterministic transformation — no network calls or model loading:

```
Raw query: "What are the credit score requirements for VA loans?"
    ↓ normalize (lowercase, unicode normalize)
    ↓ spell_correct (RapidFuzz-based phrase repair)
    ↓ split_into_sub_queries (multi-question detection via delimiter recognition)
    ↓ entity_extraction (domain-specific entity matching)
    ↓ intent_detection (general, eligibility, documents, rates, ...)
    → QueryPlan(sub_queries=[SQ(...), SQ(...)])
```

### 3. Hybrid Search (`search/hybrid_orchestrator.py`)
A **single SQL query** combines everything:

```sql
SELECT chunks.*, 
       ts_rank_cd(chunks.fts, plainto_tsquery($1)) AS bm25_score,
       1 - (chunks.embedding <=> $2) AS vec_score
FROM document_chunks chunks
WHERE chunks.is_active = true
  AND chunks.is_approved = true          -- version filter
  AND chunks.department = ANY($3)       -- RBAC filter (in WHERE, not post-hoc)
ORDER BY ts_rank_cd(...) * 0.3 + (1 - (embedding <=> query_vec)) * 0.7 DESC
LIMIT 25;
```

BM25 scores text relevance using PostgreSQL's full-text search (`tsvector`), vector search uses pgvector's `vector_cosine_ops` HNSW index. Both use the same WHERE clause for RBAC — **no post-hoc filtering**.

### 4. Ranking (`ranking/rrf.py`)
Reciprocal Rank Fusion combines BM25-ranked and vector-ranked lists:

```python
def rank_fusion(bm25_ranked, vector_ranked, chunk_lookup, k=60):
    """RRF: each chunk gets score = Σ(1 / (k + rank)) across lists."""
    # No learned weights — pure position-based fusion
    # Configurable k parameter in ranking/weights_config.py
```

### 5. Response Packaging (`response/package_builder.py`)
Assembles the response package — **verbatim excerpts only**, plus an
extractive summary (`response/summarizer.py`, Sumy TextRank) selecting up
to 4 sentences verbatim from the top excerpts, each mapped back to its
source:

```
ResponsePackage {
    response_id: UUID (audit correlation),
    title: "Derived from top excerpt's document title",
    excerpts: [
        { text: "The minimum credit score for...",  ← verbatim chunk
          source: {title, section, chunk_type},
          confidence: 87.5,
          related_sub_queries: [...] }
    ],
    confidence: 87.5,  ← weighted average of top excerpt confidences
    routing: "answer"  ← determined by confidence_thresholds.py
    related_questions: [...]  ← from multi_question.py
}
```

**Confidence routing** (`response/confidence_thresholds.py`):
- **90+** → `"answer"` (high confidence)
- **75-89** → `"partial"` (some relevant results)
- **50-74** → `"partial"` (low confidence, needs human review)
- **<50** → `"no_answer"` (redirect to human)

### 6. Validation (`response/validation.py`)
Safety-net validation (not the only RBAC enforcement — that's in the SQL WHERE clause):
- Re-checks document department access
- Re-checks document approval status and version flags
- Does **not** check confidence thresholds — that is handled by `confidence_thresholds.py`
  (`route_by_confidence`), which sets `package.routing`. Low-confidence results return a
  graceful `"no_answer"` response, not a server error.

### 7. Audit Logging (`audit/audit_logger.py`)
Every query is logged to `audit_log` table:
```
user_id, query, sub_queries (JSON), retrieved_ids (array),
confidence, response_id, outcome, latency_ms, created_at
```

---

## Project Structure

```
ASTO/
├── backend/                    # FastAPI application
│   ├── app/
│   │   ├── api/v1/           # auth, client, search, documents, upload, feedback, analytics, admin, approvals
│   │   ├── audit/            # Structured audit logging
│   │   ├── auth/             # JWT, RBAC, permissions
│   │   ├── db/postgres/      # Schema, session pooling, models
│   │   ├── documents/        # Ingestion pipeline (batch-only)
│   │   │   └── chunking/      # Structural chunker
│   │   ├── knowledge_gap/    # Low-confidence query detection
│   │   ├── query_processing/  # Query normalization, spell correction, expansion
│   │   ├── ranking/           # RRF fusion, configurable weights
│   │   ├── response/          # Package builder, confidence thresholds, validation
│   │   ├── search/            # Hybrid BM25 + pgvector orchestrator
│   │   ├── config.py          # Pydantic-settings configuration
│   │   ├── dependencies.py    # FastAPI dependency injection (dual-audience JWT resolution)
│   │   └── main.py           # FastAPI app with lifespan
│   ├── scripts/             # seed_db.py (dev/seed data)
│   ├── tests/
│   │   ├── unit/             # 140 unit tests
│   │   ├── integration/      # 11 integration tests (RBAC, approvals, client auth)
│   │   └── conftest.py       # DB mocking for unit tests
│   ├── requirements.txt      # Pinned dependencies
│   ├── Dockerfile            # python:3.11-slim, --workers 1
│   └── debug_imports.py      # Import verification
│
├── frontend/                  # Next.js 14 static frontend
│   ├── app/                  # Pages: / (chat), /login, /portal, /admin
│   ├── components/           # search, chat, feedback components
│   ├── hooks/                # use-chat-history.ts (24h localStorage)
│   ├── lib/                  # API client, JWT auth + decodeToken
│   └── styles/               # Tailwind CSS
│
├── evaluation/               # Benchmark framework
│   ├── datasets/             # eval_20_questions.jsonl
│   ├── metrics/              # hit_rate, precision, recall, MRR, nDCG
│   ├── reports/              # Benchmark output
│   └── run_benchmark.py      # Evaluation runner
│
├── shared-host-infra-scaffold/  # Production deployment
│   ├── infra/
│   │   ├── shared/           # docker-compose (Postgres + Nginx)
│   │   ├── systemd/         # Socket-activated backend service
│   │   └── scripts/         # migrate_db.sh, run_ingestion.sh
│   └── postgres/init/       # Schema initialization
│
├── .github/workflows/       # CI/CD (ci.yml, deploy.yml, eval_on_pr.yml)
├── CLAUDE.md               # Architectural rules
└── README.md               # This file
```

---

## Quick Start (Development)

### Required toolchain
- Python 3.11.x for the backend
- Node.js 20.x for the frontend
- npm 10.x or newer

```bash
# 1. Start PostgreSQL with pgvector
docker run -d --name postgres \
  -e POSTGRES_USER=admin -e POSTGRES_PASSWORD=adminpass \
  -e POSTGRES_DB=asto_assistant \
  -p 5433:5432 \
  pgvector/pgvector:pg16

# 2. Create and activate a Python virtual environment
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1   # Windows PowerShell
# or: source .venv/bin/activate  # macOS/Linux

# 3. Install backend dependencies
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt

# 4. Set environment variables
# Copy the example env file if present and adjust values as needed
# . .env

# 5. Run the API
.venv\Scripts\python.exe -m uvicorn app.main:app --workers 1 --reload

# 6. Seed dev data (creates admin, a client, property, case, assignment,
#    and one pending document awaiting approval)
.venv\Scripts\python.exe -m scripts.seed_db

# 7. Run tests
.venv\Scripts\python.exe -m pytest tests/unit/ -q

# 8. Run frontend (separate terminal)
cd ../frontend
npm ci
npm run dev

# 9. Run evaluation benchmark
cd ../backend
.venv\Scripts\python.exe -m evaluation.run_benchmark --output-dir evaluation/reports
```

**Default seeded accounts** (`scripts/seed_db.py`, dev only):

| Account | Email | Password | Role |
|---|---|---|---|
| Admin | `admin@asto.local` | `admin123` | admin |
| Client | `client@asto.local` | `client123` | client (external) |

The admin approves the seeded pending document via **Asto Admin** → Approvals
(`/admin`), then it becomes searchable.

---

## Production Deployment

```bash
# 1. Shared Postgres + Nginx
cd shared-host-infra-scaffold/infra/shared
cp .env.example .env
docker compose up -d

# 2. Install socket-activated backend
sudo cp infra/systemd/asto-backend.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now asto-backend.socket
sudo systemctl enable --now asto-backend-idle.timer

# 3. Set secrets
export ASTO_DATABASE_URL=postgresql://asto_app:S3CRET@127.0.0.1:5433/asto_assistant
export ASTO_JWT_SECRET="at-least-32-char-secret-key-here"

# 4. Seed schema (if not auto-created)
bash infra/scripts/migrate_db.sh

# 5. Run batch ingestion
bash infra/scripts/run_ingestion.sh

# 6. Build frontend (static)
cd frontend
npm run build && npx serve -s out -p 3011
```

---

## Testing

Tests are split into **unit** (no database) and **integration** (RBAC enforcement):

```bash
cd backend
.venv\Scripts\python.exe -m pytest tests/unit/ -q
.venv\Scripts\python.exe -m pytest tests/ -q
```

**Unit test modules (140 tests):**
- `test_backend_skeleton.py` — App startup, auth, JWT, RBAC, endpoints
- `test_documents.py` — Ingestion validation, chunking, metadata
- `test_search_ranking.py` — BM25 query building, metadata filters, RRF
- `test_response.py` — Confidence thresholds, package builder, validation
- `test_spell_correction.py` — Spell correction phrase repair
- `test_summarizer.py` — Extractive (verbatim) summary
- `test_approvals.py` — Approval workflow (pending → approve/reject, audit trail)
- `test_client_auth.py` — Client JWT, client login, client-scoped endpoints

**Integration tests (11 tests, live Postgres):**
- `test_rbac_prefilter.py` — RBAC enforcement in SQL WHERE clause
- `test_dual_audience.py` — Staff vs client scoping end-to-end
- `test_end_to_end.py` — Full login → search → response package → audit
- `test_approvals.py` — Pending invisible → approved searchable → rejected invisible

---

## Evaluation & Benchmarks

The evaluation framework runs 20 test questions against the query-processing pipeline and measures accuracy + latency:

```bash
cd backend
.venv/bin/python -m evaluation.run_benchmark --output-dir evaluation/reports
```

**Latest results** (`evaluation/reports/benchmark_20260808_005649.json`):
- Sub-question decomposition accuracy: 100%
- Intent accuracy: 58.3%, entity accuracy: 91.7%
- Retrieval: hit_rate@5 91.7%, ndcg@10 85.4%, MRR 75%
- Search latency: p50 10.8ms / p95 20.8ms (warm)
- Cold start: ~368ms

Results are uploaded as artifacts in CI and used for regression detection on PRs.
No ranking/confidence change has been made since this baseline (Sessions 3–4
touched auth, approval workflow, and frontend only), so no benchmark re-run was
required.
