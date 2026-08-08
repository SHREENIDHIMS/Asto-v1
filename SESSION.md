# Asto — Session Summary

> **Always read this file at the start of every session and update it at the
> end.** It is the single source of truth for *where the project is now* and
> *what to do next*. Companion files: `TEMPLATE.md` (how we work), `CLAUDE.md`
> (hard rules), `SKILL.md` (build order).

---

## Project Identity (DO NOT CHANGE)

- **Product name:** Asto (renamed from Hexta / HeXta on 2026-08-08 — see Session 1)
- **Positioning:** Dual-audience **Knowledge & Process Assistant**
  1. Internal staff/process efficiency (role, department, and assigned
     client/case scope).
  2. Authenticated external clients — secure self-service access to *their own*
     documents, properties, mortgage/cases, status, requirements, and
     end-to-end process info.
- **Core philosophy (non-negotiable):** *"Find the right information, don't
  generate new information."* No LLM in the serving path. Every response field
  is a verbatim/near-verbatim excerpt with a source citation.

---

## Architecture Snapshot (where we are)

- **Backend:** FastAPI + psycopg3 + pgvector (BM25 + vector in a single SQL
  query), JWT + RBAC (staff **and** client audiences), `--workers 1`,
  socket-activated, idle-stopped.
- **Dual-audience (Session 3):** clients log in via `/auth/client-login`; JWT
  carries `audience` + `client_id`; `get_current_user` resolves both tables.
  Client-scoped API under `/client/*`. Approval workflow under `/admin/documents/*`
  (pending/approve/reject + `approval_log` trail); new ingestions enter as `pending`.
- **Frontend:** Next.js 14 static export (`output: 'export'`), Tailwind +
  shadcn/ui, client-side JWT. Chat view at `/` (bubbles, 24h localStorage
  history), Staff/Client login tabs, client portal at `/portal`, admin
  dashboard at `/admin` (approvals, documents+upload, users, clients,
  analytics). No SSE streaming yet.
- **Storage:** One Postgres per host, one database per project
  (`asto_assistant`). NO Qdrant / Redis / MinIO (deliberately removed).
- **Ingestion:** Batch-only (`ingest_batch.py`), never in the request path.
- **Evaluation:** `evaluation/run_benchmark.py` + 20-question dataset; CI gates
  ranking/confidence changes.

### Ports (updated 2026-08-08 — moved off common defaults to avoid conflicts)

| Service | Host port | Notes |
|---|---|---|
| Postgres | **5433** | container internal still 5432 |
| Backend (FastAPI) | **8011** | systemd socket + docker-compose |
| Frontend (Next.js/nginx) | **3011** | docker maps 3011→80 |
| Shared-host nginx | 80/443 | host-level, unchanged |

CI workflows keep 5432 internally (isolated runners). Update any new docs/config
to these ports.

---

## Current State Audit (Session 1, 2026-08-08)

**What exists and works:**
- Full retrieval pipeline wired end-to-end: query_processing → hybrid_search →
  RRF → rerank(optional) → package_builder → validate → audit.
- **Extractive summary added (2026-08-08):** `response/summarizer.py` uses Sumy
  TextRank to select up to 4 sentences verbatim from the top excerpts, each
  mapped back to its source. Relaxed CLAUDE.md doctrine accordingly (no LLM,
  no abstractive synthesis — extractive-only, deliberate exception). Wired into
  `ResponsePackage`, `/search` response, and frontend `ResponsePackageCard`.
- RBAC enforced in SQL WHERE clause (with integration tests).
- Schema, audit log, feedback, knowledge gaps, seed scripts, evaluation suite.
- Audit findings from `AUDIT.md` (25 items) were largely remediated in prior
  work (confidence calc, auth gating, weighted score, OCR, chunkers, bcrypt,
  pagination, etc.) — re-verify, don't assume.

**What does NOT exist yet (this is the real work ahead):**
1. ~~**Dual-audience model**~~ — schema (clients/properties/cases/assignments) + RBAC filters
   exist; client AUTH + client-scoped API added (Session 3, see below).
2. ~~**Document approval workflow**~~ — schema + approval API + pending-on-ingest + audit
   trail implemented (Session 3).
3. ~~**Client (external) auth**~~ — client login, audience-scoped JWT, client endpoints
   implemented (Session 3).
4. ~~**ChatGPT-style chat UX**~~ — **DONE (Session 4):** chat thread view at `/`,
   assistant bubbles, 24h localStorage history, typing indicator. True token
   streaming (SSE) not started — deliberate carry-over.
5. ~~**Admin dashboard**~~ — **DONE (Session 4):** `/admin` with approvals queue,
   documents + upload, users, clients + assignments, knowledge-gap analytics.
   No charts — analytics tab shows the raw knowledge-gap list.
6. ~~**Runtime verification**~~ — **DONE (Session 2):** `.venv` (3.11) installed,
   unit (107) + integration (7) tests pass, compose up healthy, benchmark run.

---

## Session Log

### Session 4 — 2026-08-08 (Phase D — frontend: chat UX, client portal, admin dashboard)

**Done (Phase D):**
- **D1 Chat view** (`/`): converted the single search box into a ChatGPT-style
  conversation. User questions render as right-aligned bubbles; each Asto
  answer renders as an assistant bubble wrapping the existing
  `ResponsePackageCard` (title, confidence badge, verbatim summary with
  citations, source excerpts) + thumbs feedback. Related questions append to
  the conversation; a typing indicator + skeleton shows while a query runs.
- **D2 24h local-only history**: new `hooks/use-chat-history.ts` persists
  turns (query + full response package) to `localStorage` keyed
  `asto_chat_history`, purges entries older than 24h on load, and supports
  clear-all ("New conversation") and per-turn remove. No server persistence.
- **Client portal** (`/portal`): authenticated client-only dashboard showing
  profile, properties, cases (loan amount/status), and approved documents.
  Redirects non-client JWTs to `/login`. Header links to "Ask Asto".
- **Client login**: `/login` now has a Staff/Client tab — client tab calls
  `/auth/client-login` and stores the client-scoped JWT (audience="client").
- **D3 Admin dashboard** (`/admin`): admin-role-only management UI with five
  tabs:
  - Approvals — pending-queue (approve/reject writes the audit trail, refresh)
    + per-document approval history dialog.
  - Documents — upload (multipart → `/documents/upload`, explains pending +
    batch-ingest flow) + list-all with status badges.
  - Users — list + create staff users (role/department selects).
  - Clients — list + create client accounts + assign staff to client.
  - Analytics — knowledge gaps (no-answer / low-confidence queries).
- **Auth routing**: `auth.ts` gained `decodeToken()` (reads `audience`, `role`,
  `client_id`, `exp` from the JWT payload) used by all three pages to gate and
  route. `/` and `/admin` redirect unauthenticated / wrong-audience visitors to
  `/login`. Client audience gets a "you can only see your own approved
  documents" banner.
- **API client**: `api-client.ts` extended with clientLogin, client
  me/properties/cases/documents, admin approvals (pending/approve/reject/
  history), documents list + upload, users (list/create), clients
  (list/create/assign), and knowledge-gaps — all typed to the live response
  shapes.
- **Baseline gap closed (Session 2 carry-over):** host `npm ci` deps present,
  `npm run build` + `npm run lint` both clean on the host.
- **Verified live**: built + deployed the frontend container (`docker compose
  build frontend && up -d`). `/`, `/login`, `/admin`, `/portal` all serve 200.
  API smoke test confirmed every new frontend call matches the real backend
  shapes (staff+client login, pending queue, history keys, users/clients keys,
  portal me/properties/cases/documents keys, knowledge-gaps keys, search
  `related_questions` array) and that authz holds (staff→/client/me 403,
  client→/admin/users 403, duplicate user create 409).

**Not done / carry to next session:**
- Phase E (docs/README/design-doc consistency) — not started.
- Streaming response (real SSE streaming-lite) — the UI shows a skeleton while
  awaiting the response; not yet token streaming (backend is request/response).
- Admin dashboard has no analytics charts (only the knowledge-gaps list) and no
  document view/download; client portal has no document open/download.
- The deployed frontend uses the baked-in `localhost:8011` API base (no
  NEXT_PUBLIC_API_URL build arg) — fine for local dev, must be set explicitly
  for a remote host (see nginx + compose).

### Session 5 — 2026-08-08 (Phase E — documentation & consistency)

**Done (Phase E):**
- **E1 Docs updated for dual-audience + approval workflow:**
  - `README.md` — rewritten intro (staff + client audiences, approval
    workflow), architecture diagram, constraints table, step-1 auth + step-1b
    approval workflow sections, frontend component table, project structure
    matching reality, quick start with seed accounts
    (`admin@asto.local/admin123`, `client@asto.local/client123`), testing
    section (140 unit + 11 integration, module names verified against the
    tree), evaluation section pointing at
    `evaluation/reports/benchmark_20260808_005649.json`.
  - `Final_System_Design.md` — §8b **Dual-Audience Authentication**
    (mermaid login flow), §8c **Document Approval Workflow** (state diagram +
    gate in the search WHERE clause), component-responsibility table gained
    Approval Workflow + Dual-Audience Auth rows, design decisions #11 and #12.
  - `Final_Folder_Structure.md` — rewrote the tree to match the actual
    repository (flat `frontend/app/` pages `page/login/portal/admin`, `lib`
    `api-client.ts` + `auth.ts` with `decodeToken`,
    `hooks/use-chat-history.ts`, `components/chat/ChatMessage.tsx`; backend
    gained `api/v1/approvals.py`, `api/v1/client.py`, extended
    `admin.py`/`jwt_handler.py`/`dependencies.py`/`indexing.py`,
    `scripts/seed_db.py`, new tests). Added a "Added 2026-08-08" table for
    the Session 3–4 deltas. Dropped dead artifacts (Qdrant, Redis, MinIO,
    per-project Postgres, `infra/monitoring/`, `nlp_models/`, Alembic —
    none exist in the repo).
- **E2 SKILL.md** — inserted **Phase 6.5 — Dual-Audience Auth + Approval
  Workflow + Frontend UX** after Phase 6: approval workflow, approval filter
  in the search WHERE clause, client JWT auth (audience + client_id),
  client-scoped API, admin user/client endpoints, chat/portal/admin frontend,
  seeding, DoD (151 tests, live approve→searchable / reject→not-searchable,
  build+lint clean, all four routes 200).
- **E3 Benchmark gate** — **no re-run needed.** Audited the retrieval path:
  the only change in Sessions 3–4 was adding the `is_approved`/`is_active`
  hard pre-filter (`search/metadata_filters.py` `get_version_filter`, line
  100) plus the client/department RBAC clause — both reduce the candidate
  set; ranking weights, confidence thresholds, and the reranker are
  untouched. Baseline `benchmark_20260808_005649.json` remains the gate.

**Noted as carry-overs (unchanged from Session 4):**
- True SSE token streaming not started; admin dashboard has no charts and no
  document view/download; client portal has no document open/download; the
  deployed frontend still uses the baked-in `localhost:8011` API base.

### Session 3 — 2026-08-08

**Done (Phase B3 + Phase C — approval workflow + client auth backend):**
- **Approval workflow (B3):**
  - `indexing.py` now inserts documents/chunks with `approval_status='pending'`,
    `is_approved=false` by default (opt-in `approval_status="approved"` for seed/backfill).
    Pending docs are invisible to search (search filters on `is_approved=true`).
  - New `api/v1/approvals.py`: `GET /admin/documents/pending`,
    `POST /admin/documents/{id}/approve`, `POST /admin/documents/{id}/reject`,
    `GET /admin/documents/{id}/history`. Transitions document + all chunks
    transactionally and writes `approval_log` (reviewer, from→to, timestamp).
  - `documents.py` list now exposes `approval_status`/`approved_by`/`approved_at`.
- **Client auth (C):**
  - `jwt_handler.create_token` gains `audience` ("staff"/"client") + optional
    `client_id` claims.
  - `POST /auth/client-login` authenticates against the `clients` table.
  - `dependencies.get_current_user` resolves BOTH audiences: staff → `users`,
    client → `clients` tagged `audience="client"` + `client_id`.
  - `permissions.require_role` is now fail-closed for the client audience and
    unknown roles (closed a fail-open hole that let "client" pass role checks).
  - New `api/v1/client.py` (client-scoped, own data only): `/client/me`,
    `/client/properties`, `/client/cases`, `/client/documents`.
  - `api/v1/admin.py` extended (C3): `POST /admin/users`, `GET+POST /admin/clients`,
    `POST /admin/assignments` (staff↔client scoping).
- **Seed:** `scripts/seed_db.py` seeds client@asto.local / **client123**, a property,
  a case (CAS-2026-0001), admin→client assignment, and a pending-review document.
- **Tests:** 140 unit + 11 integration pass (151 total). New `test_approvals.py` and
  `test_client_auth.py`. Fixed a subtle test-isolation issue: `test_approvals.py`
  originally imported `app.main` at module scope, which bound
  `dependencies.acquire` to the real DB function before conftest's autouse mock ran
  (breaking the "mock DB has no users" assumption for later files) — imports are now
  lazy inside test bodies, matching existing convention.
- **Live verification** (docker compose backend rebuilt + restarted): client login → me/
  properties/cases/documents all 200; client search returns scoped results; client
  hitting `/admin/*` → 403; admin list pending → approve → searchable + audit trail;
  reject → not searchable (`no_answer`) + audit trail.

**Not done / carry to next session:**
- Phase D: chat UX (thread UI, 24h localStorage history, typing UX) — not started.
- Phase E: admin dashboard UI — not started.
- `frontend` npm deps still not installed on host (verified via Docker build only).
- No new evaluation benchmark run needed (no ranking/confidence changes this session).

### Session 2 — 2026-08-08

**Done (Phase A — baseline verification):**
- Added **Sumy extractive summary** (user-approved, CLAUDE.md doctrine relaxed):
  `response/summarizer.py` (TextRank, 4 verbatim sentences, self-contained
  tokenizer — no NLTK model download), wired into ResponsePackage, `/search`,
  and frontend `ResponsePackageCard` "Key Points" card. Fixed circular import.
- Created `backend/.venv` (CPython 3.11.15 via uv) + installed requirements/dev.
  Note: host Python 3.14 is too new for fastembed/onnxruntime — use the venv.
- **107 unit tests pass** (fixed: needed `backend/.env` from `.env.example` —
  empty `jwt_secret` caused 2 PyJWT failures).
- **7 integration tests pass, 4 skipped** (e2e tests need live Postgres; run
  after compose is up).
- `docker compose up -d --build` (ports 5433/8011/3011): all 3 containers
  healthy. `/health` → `{"status":"healthy"}`. Frontend serves on 3011.
- Seeded DB (`scripts/seed_db.py`, admin@asto.local / **admin123**) then ran
  `scripts/backfill_embeddings.py` (6 chunks had no embedding). First search
  returned no results because search requires `embedding IS NOT NULL`.
- Verified end-to-end: login → search "minimum credit score for loan" →
  routing=answer, title + 3-sentence summary with source citations + 2 excerpts.
- **Evaluation benchmark run** → `evaluation/reports/benchmark_20260808_005649.json`:
  sub-question 100%, intent 58.3%, entity 91.7%; hit_rate@5 91.7%, ndcg@10
  85.4%, MRR 75%; end-to-end search p50 10.8ms / p95 20.8ms; cold start 368ms.
- Downloaded bge-small-en-v1.5 (~66MB) to host `backend/nlp_models/embeddings/`
  (user-approved) for benchmark retrieval phase.

**Not done / blocked:**
- `frontend` npm deps still not installed (`npm ci`) — frontend verified via
  Docker build, not `npm run lint`/`next build` on host.
- None of Phase B–E (dual-audience model, approval workflow, client auth, chat
  UX, admin dashboard).

### Session 1 — 2026-08-08

**Done:**
- Audited project structure, docs, compose, schema, search pipeline, infra.
- Renamed project **Hexta/HeXta → Asto** everywhere (39 files + 6 file renames):
  env prefix `HEXA_`→`ASTO_`, DB `hexa_assistant`→`asto_assistant`, user
  `hexa_app`→`asto_app`, containers/services `hexa-*`→`asto-*`, systemd units,
  nginx conf, package.json name, UI title, docs, CI. Verified zero `hexa`
  matches remain (excluding node_modules/.venv).
- Reassigned ports to avoid clashes: 5433 / 8011 / 3011 (see table above),
  updated compose, Dockerfile, nginx, systemd, .env examples, api-client,
  package.json dev script, infra scripts, README/SKILL/design docs, deploy CI.
- Created this file (`SESSION.md`) + `TEMPLATE.md`.

**Not done / blocked (carry to next session):**
- Full runtime test run (needs venv: Python 3.11 + `pip install -r
  requirements.txt -r requirements-dev.txt`).
- Docker compose up + health check (needs Docker running).
- All the new dual-audience / approval / chat / admin work below.

---

## Next Steps (prioritized — work in this order)

### Phase A — Baseline verification ✅ DONE (Session 2)
- [x] A1: Create `backend/.venv` with Python 3.11; install requirements + dev.
- [x] A2: `pytest tests/unit -q` and `pytest tests/integration -q` — fix failures.
      (Includes new `tests/unit/test_summarizer.py` — Sumy extractive summary.)
- [x] A3: `docker compose up -d` (ports 5433/8011/3011) and hit `/health`.
- [x] A4: Run `evaluation/run_benchmark.py`, record report in `evaluation/reports/`
      (`benchmark_20260808_005649.json`).

### Phase B — Data model for dual-audience (schema + models + migrations)
- [x] B1: Add tables: `clients`, `properties`, `cases` (mortgage/case), and
      `client_document_access` / ownership links. (Schema existed; verified + seeded.)
- [x] B2: Scope staff by assigned client/case (`staff_client_assignments`), keep
      department RBAC. (Filters existed; admin assignment endpoint added Session 3.)
- [x] B3: Add document **Pending/Approved/Rejected** state machine + reviewer
      audit trail (who/when approved). (API + pending-on-ingest + audit trail added
      Session 3.)
- [x] B4: Wire scoping into `search/metadata_filters.py` WHERE clause (staff =
      dept ∩ assigned clients; client = own client_id only). Keep rule #1. (Existed;
      verified end-to-end with client audience.)

### Phase C — Auth for both audiences
- [x] C1: Client role + client identity in JWT; separate login for clients.
- [x] C2: Authorization **before** retrieval and before any context reaches LLM
      (there is no LLM today — preserve that guarantee).
- [x] C3: Admin/super_admin-only endpoints for approval + user management.

### Phase D — UX
- [x] D1: Chat view (chat-style conversation, message bubbles, streaming-lite).
      (Conversation + typing indicator done Session 4; true streaming not started.)
- [x] D2: 24-hour local-only history (localStorage), no server persistence by
      default. (Done Session 4 — `use-chat-history.ts`.)
- [x] D3: Separate admin dashboard (approvals queue, uploads, analytics).
      (Done Session 4 — `/admin`; uploads + knowledge-gaps + user/client mgmt.)
- [x] D4: Client portal + client login (added Session 4 alongside D1–D3:
      `/portal`, Staff/Client login tabs).

### Phase E — Documentation & consistency (done Session 5, 2026-08-08)
- [x] E1: Update `README.md`, `Final_System_Design.md`, `Final_Folder_Structure.md`
      for dual-audience + approval workflow.
- [x] E2: Update `SKILL.md` build order with new phases if architecture changes
      (added Phase 6.5 — Dual-Audience Auth + Approval Workflow + Frontend UX).
- [x] E3: Re-run evaluation benchmark after any retrieval-affecting change —
      **none made.** The only retrieval-path change in Sessions 3–4 was the
      `is_approved`/`is_active` hard pre-filter in
      `search/metadata_filters.py` (`get_version_filter`, line 100), which
      reduces the candidate set without touching ranking weights, confidence
      thresholds, or the reranker. Baseline `benchmark_20260808_005649.json`
      stands; no re-run required.

---

## Open Questions / Decisions for the User

1. **Abstractive summarization / LLM on the serving path?** Today: none, by
   design. An **extractive** summary (Sumy TextRank, 4 verbatim sentences with
   citations) was added on 2026-08-08 and is fully compliant. Abstractive
   synthesis (an LLM, T5/BART, "rewrite this in your own words") would break
   the compliance guarantee and requires an explicit decision — not
   recommended.
2. **Client data source** — will clients/properties/cases be seeded from an
   existing CRM/DB, or entered manually via admin? (Admin CRUD for users +
   clients exists now; a CRM import script can be added when the source is known.)
3. **Chat history** — confirm 24h localStorage is acceptable (per your brief).
4. **Deployment target** — keep shared-host EC2 (1GiB) model, or move to a
   bigger instance once admin dashboard + chat added?
5. **New-document default** — ingestion now inserts as `pending` (must be
   approved before searchable). Confirm that's the desired default for the
   production ingest path (`index_document` supports `approval_status="approved"`
   if a trusted backfill path ever needs to bypass review).
