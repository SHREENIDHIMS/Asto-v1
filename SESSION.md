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
  analytics). True SSE streaming (Session 6): `POST /search/stream` pushes
  `status` → `fact`/`sentence` → `result` events as content is produced;
  staff + client chat render facts/sentences progressively.
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
   assistant bubbles, 24h localStorage history, typing indicator. True SSE
   streaming **DONE (Session 6):** `/search/stream` pushes `status`/`fact`/
   `sentence`/`result` events progressively; staff + client chat render them.
5. ~~**Admin dashboard**~~ — **DONE (Session 4):** `/admin` with approvals queue,
   documents + upload, users, clients + assignments, knowledge-gap analytics.
   Document view/download verified live (Session 6). Analytics *endpoints*
   verified live and charted in the `/admin` Analytics tab.
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
  *(Both since resolved — Session 6: document view/download + analytics charts.)*
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
  *(Resolved Session 6: streaming, document view/download, analytics charts.)*

### Session 6 — 2026-08-10 (True SSE streaming + document view/download + analytics verification)

**Done (Phase D carry-overs closed):**
- **Verified document view/download (#2):** admin `GET /documents/{id}/file`
  and client `GET /client/documents/{id}/file` both serve stored files (admin
  resolve confirmed 200 with the stored file). Seeded demo docs reference
  `/docs/*.pdf` that were never placed in storage, so those rows 404 — the
  endpoint logic is correct and works whenever a real file is on disk
  (`documents/file_serve.py` searches processed/ then pending/ by basename).
- **Verified analytics (#3):** `GET /analytics/summary` + `/analytics/knowledge-gaps`
  live on `admin@asto.local` (empty until real gaps accumulate — gap logging is
  wired into the pipeline).
- **True SSE streaming (backend):** replaced the "streaming-lite" buffered
  stream in `api/v1/search.py`. `_run_pipeline` now emits typed events via a
  `(event_type, data)` callback; `POST /search/stream` runs the sync pipeline
  in a worker thread (`asyncio.to_thread`) draining an `asyncio.Queue` so each
  event is flushed as soon as it is produced — no more single buffered payload.
  Event order: `status` (processing/searching/ranking/packaging/done) →
  one `fact` event per structured-fact row (fact path) or one `sentence`
  event per extractive summary sentence (document path) → `result` (same
  payload as the sync endpoint) → `error` on failure. No LLM, no generated
  text — every streamed item is a verbatim retrieved value.
- **Frontend streaming UI:** `lib/api-client.ts`
  `searchKnowledgeBaseStream` now takes a handlers object
  (`onStage`/`onFact`/`onSentence`); new
  `components/chat/StreamingPreview.tsx` renders the stage label plus facts /
  summary sentences as they arrive; wired into the staff chat (`/`) and client
  chat (`/client`) loading bubbles (reset on new search/regenerate, replaced by
  the full `ChatMessage` when `result` lands). Staff page supports case-context
  fact streaming; client page streams own-case facts + document summaries.
- **Tests:** new integration tests — `test_fact_path_integration.py`
  `test_stream_emits_fact_events_then_result` (SSE stream: statuses → fact
  events → result, one fact event per fact, verbatim values + sources) and
  `test_end_to_end.py` `test_document_path_stream_emits_sentence_events`
  (sentence events == summary rows). Full suite: **311 passed**
  (unit + integration, live Postgres).
- **Live verification:** rebuilt `asto-backend` + `frontend`, recreated both.
  Client fact query over `/search/stream` returned
  status → 5 fact events → result; admin document query returned
  status → 2 sentence events → result; sync `/search/` still returns a full
  package (routing=answer, confidence 100). Frontend container serves the
  `StreamingPreview` chunk.
- **Build hygiene:** `npm run build` clean, `tsc --noEmit` clean, ESLint clean
  on changed files.

**Not done / carry to next session:**
- Admin dashboard still shows only the raw knowledge-gap list (no charts yet) —
  the analytics *endpoints* are verified; a chart UI is the remaining piece.
  *(Fixed: `/admin` Analytics tab renders charts — see Session 8.)*
- Seeded demo docs have no real source files on disk (they 404 on view) —
  either place PDFs in `storage/processed/` matching their basenames or upload
  fresh docs to see view/download end-to-end.
- Phase E docs (README/design-doc) not re-touched for streaming; this entry is
  the record.

### Session 7 — 2026-08-10 (Unified single sign-in — no Staff/Client selector)

**Done:**
- **Unified `POST /auth/login`:** `api/v1/auth.py` now resolves the identity
  across both tables in one request — checks `users` (staff) first, then
  `clients` (external). Returns the audience-scoped JWT (staff →
  role/department claims; client → `audience="client"` + `client_id`). The
  frontend already auto-routed by JWT claims, so removing the tabs completes
  the flow: **one login form, identity auto-detected from email/password.**
- **Single generic 401:** a failed match on both tables returns one
  "Invalid credentials" error, so the response never reveals which table an
  email belongs to.
- **Deterministic precedence:** an email present in both tables resolves as
  staff (documented in `auth.py` docstring).
- **Frontend:** `app/login/page.tsx` rewritten as a single form (email +
  password + remember-me + forgot-password), tabs removed. Removed the now
  unused `clientLogin` helper from `lib/api-client.ts`; `/auth/client-login`
  endpoint kept for backward compatibility.
- **Tests:** new `tests/integration/test_unified_login.py` (4 tests) — staff
  and client both resolve via `/auth/login` with correct JWT claims, bad
  password/unknown email → generic 401, legacy `/auth/client-login` still
  works. Full suite: **315 passed** (unit + integration, live Postgres).
- **Live verified:** rebuilt `asto-backend` + `frontend`. `admin@asto.local`
  and `client@asto.local` both log in via `/auth/login`; wrong password → 401;
  `/login` serves 200 and the login page chunk contains zero `TabsTrigger`
  references.

**Not done / carry to next session:**
- Admin analytics tab still shows the raw knowledge-gap list (no charts yet) —
  the analytics endpoints are verified; a chart UI is the remaining piece.
  *(Fixed: `/admin` Analytics tab renders charts — see Session 8.)*
- Seeded demo docs still reference `/docs/*.pdf` that were never placed on
  disk (they 404 on view) — place PDFs in `storage/processed/` matching their
  basenames or upload fresh docs to see view/download end-to-end.

### Session 8 — 2026-08-10 (Phase F1 — seeded doc View 404 + stale SESSION notes)

**Done:**
- **Seeded doc View fixed:** `scripts/seed_db.py` now generates real PDFs
  into `storage/processed/` matching each seeded `source_path` basename
  (`draft_credit_policy.pdf`, `sample_policy.pdf`, `eligibility.pdf`) via a
  new `ensure_seed_files()` step (idempotent — skips existing files). Ran it
  against the live DB; all three seeded docs (448/449/450) now resolve via
  `resolve_stored_file` and the admin `/documents/{id}/file` endpoint returns
  **200** (was 404).
- **Stale analytics notes fixed:** the carry-over notes claiming the admin
  Analytics tab has "no charts yet" were outdated — the `/admin` Analytics tab
  already renders charts. Marked each as resolved in the Session 4/5/6/7 log
  entries.
- **Orphaned demo rows noted:** docs 444–447 (client-uploaded demo docs from a
  prior session) have empty `source_path` and no files on disk — View will
  still 404 for them. Flagged; not in seed scope.

**Phase F2 — Admin Dashboard + Settings (same session):**
- **`GET /admin/summary`:** new endpoint in `api/v1/admin.py` returning 7
  admin-only aggregate counts (pending approvals, total documents, users,
  clients, active cases, knowledge gaps, pending SOP access requests).
- **Frontend:** admin `Dashboard` + `Settings` nav items enabled; new
  `DashboardTab` (stat-card grid with refresh) and `SettingsTab` (browser-local
  prefs: default landing tab + audit-banner toggle) in `app/admin/page.tsx`;
  `getAdminSummary` client added. Default landing tab now honors the saved pref.
- **Tests:** `tests/unit/test_admin_summary.py` (5 tests) — route wiring, 401,
  client 403, payload counts, null-count → 0. Full suite: **320 passed**.
- **Live verified:** rebuilt `asto-backend` + `frontend`; `/admin/summary`
  returns live counts; admin page 200 and its compiled chunk references the new
  components.

**Phase F3 — Admin governance views (same session):**
- **Design decision (user):** Roles & Permissions / Departments are
  **config-driven** — `app/auth/roles_config.py` is the single source of truth
  for roles, their department access, the role hierarchy, and the departments
  list (Python data, not YAML, to avoid a new dependency). Enforcement stays in
  `rbac.py`/`permissions.py`; the admin view is read-only for now.
- **Endpoints** in `api/v1/admin.py`: `GET /admin/documents/{id}/chunks`
  (read-only KB browse), `GET /admin/sops` (admin read-all SOPs), and
  `GET /admin/governance` (config-driven roles + departments).
- **Frontend:** admin `Knowledge`, `SOPs`, `Roles`, `Departments` nav items
  enabled; new `KnowledgeBaseTab` (document picker + chunk list),
  `SopManagementTab` (SOP list + access-request approve/reject), and
  `GovernanceTab` (read-only roles/departments, shared by Roles + Departments).
- **Tests:** `tests/unit/test_admin_governance.py` (9 tests) — route wiring,
  401, client 403, chunk payload + 404, SOP payload, governance config.
  Full suite: **329 passed**.
- **Live verified:** all three endpoints return correct data against the live
  DB; admin page 200 with the new components in its compiled chunk.

**Phase F4 — Staff operational views (same session):**
- **New `/staff` page** (`app/staff/page.tsx`) — four tabs all wired to the
  existing backend (no backend change): Dashboard (stat cards + recent
  workflows from `/staff/dashboard`), My Cases (case cards + case-notes
  view/add via `/staff/cases/{id}/notes`), Workflows (advance stage via
  `/staff/workflows/{id}/advance`), SOPs (list + create for approved authors +
  access-request submit + own requests list).
- **Login routing:** non-admin staff now route to `/staff` (was `/` chat page).
- **Nav:** staff Dashboard / My Cases / Workflows / SOPs enabled; Tasks and
  Collaboration stay disabled.
- **Live verified:** `/staff` serves 200 with the new components in its chunk;
  `/staff/dashboard` returns live cases + workflows + SOPs for `staff@asto.local`.

**Phase F5 — Staff Tasks + client Home/Help (same session):**
- **Design decision (user):** Staff Tasks are **derived from workflows** — no
  new `tasks` table. Each active (in_progress/review) workflow in the staff
  member's departments is a task with an Advance action.
- **Client Home:** new `HomeView` in `app/client/page.tsx` — overview cards
  (active case, properties, documents) from the already-loaded
  me/properties/cases/documents endpoints + a latest-update card from
  `latest_event`. Client now lands on Home after login (was chat).
- **Client Help:** new `HelpView` — static FAQ-style sections. Client Home +
  Help nav items enabled.
- **Staff Tasks:** new `TasksTab` in `app/staff/page.tsx` — open/completed
  stat cards + actionable workflows with Advance (reuses `/staff/workflows/
  {id}/advance`). Tasks nav item enabled.
- **Live verified:** `/client` and `/staff` both 200; compiled chunks reference
  the new Home/Help/Tasks components. Full backend suite still **329 passed**.

**Not done / carry to next session:**
- Remaining Phase F views (F6 messages/collaboration, F7 audit log) — next in
  build order.

### Session 9 — 2026-08-11 (Phase F6 — Messages + Collaboration)

**Design decision (user):** **Full messages system** — new `conversations` +
`messages` tables, client-scoped, case-anchored. No shared-storage message bus;
every conversation belongs to exactly one client, optionally tied to a case.
RBAC is enforced in the SQL WHERE clause (CLAUDE.md rule 1): clients only see
`conversations.client_id = their id`; staff only see conversations for clients
they are assigned to (`staff_client_assignments`); admins see all.

**Backend:**
- `db/postgres/schema.py`: two new tables — `conversations` (case_id nullable,
  client_id NOT NULL → clients ON DELETE CASCADE, subject, timestamps) and
  `messages` (conversation_id → CASCADE, sender_type CHECK staff|client,
  sender_user_id / sender_client_id, body, created_at) + 3 indexes
  (conversations by client/case, messages by conversation+time).
- `db/postgres/models.py`: `conversation_row_to_dict` + `message_row_to_dict`.
- New `api/v1/messaging.py`: shared helpers — client/staff conversation access
  checks (`_assert_conversation_access_client/staff`), SQL-scoped listers
  (`_list_conversations_client/staff`), `_list_messages` (JOINs users + clients
  for `sender_name`), `_touch_conversation` (bumps `updated_at` for sort).
- `api/v1/client.py`: `GET/POST /client/conversations`, `GET/POST
  /client/conversations/{id}/messages` — client-only, scoped by JWT client_id;
  `_assert_owns_case` gates the optional `case_id`.
- `api/v1/staff.py`: `GET/POST /staff/conversations`, `GET/POST
  /staff/conversations/{id}/messages` — staff-only; `_assert_client_visible`
  and the access helpers enforce assignment scoping (admins unrestricted).
- Tests: `tests/unit/test_messaging.py` (16 tests) — route wiring, 401, client
  403 on staff routes, staff 403 on client routes, client list SQL scopes by
  client_id, create conversation, blank-subject/body 422, ownership 404,
  staff list admin-all vs assignment-scoped SQL, message read JOINs
  `sender_name`. Full suite: **345 passed** (329 + 16).

**Frontend:**
- `lib/api-client.ts`: `Conversation`/`Message` types + `jsonOrThrow` helper +
  8 functions (client: list/create/conversation messages/send; staff: same).
- `config/navigation.tsx`: client `messages` and staff `collaboration` nav
  items enabled (were disabled).
- New `components/messages/ConversationThread.tsx`: shared two-pane thread —
  conversation list (subject + case # + client name), message bubbles
  (mine/other by `selfSenderType`, sender name on the other side, timestamps),
  auto-scroll, Enter-to-send. Used by both portals.
- Client `app/client/page.tsx`: `messages` view added to `View`/nav maps +
  header title; new `MessagesView` (conversation list, New-conversation form
  with subject + optional linked case, refresh) rendering `ConversationThread`.
- Staff `app/staff/page.tsx`: new `CollaborationTab` (conversation list,
  New-conversation form with subject + client picker + optional case filtered
  to that client) rendering `ConversationThread`; TabsList 5 → 6 columns.
- `tsc --noEmit` clean, ESLint clean on changed files.

**Live verified (rebuilt + recreated `asto-backend` + `frontend`):**
- Tables `conversations` + `messages` created on startup schema init.
- client@asto.local creates a conversation → client sends "Hi, can you review
  my docs?" → admin sees it under `/staff/conversations` → admin replies →
  client thread returns both messages with correct `sender_name`s
  ("Client User" / "Admin User").
- Cross-client read of another client's conversation → **404** (SQL scoping
  holds). Left the demo thread in place as sample data.

**Not done / carry to next session:**
- F7 Audit Log viewer (last remaining Phase F view) — `GET /admin/audit`
  (filterable: user, date range, outcome) + admin Audit Log view with
  pagination.

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

### Phase F — Remaining views: not-implemented features (added 2026-08-10)
Build order for the disabled sidebar views + carry-overs. **Audit Log is last
by design.** Existing-backend items come before new-schema items. Each phase's
DoD: endpoints tested under `backend/tests/`, docs updated, live-verified after
rebuild. ⚠️ = needs a design decision before building (stop and ask).

- [x] **F1 Foundation & carry-over fixes:** place real PDFs matching seeded
      `source_path` basenames into `storage/processed/` so admin + client
      document View works end-to-end; fix stale analytics carry-over note
      (charts already exist in `/admin` Analytics tab). *(Done Session 8 —
      seed generates PDFs into `storage/processed/`; View returns 200.)*
- [x] **F2 Admin Dashboard + Settings:** new `/admin/summary` endpoint
      (pending approvals, documents, users, clients, gaps) + admin Dashboard
      stat-card view; admin Settings view (frontend prefs). *(Done Session 8 —
      summary returns 7 counts; Dashboard + Settings tabs live.)*
- [x] **F3 Admin governance:** Knowledge Base browse (read-only
      `/admin/documents/{id}/chunks` + view); SOP Management view (reuse
      `/staff/sops` + `/admin/sop-access-requests` review, add admin read-all
      SOPs endpoint); Roles & Permissions / Departments — **config-driven**
      editor (`app/auth/roles_config.py` is the single source of truth; admin
      read-only governance view). *(Done Session 8 — decision: config over DB.)*
- [x] **F4 Staff operational views (backend exists — frontend only):**
      Dashboard (`/staff/dashboard`), My Cases (`/staff/cases/{id}/notes`),
      Workflows (`/staff/workflows/{id}/advance`), SOPs (CRUD + access
      requests). *(Done Session 8 — new `/staff` page + login routing.)*
- [x] **F5 Staff Tasks + client Home/Help:** Tasks — **derived from workflows**
      (decision: no new table — each active in_progress/review workflow is a
      task with an Advance action); client Home (overview cards from existing
      me/properties/cases/documents endpoints); client Help (static content).
      *(Done Session 8.)*
- [x] **F6 Messages + Collaboration (new schema):** ⚠️ neither exists; both
      need new tables + endpoints with RBAC scoping in the SQL WHERE clause
      (CLAUDE.md rule 1). *(Done Session 9 — user chose full messages system:
      `conversations` + `messages` tables, case-anchored; client `messages` +
      staff `collaboration` views; 16 tests; 345 total.)*
- [ ] **F7 Audit Log viewer (LAST):** new `/admin/audit` endpoint (filterable:
      user, date-range, outcome) + admin Audit Log view with pagination.
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
