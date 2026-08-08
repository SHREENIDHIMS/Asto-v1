---
name: asto-assistant-builder
description: Step-by-step build playbook for Asto (V3.2 shared-host architecture). Use this whenever building, extending, or resuming work on this specific project — setting up infra, scaffolding the FastAPI backend, wiring the query/search/ranking pipeline, building document ingestion, building the frontend, deploying to the shared EC2 host, or setting up the evaluation framework. Always consult this skill before starting a new phase of the build or when picking up the project after a break, so work happens in the correct dependency order and respects the constraints in CLAUDE.md.
---

# Mortgage Assistant — Build Playbook

This skill defines the **order** to build this project in, and for each
phase: what must exist before you start (Input), what must exist when
you're done (Output), constraints specific to that phase, and how to know
it's actually done (Definition of Done). Phases are ordered by dependency
— don't skip ahead; later phases assume earlier ones are working.

Always read `CLAUDE.md` first for the non-negotiable architectural rules.
This skill is the "in what order" companion to that "what rules" doc.

---

## Phase 0 — Environment & Shared Infra

**Input:** A fresh EC2 instance (or local dev machine), nothing else.

**Steps:**
1. Follow `infra/README.md` steps 1–2: install Docker, add 2GB swap,
   bring up `infra/shared/docker-compose.yml` (shared Postgres+pgvector,
   shared Nginx).
2. Confirm both containers are healthy: `docker compose ps`.
3. Set a CloudWatch billing alarm at $0 (console, one-time, do this before
   anything else touches the box).

**Output:** Shared Postgres (with `vector` extension enabled) and shared
Nginx running, reachable at `127.0.0.1:5433` and ports 80/443 respectively.

**Constraints:** Do not launch any project-specific containers here. This
phase only touches `infra/shared/`.

**Definition of Done:** `docker exec shared_postgres psql -U admin -c "SELECT * FROM pg_extension WHERE extname='vector';"` returns a row. `curl localhost` returns Nginx's default response (before any server blocks are added).

---

## Phase 1 — Backend Skeleton

**Input:** Phase 0 complete.

**Steps:**
1. Scaffold `backend/app/` per `Final_Folder_Structure.md`: `main.py`,
   `config.py`, `dependencies.py`, empty `api/v1/` route files that return
   `501 Not Implemented` placeholders.
2. Add `db/postgres/session.py` connecting to the shared instance, using
   this project's own database (created via
    `infra/shared/postgres/init/01_asto_assistant.sql`).
3. Set up Alembic; first migration creates the `document_chunks` table
   with a `vector(384)` column (dimension matches bge-small-en-v1.5).
4. Add `auth/jwt_handler.py` and a minimal `/api/v1/auth/login` endpoint
   backed by a `users` table (email, hashed password, role).
5. Write `Dockerfile` using `python:3.11-slim`.

**Output:** A FastAPI app that starts, connects to Postgres, and can issue
a JWT on login. No search/ranking/ingestion logic yet.

**Constraints:** `--workers 1` in every run command from here on. Don't
add Redis, Qdrant, or MinIO clients even as placeholders.

**Definition of Done:** `uvicorn app.main:app --workers 1` starts cleanly;
`POST /api/v1/auth/login` with a seeded test user returns a valid JWT;
`alembic upgrade head` runs without error against the shared Postgres
instance.

---

## Phase 2 — Document Ingestion (Batch Pipeline)

**Input:** Phase 1 complete (need `document_chunks` table and DB session).

**Steps:**
1. Build `documents/upload.py` — API endpoint that validates file
   type/size and writes to `storage/pending/`, returns immediately. It
   must NOT call any ingestion logic directly.
2. Build the ingestion pipeline as a **separate, standalone module** —
   `documents/ingest_batch.py` as the entry point, calling in order:
   `validation.py` → `ocr.py` (optional) → `text_extraction.py` →
   `chunking/structural_chunker.py` → `metadata_extraction.py` →
    `entity_extraction.py` (dictionary-based) → `embedding.py` (FastEmbed) →
   `indexing.py` (writes rows + pgvector column).
3. Implement `chunking/structural_chunker.py` to dispatch by structure
   type (heading/section, table, checklist, paragraph) per
   `Final_System_Design.md` §6 — tables must never be split mid-table.
4. Wire `infra/scripts/run_ingestion.sh` to call `ingest_batch.py` against
   `storage/pending/`, moving processed files to `storage/processed/`.

**Output:** Uploading a PDF via the API, then manually running
`run_ingestion.sh`, results in searchable rows in `document_chunks` with
populated embeddings.

**Constraints:** The embedding model must only be loaded
inside `ingest_batch.py`'s process, never imported at module level in
`app/main.py` or any request handler (that would load them into the
always-on process). Verify with `ps`/`pmap` that the API process's RSS
doesn't include these models after a normal request.

**Definition of Done:** End-to-end test: upload a sample document
(with at least one table), run ingestion, query `document_chunks` and
confirm (a) the table appears as a single chunk, not fragmented, and
(b) `embedding` is non-null for every row.

---

## Phase 3 — Query Processing Engine

**Input:** Phase 1 complete. Independent of Phase 2 (can be built in
parallel), but needs ingested data to test end-to-end.

**Steps:**
1. Build `query_processing/spell_correction.py` (RapidFuzz/SymSpell),
   `normalization.py`, `intent_detection.py`, `query_expansion.py`.
2. Build `query_processing/entity_extraction.py` — dictionary-based
       entity extraction (domain terms + numeric patterns). Replaces the
       originally-planned NLP model approach — lighter and sufficient.
3. Assemble into a `process_query(raw: str) -> StructuredQuery` function.

**Output:** A pure function that takes a raw query string and returns a
structured object (corrected text, detected intent, extracted entities,
expanded terms) — no side effects, no DB calls.

**Constraints:** Keep this stage query-time only. Don't reuse
ingestion's `entity_extraction.py` — query-time uses a lighter
dictionary approach. They may diverge over time.

**Definition of Done:** Unit tests covering: a misspelled query gets
corrected; a query naming a lender gets that entity extracted; an
acronym gets expanded via the synonym dictionary.

---

## Phase 4 — Hybrid Search + Ranking + Reranking

**Input:** Phases 2 and 3 complete.

**Steps:**
1. Build `search/metadata_filters.py` — translates the requesting user's
   RBAC scope (from their JWT/role) into a SQL `WHERE` clause fragment.
2. Build `search/pgvector_search.py` and `search/bm25_search.py`, then
   `search/hybrid_orchestrator.py` combining them into the single-query
   pattern from `Final_System_Design.md` §4 — RBAC and active-version
   filtering **inside** the `WHERE` clause, not applied after.
3. Build `ranking/rrf.py` and `ranking/scoring.py` implementing the
   weighted formula, reading weights from `ranking/weights_config.py`
   (DB-backed, defaults from `Final_Tech_Stack.md`).
4. Build `ranking/reranker.py` loading the ONNX Int8 quantized
   cross-encoder, scoring only the top-10 RRF candidates.
5. Add a latency assertion/log around the reranker call.

**Output:** Given a `StructuredQuery` and a user's RBAC scope, returns a
ranked, permission-safe list of chunk candidates.

**Constraints:** Write a test that deliberately includes a chunk the test
user is NOT permitted to see, and assert it never reaches the reranker
(check via a call-count mock), not just that it's absent from the final
output — this is the constraint from `CLAUDE.md` rule 1 and needs a test
that would actually catch a regression.

**Definition of Done:** Integration test with seeded data across two
departments and two users with different RBAC scopes returns correctly
scoped results for each; reranker latency logged and under 200ms p95
across 20 sample queries.

---

## Phase 5 — Response Packaging + Validation + Audit

**Input:** Phase 4 complete.

**Steps:**
1. Build `response/package_builder.py` assembling the retrieved chunks
   into the Response Package shape (Title, Excerpts, Summary, Steps,
   Required Docs, Source/Page/Section, Confidence, Related Questions) —
   every field sourced from retrieved data, nothing abstractively
   synthesized. `Summary` is populated by the extractive summarizer
   (`response/summarizer.py`, Sumy TextRank).
2. Build `response/confidence_thresholds.py` implementing the 90/75/50
   routing behavior from `Final_System_Design.md` §5.
3. Build `response/validation.py` as the redundant safety-net check
   (permission re-check, version re-check, confidence gate).
4. Build `audit/audit_logger.py` — called on every request regardless of
   outcome (including "no answer found").
5. Build `knowledge_gap/gap_detector.py` — logs when confidence falls
   below 50.

**Output:** A complete `/api/v1/search` endpoint: query in, Response
Package out, every request audit-logged.

**Constraints:** No field in the Response Package may contain text that
doesn't trace back verbatim (or near-verbatim excerpt) to a source chunk.
The one allowed exception is `response/summarizer.py` — a Sumy TextRank
**extractive** summary that selects up to 4 sentences verbatim from the top
excerpts and maps each back to its source. If you need to paraphrase,
rewrite, or synthesize across chunks, stop — that's generation; flag it to
the user instead of implementing it.

**Definition of Done:** Full request/response test through the real
endpoint (not mocked) for confidence bands >90, 75–89, 50–74, and <50,
confirming each routes correctly and produces an audit log row.

---

## Phase 6 — Frontend

**Input:** Phase 5 complete (needs a working `/api/v1/search` to build
against).

**Steps:**
1. Scaffold Next.js with `output: 'export'` in `next.config.js` from the
   start — don't build with server routes and convert later.
2. Build `lib/api-client.ts` calling FastAPI directly (no BFF proxy).
3. Build `components/search/` per `Final_Folder_Structure.md`:
   `SearchBar`, `ResponsePackageCard`, `ConfidenceBadge`,
   `SourceCitation`, `RelatedQuestions`.
4. Build `components/feedback/ThumbsFeedback.tsx` wired to
   `/api/v1/feedback`.
5. Build the `(auth)` and `(dashboard)` route groups with client-side JWT
   handling (`lib/auth.ts`) — remember there is no server-side session,
   auth state lives in the browser and every API call carries the JWT.

**Output:** `npm run build` produces static files in `frontend/out/` that
can be served directly by the shared Nginx.

**Constraints:** No `app/api/` route handlers. No server-only Next.js
features (no `getServerSideProps`-equivalent, no server actions).

**Definition of Done:** `npm run build` succeeds with `output: 'export'`;
manually serving `frontend/out/` with any static file server and pointing
`api-client.ts` at a running backend produces a working search flow.

---

## Phase 6.5 — Dual-Audience Auth + Approval Workflow + Frontend UX

**Input:** Phase 6 complete (working `/api/v1/search`, working frontend).
Added 2026-08-08 (Sessions 3–4) — retrofitted onto the finished baseline.

**Steps:**
1. **Approval workflow (B3):** make `documents/indexing.py` insert
   documents/chunks with `approval_status='pending'`, `is_approved=false` by
   default. Add `api/v1/approvals.py`: list pending, approve, reject, history.
   Transitions must update the document AND all its chunks in one transaction
   and write `approval_log` (reviewer, from→to, timestamp).
2. **Approval filter in search:** `search/metadata_filters.py` must include
   `is_approved = true` in the same `WHERE` clause as RBAC/version filters —
   pending/rejected rows never reach ranking or the reranker (extends
   CLAUDE.md rule #1 to the approval gate).
3. **Client auth (C):** extend `auth/jwt_handler.py` with `audience`
   ("staff"/"client") and `client_id` claims. Add `POST /auth/client-login`
   against the `clients` table. Extend `dependencies.get_current_user` to
   resolve BOTH audiences. Make `permissions.require_role` fail-closed for the
   client audience.
4. **Client API (C):** add `api/v1/client.py` (`me`, `properties`, `cases`,
   `documents`) scoped strictly by the authenticated `client_id` — never from
   the request body. Extend `admin.py` with user/client creation + staff↔client
   assignments.
5. **Frontend (D):** chat view (`/`) with assistant bubbles wrapping
   `ResponsePackageCard`; 24h localStorage history (`hooks/use-chat-history.ts`,
   TTL-purged); `/login` Staff/Client tabs; `/portal` client dashboard; `/admin`
   dashboard (approvals, documents+upload, users, clients, analytics). Gate each
   page by `decodeToken` (`audience`/`role`), redirect unauthorized users to
   `/login`.
6. **Seed:** `scripts/seed_db.py` with admin, client, property, case,
   assignment, and one pending document for manual approve/reject testing.

**Output:** Two audiences (staff + external clients) share one corpus with
hard separation; new documents are approval-gated; the frontend exposes chat,
client portal, and an admin dashboard.

**Constraints:**
- Approval + RBAC scoping live in the SQL `WHERE` clause, never post-hoc.
- `response/validation.py` must NOT reject low-confidence packages (that would
  turn `no_answer` into HTTP 500) — routing is decided by
  `route_by_confidence`, validation only enforces RBAC/approval safety-nets.
- No LLM, no Qdrant/Redis/MinIO, no per-project Postgres — the baseline rules
  all still hold.

**Definition of Done:** 140 unit + 11 integration tests pass; live verification
shows client login → scoped portal data, pending doc invisible → approve →
searchable → audit trail, reject → not searchable; `npm run build` + `lint`
clean; `/`, `/login`, `/portal`, `/admin` all serve 200 from the deployed
static export.

---

## Phase 7 — On-Demand Deployment (Systemd)

**Input:** Phases 1–6 complete and working locally.

**Steps:**
1. Follow `infra/README.md` step 3: install the socket/service/timer
    units, enable and start `asto-backend.socket` and
    `asto-backend-idle.timer`.
2. Add `nginx/conf.d/asto-assistant.conf` to `infra/shared/nginx/conf.d/`
   and reload Nginx.
3. Deploy `frontend/out/` to the path referenced in that Nginx config.
4. Verify cold-start behavior: hit the endpoint after the socket has been
   idle, confirm the service activates and responds within a reasonable
   cold-start window; hit it again immediately and confirm it's fast
   (warm).
5. Verify idle-stop: leave it untouched for >10 minutes, confirm
    `systemctl status asto-backend.service` shows inactive.

**Output:** The full stack reachable via the real domain/subdomain,
running only when it has traffic.

**Constraints:** Don't disable the idle timer "to make it always fast" —
if latency is unacceptable, that's a signal to revisit Phase 4/5
performance, not to defeat the memory-sharing design.

**Definition of Done:** `curl` the live endpoint after a 15-minute gap and
measure the cold-start latency; record it in `evaluation/reports/` as a
baseline.

---

## Phase 8 — Evaluation Framework

**Input:** Phases 1–5 complete (needs a working search pipeline to
evaluate against). Can run against local or deployed instance.

**Steps:**
1. Build `evaluation/datasets/eval_100_questions.jsonl` — real or
    realistic domain questions with expected document + expected chunk,
   built from actual ingested content, not invented in the abstract.
2. Build the metrics: `precision_recall.py`, `mrr.py`, `ndcg.py`,
   `hit_rate.py`, `latency_benchmark.py`.
3. Build `run_benchmark.py` to run the full pipeline per question and
   output a report to `evaluation/reports/<timestamp>.json`.
4. Wire `eval_on_pr.yml` in CI to run this on every PR touching
   `search/`, `ranking/`, or `response/confidence_thresholds.py`, and
   fail the check on regression beyond a defined tolerance.

**Output:** A repeatable benchmark you can point at any version of the
ranking/threshold config and get comparable numbers.

**Constraints:** Don't hand-tune `weights_config.py` or
`confidence_thresholds.py` without a benchmark run before and after
showing the change is actually an improvement — this is the enforcement
mechanism for CLAUDE.md rule 7.

**Definition of Done:** Two consecutive benchmark runs with no code
changes produce consistent results (checks the benchmark itself is
deterministic enough to trust); a deliberate ranking-weight change shows
up as a measurable metric delta in the report.

---

## Phase 9 — Second Project Onboarding (when applicable)

**Input:** This project fully deployed per Phase 7, and a second project
ready to share the host.

**Steps:** Follow `infra/README.md` step 5 exactly — new
`<project>.socket`/`.service` pair on a new port, new idle timer, new
Nginx server block, new Postgres database (not new instance).

**Constraints:** Before onboarding, check real memory headroom on the
host (`free -h`) with this project idle vs. under load — don't assume
the theoretical budget from `Final_System_Design.md` §7 holds without
checking.

**Definition of Done:** Both projects' idle-stop/wake cycles work
independently; hitting one doesn't wake the other; combined idle RAM
usage matches the ~230MB baseline expectation (within reason).
