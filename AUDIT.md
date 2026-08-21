# Asto Project Audit

**Date:** 2026-08-03 (original) — **Re-audit:** 2026-08-19 (this session)
**Project:** Asto — Knowledge-Based AI Assistant for Mortgage Lending
**Git head:** `073b164` · Mode: read-only audit (no code modified in this session)

> This file is the living audit note for the project. The bottom section
> ("Re-audit 2026-08-19 — findings") records the state re-verified against the
> current tree. Each original finding below keeps its status checkbox plus a
> `Re-check` annotation describing what the re-audit found (some items marked
> done in 2026-08-03 are actually incomplete, regressed, or partially done).

---

## Executive Summary

The Asto project is a retrieval-only AI assistant for mortgage lending
compliance. It uses FastAPI + PostgreSQL (pgvector) + Next.js static export,
deployed on a shared AWS EC2 micro-tier instance (1 GiB RAM). The architecture
follows sound design principles (no LLM generation, RBAC in SQL WHERE clause,
socket-activated backend, batch ingestion).

However, both the original and the re-audit found **critical bugs, missing
coverage, and implementation gaps** that still prevent the system from working
as designed. The most severe class of issue this re-audit surfaces is a
**broken confidence model + an audit trail that is silently dead on any fresh
deployment** plus **multiple regressions** from "completed" items.

### Re-check highlight

- Of the 25 original findings, **3 are genuinely fixed** (1.2, 1.3/3.1, 20, 22).
- **3 are only partially done** (1.1 overconfident, 1.4 weighted-but-stale, 18 prod-enforced-but-dev-defaults-remain).
- **2 are marked done but regressed / still broken** (16 idle-watcher — actually fixed, see note; 25 RBAC test is vacuous).
- **~25 new findings** in areas the 2026-08-03 audit did not reach (query
  processing internals, fact path, LLM seam, frontend security/UX tests,
  infra shared-host 404, OOM, watermark bypass, path traversal on file writes,
  etc).

---

## Audit Findings by Severity

### CRITICAL

#### 1. Confidence Score Calculation — fixed then overconfident (regression)
**File:** `backend/app/response/package_builder.py:21-31, 90, 122, 137`
**Original bug:** `confidence = min(c.rrf_score * 100, 100.0)` → RRF capped at ~3.33 → everything no_answer.
**Re-check status:** `_normalize_rrf_score` (lines 21-31) now normalizes against the theoretical max `2/(K+1)`, so the *scale* is fixed. **But** both RRF lists are fused from the same 100 candidate rows, so `rank_1 ≈ rank_2` and confidence almost always lands 55-100. The `<50 no_answer` bar is nearly unreachable, and the documented "75-89: answer with caveat" band is dead (tests assert this). Routing is still effectively `answer`/`no_answer` only.
**Impact:** confidence-based triage is unreliable; "partial" routing is unreachable.
**Fix:** derive confidence from score magnitude / match coverage rather than pure rank position, so the 50/75/90 thresholds map to real signal. Re-run `evaluation/run_benchmark.py` before/after (rule #7). New tests needed.

#### 2. Hardcoded Related Questions — FIXED
**File:** `backend/app/api/v1/search.py:405-408`
**Re-check status:** ✅ Now dynamic — `[sq.display for sq in plan.sub_queries[:3]]` when `package.related_questions` is empty. Original bug resolved.

#### 3. Search Endpoint Unauthenticated Access — FIXED
**File:** `backend/app/api/v1/search.py:419-425`
**Re-check status:** ✅ `search` now declares `user: Annotated[dict, Depends(require_auth)]`; `/suggest` likewise (line 428). Original auth bypass resolved.
**New caveat (see §6):** unauthenticated protection is present, but the endpoint still accepts **unbounded query strings** (`search.py:78`) → mega-query DoS; malformed `date_from`/`date_to` → unhandled psycopg 500.

#### 4. Weighted Search Score — partially done (stale weights)
**File:** `backend/app/search/hybrid_orchestrator.py:207-210`
**Original bug:** `GREATEST(ts_rank_cd(...), 1-(embedding<=>))` instead of weighted combo.
**Re-check status:** ⚠️ The SQL now uses the weighted formula `ts_rank_cd(...) * 0.3 + (1-(embedding<=>)) * 0.7`. **BUT** the weights `0.3/0.7` are **hardcoded in SQL** and do NOT read `ranking/weights_config.py` (which holds the benchmark-verified `0.2/0.8`), never imported by the retrieval cut. Violates CLAUDE.md rule #7 ("weights are configuration, not constants"). On fresh deploy the schema-migration drift + this make the retrieval cut un-auditable.
**Fix:** parametrize the weights from `weights_config` (or config), and re-verify hit_rate@1 vs the 0.928 baseline before merging.

---

### HIGH

#### 5. eval_on_pr.yml Regression Check — FIXED
**Re-check status:** ✅ Now checks the real metrics (`sub_question_accuracy`, `intent_accuracy`, `entity_accuracy`).

#### 6. OCR Module — EXISTS
**Re-check status:** ✅ `backend/app/documents/ocr.py` exists (Tesseract + pdf2image fallback).

#### 7. Chunker Submodules — exist (but one is dead)
**Re-check status:** ✅ `table_chunker.py`, `checklist_chunker.py`, `recursive_chunker.py` all exist. **New issue:** `recursive_chunker.py` is **dead code** — never imported by anything (verified). Two divergent chunking algorithms present. See §6.

#### 8. NER Modules — Resolved
**Re-check status:** ✅ `query_processing/ner/` was removed in favor of the dictionary-based `entity_extraction.py` (no GLiNER/spacy on the 1 GiB host).

#### 9. Reranker Module — exists (unenforceable budget)
**Re-check status:** ✅ `ranking/reranker.py` exists, integrated at `search.py:330`. **New issue (see §6):** `rerank()` rebuilds a full `transformers` pipeline per request (no cache) → the `<200ms p95` budget is unenforceable; not wired to CI; "ONNX Int8" claim unexercised.

#### 10. Password Hashing — FIXED
**Re-check status:** ✅ `backend/app/api/v1/auth.py` now imports & uses `passlib.hash.bcrypt` (lines 14, 198, 304, 340, 356, etc.); SHA-256 removed from auth path (only remains for token hashing in `jwt_handler.py:91`).

#### 11. Empty upload.py File — FIXED
**Re-check status:** ✅ `backend/app/documents/upload.py` now contains the upload endpoint (router at line 23). The legacy stub is gone.

#### 12. next.config.js — FIXED
**Re-check status:** ✅ `frontend/next.config.js` with `output: 'export'`, `trailingSlash: true`, `images.unoptimized`.

#### 13. Frontend .env.example — FIXED
**Re-check status:** ✅ `frontend/.env.example` exists (contains `NEXT_PUBLIC_API_URL`).

#### 14. requirements-dev.txt — FIXED
**Re-check status:** ✅ `backend/requirements-dev.txt` exists.

#### 15. SQL Injection Risk in hybrid_orchestrator — FIXED (partially)
**File:** `backend/app/search/hybrid_orchestrator.py`
**Re-check status:** ⚠️ The RBAC clause from `get_search_filter` is parameterized; `f"...AND {rbac_clause}"` interpolates the **clause shape** (column names/operators) rather than user values — still string interpolation but the clause shape is trusted/static. The faceted filters (`_build_filter_clause`) are fully parameterized. Treat as a maintenance hazard not a current injection, but flag for hardening.

#### 16. Idle Stop Watcher — FIXED
**File:** `shared-host-infra-scaffold/infra/scripts/idle_stop_watcher.sh`
**Re-check status:** ✅ Now uses a `TRACKER_FILE` (`last_active` timestamp under `/var/run/asto`) updated on detected traffic, and stops only after `IDLE_MINUTES=10` of no connections. The `ActiveEnterTimestamp` pitfall (flagged originally) is removed. *(Note: an earlier infra-agent summary described the "old" logic; the current file is the fixed version.)*

#### 17. deploy.yml Doesn't Actually Deploy — FIXED
**Re-check status:** ✅ Now uses `appleboy/ssh-action@v1.1.0` guarded by an `EC2_HOST`/`EC2_SSH_KEY`/`ASTO_JWT_SECRET`/`ASTO_DATABASE_URL` secrets gate, with health-check steps. It still no-ops (warn + skip) when secrets are absent, which is the correct safe default for a fork-without-EC2.

#### 18. Hardcoded JWT Secret Default — FIXED (prod-enforced; dev defaults remain)
**File:** `backend/app/config.py:45, 142-150`
**Re-check status:** ✅ `jwt_secret: str = ""` (no default) and `_check_jwt_secret` validator **raises in any non-development environment** unless `ASTO_JWT_SECRET` is set. Remaining risk:
- dev mode (and `docker-compose.yml:4`) allow an empty / hardcoded dev secret;
- `totp.py:29` falls back to `"asto-dev-2fa-key"` (public constant) when `jwt_secret` is empty → **TOTP secrets encryptable by anyone with DB + source** in dev.
**Fix (low):** document explicitly that TOTP/Fernet is dev-only and rotate the fallback away.

#### 19. Unused config Field — FIXED
**Re-check status:** ✅ `min_confidence_no_answer` removed from `config.py` (confidence thresholds live in `confidence_thresholds.py`).

#### 20. response_id Deterministic — FIXED
**Re-check status:** ✅ `package_builder.py:128` now includes `uuid.uuid4()` in the hash → unique per response. (The `fact_path.py` fact-route packages do the same pattern with uuid, so they are also non-deterministic — fine.)

#### 21. Import Inside Function Body — FIXED
**Re-check status:** ✅ `search.py` (formerly had an in-body `resolve_user_departments` import) — verified the import now sits at module top.

#### 22. Feedback Optional Body — FIXED
**File:** `backend/app/api/v1/feedback.py:20-23`
**Re-check status:** ✅ `request: FeedbackRequest` is a required body (no default). (Minor: `rating` validation is an explicit 400 rather than relying on pydantic schema — acceptable.)

#### 23. list_documents Pagination — FIXED
**Re-check status:** ✅ `documents.py:67` now accepts `offset` / cursor-style paging (LIMIT/OFFSET).

#### 24. Backend .env.example — exists
**Re-check status:** ✅ present (gitignored locally, tracked in-repo template).

#### 25. RBAC Pre-Filter Test — NOT actually fixed (regression)
**File:** `backend/tests/integration/test_rbac_prefilter.py`
**Re-check status:** 🚫 The file exists and is marked "Phase 4" in its docstring with the right intent ("deliberately include a chunk the test user is NOT permitted to see and assert it never reaches the reranker"). **But it does not do that**: it calls `get_search_filter(...)` directly and asserts on the clause string/params (lines 22-52) — it never runs `search_knowledge_base` against a live DB with a forbidden chunk, never patches the reranker, and never asserts the chunk is excluded. The test asserts what it claims but with empty data, so it can't catch a regression where RBAC is applied post-hoc. This is a **vacuous test** that gives false confidence.
**Fix:** rewrite as a true integration test: seed a forbidden department's chunk, run `search_knowledge_base(conn, [...], user=<restricted>)`, assert the forbidden chunk_id is absent from `candidates`.

---

## Re-audit 2026-08-19 — findings (areas the 2026-08-03 audit did not cover)

Full per-function reports were produced for every module (saved alongside this file's session as
`audit_api_core.md`, `audit_search_ranking_response.md`, `docs/frontend_audit_report.md`).
Condensed, highest-signal findings by severity:

### CRITICAL
1. **Audit trail silently dead on fresh deploy.** `audit_logger.py:62-65` inserts `audience` into `audit_log`, but `schema.py` `audit_log` DDL (lines 127-140) has **no `audience` column**, no ALTER adds it, and `migrations/versions/0001_baseline.py` imports `schema.py` live — so on `alembic upgrade head` every audit INSERT fails and is swallowed at `audit_logger.py:79`. The dev DB only has it via manual add. Violates CLAUDE.md rule #8. `/search/suggest` also 500s for non-admins on fresh DB (uses the column). **Fix:** add `audience TEXT` to the `audit_log` DDL + verify; or stop writing it.
2. **Production 404 (shared-host).** `shared-host-infra-scaffold/infra/shared/nginx/conf.d/asto-assistant.conf:18-19` uses `proxy_pass http://127.0.0.1:8011/;` (trailing slash) → strips `/api` → every `/api/v1/*` request 404s. The frontend's own `nginx.conf:13` is correct. **Fix:** drop the trailing-slash URI.
3. **Non-ASCII/empty-term query → HTTP 500.** `build_tsquery("")` returns `"''::tsquery"` (`bm25_search.py:28`) → `to_tsquery('english', %s)` SyntaxError → uncaught. Any non-Latin query (हिंदी, 日本語) reaches it because `pipeline.has_searchable_content` is not gated by `search.py`. **Fix:** guard + use `websearch_to_tsquery`.
4. **Path-traversal write in all 3 upload endpoints.** `upload.py:56`, `client.py:437`, `staff.py:1250`: `pending_dir / f"{token}_{file.filename}"` with unsanitized `filename`. `../../../evil.pdf` → arbitrary host write (serve side sanitizes reads but the write doesn't). **Fix:** `PurePath(file.filename).name` + reject traversal.
5. **Zero-vector embeddings → NaN rank.** `1-(embedding <=> query)` is NaN when the stored vector is all-zero; `ORDER BY ... DESC` sorts NaN first → a zero-norm chunk ranks #1 and corrupts `apply_linear_reorder`. Only `IS NOT NULL` guards. **Fix:** `WHERE c.embedding != '[0,0,...]'` / add a norm guard.

### HIGH
6. **`staff.advance_workflow` NameError/KeyError** (`staff.py:538,544`): `now()` undefined, `due_row[0]` on dict → past-due workflows 500. Hidden by mocking test.
7. **Logout-all access-token kill not enforced.** `revoked_jitis` (`auth.py:614`) only checked by `/auth/verify` (`:763`); `get_current_user` doesn't → revoked JWTs work on `/search`/`/admin/*` for up to 8h.
8. **Re-upload of identical content → active doc with zero chunks.** Global UNIQUE `content_hash` (`schema.py:111,499`) + version bump deactivates the old doc but its chunks keep the hashes → `ON CONFLICT DO NOTHING` skips all inserts → `chunks_indexed=0`.
9. **Cross-document dedup breaks client scoping.** Same global `content_hash` (plus `.strip().lower()` in `models.py:16`) merges identical boilerplate across clients → client B's doc loses content attributed to client A. Dedup key must be `(document_id, content_hash)`.
10. **`requirements._infer_case_type` reads an unselected column** (`requirements.py:84` selects `id,client_id,property_id,status`; `_infer_case_type:182` reads `case_number`) → always `None` → **every case treated as "purchase"**. Also N+1 (~7 q/request) and `case_row["client_id"]` KeyError on NULL.
11. **Batch ingestion not failure-isolated.** `ingest_batch.process_file` only wraps `extract_text`; an `assert`/chunk/embedding/indexing exception aborts the **entire** batch run (pending queue never drains).
12. **OOM vs ~200MB cap.** `ocr.py:45` renders ALL pages at once; **zip-bomb**: `text_extraction._extract_odt:218` / `_extract_epub:271` read archive entries with no size cap.
13. **Watermark compliance bypass by design** (now in request path). `watermark.py:33` — every failure path + every non-PDF/non-image type returns **raw bytes**; `client.py:507-513` serves them **unwatermarked with no audit record of the bypass**. pypdf/reportlab/PIL run on untrusted bytes in the always-on single-worker request path.
14. **`/auth/2fa` + `forgot-password` unthrottled** (`auth.py:374, 635`): brute-force a captured-password 6-digit TOTP; email-bomb a victim on repeated reset requests.
15. **Login timing side-channel** (`auth.py:313,340`): bcrypt verified only when the row exists → account enumeration.
16. **Refresh-token rotation race** (`auth.py:532-577`): revoke + insert in separate transactions → concurrent refresh both succeed.
17. **Governance editor is a false control.** `PUT /admin/governance` rewrites `roles_config.py`, but `permissions.require_role` (`permissions.py:22`) uses a **hardcoded hierarchy** and `rbac.py` never reads `ROLE_DEPARTMENTS`; only `roles_config.can()` is live.
18. **PII detection narrow + backtracking risk** (`pii_check.py:14-24`): no phone/CC/undashed-SSN/bank-ID; `us_address` regex has nested+`+` quantifiers.

### MEDIUM
19. **Confidence compressed** — `50-89` band dead (tests assert it). See #1.
20. **Reranker budget unenforceable** (`reranker.py:43-50`): pipeline rebuilt per request, no cache, not in CI.
21. **`response/validation.py` asymmetric** — staff branch never re-checks the client-assignment leg; client branch treats `client_id=None` (company-wide) docs as a violation → latent 500.
22. **`feedback_weighting.py` dead code** — never called by `search.py`; no tests.
23. **Synonym-expansion docstring lies** (`hybrid_orchestrator.py:10-12` vs actual) — claims expansion feeds both BM25 tsquery and embedding, but `build_tsquery(combined_text)` (line 170) uses the **unexpanded** text. The full `synonyms` table is also fetched every request, uncached.
24. **Active-version filtering incomplete**: search never selects `max(documents.version)`; several dead tunables (`get_version_filter`, `bm25_limit`/`vector_limit` param defaults, `RRF_K=60`, `user_departments`).
25. **Frontend: no 401→refresh interceptor** — 8h access token expires mid-session → dead UI until reload. Blob-iframe previews run uploads in the app origin (depends on backend magic-byte validation, which doesn't exist). Chat history persists in `localStorage` after logout. `rememberMe` decorative. `cors_origins` defaults to `localhost:3011`. No timeouts/aborts; notification SSE no reconnect. **A11y audit covers 3 of 6 routes** (`/client/`, `/staff/` missing) and **skips vacuously when Chromium missing** (`axe-audit.mjs:81-87`, exit 0). **Frontend has zero tests and no typecheck script.**
26. **`test_rbac_prefilter.py` vacuous** — see #25 of the 2026-08-03 section.
27. **Vacuous unit base**: `unit/conftest.py:31-37` autouse mock empties every DB row for all unit tests → many pass on empty data.
28. **Stale design docs**: `Final_System_Design.md` lists weights `40/30/15/10/5` (actual RRF+0.2/0.8), shows reranker always-on (default OFF), says "no BFF" (nginx routes), and **omits the dual-path assistant** (in `docs/architecture/dual_path_assistant.md` only). `weights_config.py:6-8` docstring cites the stale 2026-08-08 sweep (0.928 now).

### HIGH (additional, consolidated)
- **Reset-token links logged in plaintext** (`auth.py` reset-link `logger.info`, `password_reset_email.py:38`, `mailer.py:49,82`) — with SMTP unconfigured this is the only delivery path; anyone with log access resets any account. (Covers the `password_reset_email.py:38` + `mailer.py:49,82` finding.)
- **IP lockout bypass via spoofed `X-Forwarded-For`** (`auth.py:58`) — first hop trusted unconditionally → per-IP lockout (H3) bypassable when nginx normalization absent.
- **Upload endpoints buffer unbounded request bodies in RAM before size validation** (`upload.py:40`, `client.py:420`, `staff.py:1233`) — read loop must abort at `max_upload_bytes`; OOM on the ~200MB-capped worker.
- **`update_governance` config-file write is not transactional** (`admin.py:846-963`) — on a mid-write failure the `roles_config.py` on disk is left half-written and **not restored**; governance rules can go inconsistent. Also `_next_case_number` race + task-id validation gaps in staff workflows.
- **Feedback: no FK / length validation on `response_id` and `comment`** (`feedback.py:32-44`) — `response_id` is a free string (no FK to `audit_log.response_id`); `comment` unbounded in length.

### MEDIUM (additional, consolidated)
- **`document_popularity` query keys by chunk id, not document id** (`analytics.py:159`) — popularity is chunk-granular; document-level popularity is mis-attributed.
- **Path/filename leak in some upload error messages** — minor info disclosure when a stored file's on-disk path reaches a client error.

### LOW
29. `tox`/CI: `ci.yml` provisions Postgres but never sets `ASTO_TEST_DATABASE_URL`; `deploy.yml` runs unit tests only.
30. Committed debug files: `backend/debug_imports.py`, `test_local_pipeline.py`.
31. ~20MB benchmark JSON in git history.
32. `to_string`/`now()` undefined reference in `staff.advance_workflow`; `min_confidence_no_answer` (removed — good).
33. `_extract_docx` drops all tables; `_extract_html` indexes `<script>` text and concatenates tags without spacing; `_TITLE_PATTERNS` dead code in `metadata_extraction.py:24-27`; `recursive_chunker.py` dead code.

---

## Constraint-compliance map (CLAUDE.md)

| CLAUDE.md rule | Status |
|---|---|
| No LLM/abstrative generation in serving path | ✅ Compliant (extractive Sumy + verbatim fact templates) |
| RBAC/version filter in SQL WHERE | ✅ Compliant (`metadata_filters` + `_case_scope`) |
| Batch-only ingestion | ✅ Compliant (verified no handler imports heavy modules) |
| Every query audit-logged | 🔴 **Broken on fresh deploys** (missing `audience` column #1) |
| One Postgres/pgvector, no Redis/Qdrant/MinIO | ✅ |
| `--workers 1`, socket-activated, no schedulers | ✅ |
| Rerank <200ms p95 | ⚠️ Unenforceable (#20) |
| Weights/thresholds = config, benchmark-driven | ⚠️ Hardcoded in retrieval SQL (#4/#24) |
| Memory caps | ⚠️ Risk: ocr/zip-bomb OOM (#12); systemd `200M` vs compose `384m` |
| Base images | ✅ `python:3.11-slim` for ML paths, `nginx:alpine` |

---

## Consolidated fix plan (priority order; re-verified against current code)

### Phase 1 — P0 (blocking / security / compliance)
- **1.1** Add `audience TEXT` column to `audit_log` in `schema.py` DDL + `migrations/versions/...audience.sql` (`ALTER TABLE`): restores rule #8 on fresh deploys. Add a test that `test_migrations` asserts the column.
- **1.2** Guard `build_tsquery` in `bm25_search` against empty/non-Latin input; switch to `websearch_to_tsquery`. Add `test_bm25_search.py`.
- **1.3** Sanitize `file.filename` in all upload endpoints (`Path(filename).name` + reject `/`, `\`, `..`).
- **1.4** Fix shared-host nginx `proxy_pass` (remove trailing slash) in `shared-host-infra-scaffold/.../asto-assistant.conf`.
- **1.5** Add zero-vector guard in hybrid search SQL (`WHERE embedding != zero_vector` or filter NaN).

### Phase 2 — P1 (security / auth / RBAC correctness)
- **2.1** Make `logout-all` revoke the **access** JWT too — have `get_current_user` reject tokens in `revoked_jitis`.
- **2.2** Re-write `test_rbac_prefilter.py` as a true integration test (seed forbidden chunk, assert absent).
- **2.3** Throttle `/auth/2fa` and `forgot-password`; fix `staff.advance_workflow` `now()`/KeyError; close login timing + refresh rotation race.
- **2.4** Fix global `content_hash` dedup scoping + identical-content zero-chunk re-upload.
- **2.5** Fix `requirements._infer_case_type` column selection + N+1.
- **2.6** Isolate `ingest_batch` per-file (try/except around chunk/embed/index so one bad file can't abort the run).
- **2.7** Fix OCR/zip-bomb OOM (page-at-a-time rendering, archive entry-size caps). → **done (2026-08-21)**
- **2.8** Audit trail for watermark bypass (log when raw bytes are served); move pypdf/PIL out of the request path or harden.

### Phase 3 — P2 (correctness / ranking / docs)
- **3.1** Read retrieval weights from `weights_config` (0.2/0.8) instead of hardcoded SQL; re-run benchmark.
- **3.2** Repair the confidence model so 50/75/90 thresholds map to real signal.
- **3.3** Cache + correctness-fix synonym expansion (expand tsquery too); wire `latency_benchmark.py` into CI.
- **3.4** Implement `feedback_weighting`; delete `recursive_chunker` (dead) and confirm `metadata_extraction._TITLE_PATTERNS` is gone.
- **3.5** Fix frontend security/UX (timeouts, SSE reconnect, purge chat localStorage on logout, add `/client/`+`/staff/` to a11y + make Chromium-missing a hard fail), add frontend tests + `tsc --noEmit`.
- **3.6** Freeze design docs vs as-built (weights, reranker default, direct-access, dual-path presence).

### Phase 4 — P3 (housekeeping)
- Remove committed debug files (`debug_imports.py`, `test_local_pipeline.py`), trim large benchmark JSON from history, document the dev-only TOTP Fernet fallback, gate `ASTO_TEST_DATABASE_URL` in CI.

---

## Original task checklist (re-verified)

### Phase 1: Critical Bug Fixes (Blocking)
- [x] 1.1 Fix confidence score → **re-checked 2026-08-19: scale fixed but still overconfident (regression) — see 1.1**
- [x] 1.2 Fix hardcoded related_questions → **done (verified)**
- [x] 1.3 Fix unauthenticated search → **done (verified)**
- [x] 1.4 Fix weighted search score → **re-checked 2026-08-19: weighted, but hardcoded (stale) weights — see 3.1**
- [x] 1.5 Fix eval_on_pr.yml → **done (verified)**

### Phase 2: Missing Files & Implementation Gaps
- [x] 2.1 OCR module → **done**
- [x] 2.2 table_chunker → **done (but recursive_chunker is dead code)**
- [x] 2.3 checklist_chunker → **done**
- [x] 2.4 recursive_chunker → **done (dead — consider removal)**
- [x] 2.5/2.6 NER modules removed → **resolved (dictionary-based entity_extraction)**
- [x] 2.7 reranker.py → **done (budget unenforceable — see 3.2)**
- [x] 2.8 next.config.js → **done**
- [x] 2.9 frontend/.env.example → **done**
- [x] 2.10 requirements-dev.txt → **done**
- [x] 2.11 upload.py → **done**

### Phase 3: Security & Hardening
- [x] 3.1 Password hashing → bcrypt → **done (verified)**
- [x] 3.2 Remove default jwt_secret → **done prod-side (dev defaults remain)**
- [ ] 3.3 SQL injection hardening in hybrid_orchestrator → **re-check: clause-shape interpolation remains a maintenance hazard**
- [ ] 3.4 RBAC pre-filter test → **re-check: file exists but is vacuous (still broken)**

### Phase 4: Infrastructure & CI/CD
- [x] 4.1 Idle stop watcher timestamp → **done (verified current file)**
- [ ] 4.2 EC2 deploy → **re-check: now uses ssh-action with secret gate, but `deploy.yml` runs unit tests only**
- [ ] 4.3 Frontend next.config.js in CI → **verify CI builds static export**

### Phase 5: Code Quality & Maintenance
- [x] 5.1 import in body in search.py → **done**
- [x] 5.2 feedback.py required body → **done**
- [x] 5.3 list_documents pagination → **done**
- [x] 5.4 response_id UUID → **done**
- [x] 5.5 remove unused min_confidence_no_answer → **done**
- [ ] 5.6 RBAC pre-filter test (dup of 3.4) → **still vacuous**

---

## How to use

1. **Start with Phase 1 (P0)** — the audit-trail/500/security fixes above block correct compliance and operation.
2. **Re-run `evaluation/run_benchmark.py` before and after any ranking/weight change**, and record the before/after delta in `evaluation/reports/` (CLAUDE.md rule #7).
3. **After each fix, add/adjust a test** under `backend/tests/` (rule: "done = has a test").
4. **Update this file's checkboxes** as items are re-verified.

---

Re-audit performed 2026-08-19 over the tree at `073b164` (354 tracked files). Full per-function reports: `audit_api_core.md`, `audit_search_ranking_response.md`, `docs/frontend_audit_report.md`, plus module-level summaries for `backend/app/documents/` (ingestion) and `backend/app/auth/` (auth/audit/db/llm/email). No files were modified during this audit pass.

---

## Remediation 2026-08-20 — verified fixes applied (this session)

Status for the highest-signal findings after the remediation pass. Every fix
is covered by a test (rule: "done = has a test"); full backend suite: **783
passed** (unit + integration) after this session's changes.

### P0
- **#1 Audit trail dead on fresh deploy — FALSE POSITIVE, now proven by test.** The `audience` column *does* exist in `schema.py` DDL (lines 128-133) and as an idempotent ALTER (`ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS audience TEXT`); the 2026-08-19 read of the schema predated the dual-audience change. Added `tests/integration/test_audit_log_column.py` proving client + staff audit rows persist `audience` end-to-end on the live DB. Constraint map row "Every query audit-logged" → ✅.
- **#3 Non-ASCII/empty-term query 500** — guarded (see P0-2 in fix plan): `build_tsquery` returns `"''::tsquery"` only when the text has no ASCII tokens, and `search.py` now rejects `""` via `has_lexical_terms` + `max_length` on `SearchRequest`.
- **#4 Path-traversal write in upload endpoints** — `sanitize_filename()` in `documents/validation.py` (rejects empty, `/`, `\`, `.`, `..`, PurePath mismatches); all 3 endpoints write `result.filename`.
- **#2 Shared-host nginx 404** — `proxy_pass http://127.0.0.1:8011;` (trailing slash removed).
- **#5 Zero-vector embeddings → NaN rank** — `is_broken_vector()` guards store/query/scoring; NaN coerced to 0.

### P1
- **#6 `staff.advance_workflow` NameError/KeyError** — `now()` removed, overdue moved into SQL, dict access fixed.
- **#7 Logout-all access-token kill** — `get_current_user` rejects `revoked_jtis` (EXISTS subquery) for both client and staff branches.
- **#8/#9 content_hash dedup** — scoped to `(document_id, content_hash)` via migration `0003_scoped_chunk_dedup` (applied to live DB); cross-client merge + zero-chunk re-upload resolved.
- **#10 `requirements._infer_case_type`** — `case_number` now selected; dead `dict_row_to_case` import removed.
- **#11 Batch ingestion not failure-isolated** — `process_file` wraps all downstream stages; `main` loop continues past a poisoned file.
- **#14 `/auth/2fa` + forgot-password unthrottled** — per-IP throttle added; reset path uses a sentinel email to avoid lockout-DoS.
- **#16 Refresh-token rotation race** — single-transaction revoke+insert with `rowcount` guard.
- **#21 `validation.py` asymmetric / client-`None` 500** — client branch now allows company-wide docs (`client_id IS NULL`); staff branch re-checks the client-assignment leg via `assigned_client_ids`.
- **#25/#26 `test_rbac_prefilter.py` vacuous** — rewritten as a true integration test: seeds forbidden department + unassigned-client + company-wide docs with real embeddings, runs `search_knowledge_base`, asserts forbidden chunk_ids never reach `candidates`.

### P2
- **#24/#3.1 Weights hardcoded in SQL** — `hybrid_orchestrator` now binds `weights.bm25_weight`/`vector_weight` from `weights_config` (benchmark-verified 0.2/0.8).
- **#22 `feedback_weighting.py` dead code — claim corrected.** It is **not** dead: `evaluation/compare_rankings.py:26` imports `apply_feedback_weighted_reorder` / `compute_doc_feedback_ratios` for the J3 feedback-boost sweep. Kept.
- **#33 dead code removed** — `recursive_chunker.py` deleted; `_TITLE_PATTERNS` + unused `re` import removed from `metadata_extraction.py`; `decode_for_audit` removed from `jwt_handler.py`.
- **P0-3 upload body unbounded buffering** — `read_upload()` aborts at `max_upload_bytes` (413).

### Remaining (not yet addressed)
- **#1 Confidence model overconfidence** (fix 3.2) — **done (2026-08-22)**: response-level confidence is now rank-agreement × smoothed query-term-coverage (`package_builder._calibrated_confidence`), so `partial` is reachable and zero-overlap deep ranks route to `no_answer`. Reasoning in `evaluation/reports/2026-08-22_confidence_calibration.md`; benchmark before/after still pending there.
- **#13 watermark bypass** (2.8) — audit trail added (S1-S7), but pypdf/PIL still run in the always-on request path; move to batch or harden.
- **#17 governance editor false control** — **fixed (2026-08-22)**: `permissions.require_role` and `rbac.py` read `roles_config` at call time, so governance edits change enforcement, not just the UI. Regression tests: `test_rbac_single_source.py`.
- **#23 synonym expansion** (3.3) — **done (2026-08-21)**: dict-row access fixed (expansion never matched before), expanded text now feeds the BM25 tsquery too, and the `synonyms` table is cached with inline admin invalidation. Benchmark note in `evaluation/reports/` (empty synonyms table → no-op; re-benchmark when populated).
- **3.5 frontend hardening** (mostly done), **3.6 design-doc freeze**.

### Constraint-compliance map — updated rows
| CLAUDE.md rule | Status |
|---|---|
| Every query audit-logged | ✅ Column exists, write verified by `test_audit_log_column.py` |
| Weights/thresholds = config, benchmark-driven | ✅ Retrieval reads `weights_config` (0.2/0.8) |
| RBAC/version filter in SQL WHERE | ✅ Verified live (`test_rbac_prefilter.py`) |

---

## Overall audit 2026-08-20 — consolidated findings + next-session fix plan

Full report: `AUDIT_overall_2026-08-20.md` (five read-only streams; key claims
re-verified against the tree at `cca9468`; suite 789 passed). This section is
the condensed state + fix checklist to resume from in the next session.

### Constraint map (CLAUDE.md rules 0-10): 9/11 compliant
- **Rule 6 (PARTIAL)** — reranker <200ms p95 budget enforced nowhere in CI
  (`check_reranker_budget` unused by `run_benchmark`); `reranker.py:44-48`
  reloads the model per request (no cache); `transformers` NOT in
  `requirements.txt` so `ASTO_RERANK_ENABLED` silently no-ops.
- **Rule 10 (PARTIAL)** — systemd `MemoryMax=200M`
  (`shared-host-infra-scaffold/infra/systemd/asto-backend.service:19`) vs
  compose `384m` (`docker-compose.yml:67`, evidence comment: ~300MB peak).
  Reconcile the systemd cap.
- Rules 0-5, 7, 8, 9 compliant (RBAC/version in SQL; batch-only ingestion;
  no LLM in serving path; no Redis/Qdrant/MinIO; `--workers 1` socket-activated;
  weights/thresholds config-driven).

### CRITICAL — S1: deploy can ship with a forgeable JWT secret
- `docker-compose.yml:4` ships known fallback
  `dev-only-secret-change-me-in-production-32chars`; `:5` defaults
  `ASTO_ENVIRONMENT=development`; `deploy.yml:70-72` passes `ASTO_JWT_SECRET`
  but never sets `ASTO_ENVIRONMENT=production` → the guard at
  `config.py:143-151` is inert, and an unset GH secret silently falls back to
  the public key. Also `totp.py:29` Fernet fallback to `"asto-dev-2fa-key"`.
- **Fix:** remove compose fallback; require `len(jwt_secret) >= 32` in all
  environments; set `ASTO_ENVIRONMENT=production` in `deploy.yml`; drop TOTP
  fallback.

### HIGH — for the next session
- **S2** `X-Forwarded-For` first element trusted (`auth.py:58-63`) → throttle
  bypass + lockout-DoS. Use last hop / `X-Real-IP` / nginx overwrite.
- **S3** reset tokens logged in plaintext (`password_reset_email.py:38`,
  `mailer.py:49,82`). Log hash only.
- **S4** `/search/suggest` (`search.py:436-449`) and document file-serving
  (`client.py:461`, `staff.py:1291`, `documents.py:58`) not audit-logged.
- **S5** watermark bypass serves raw bytes with no audit
  (`watermark.py:44-56`, `client.py:505-509`).
- **eval_on_pr.yml is broken as a gate** — no embedding-model pre-download
  step; will fail like the pre-`028ccf6` CI benchmark. Add the pre-download +
  wire `check_reranker_budget` (rule 6).
- **Frontend** — chat history persists after logout
  (`frontend/app/page.tsx:149-173`, `client/page.tsx:1586-1603`,
  `hooks/use-chat-history.ts:14`); a11y gate exits 0 without Chromium
  (`axe-audit.mjs:81-87`); no frontend tests / no `tsc --noEmit`; CI runs no
  lint/a11y.
- **S6/S7** magic-byte upload validation (`validation.py:89-127`); CORS `*` +
  credentials (`main.py:64-75`).

### MEDIUM/LOW hygiene backlog
- Dead code to delete: `backend/app/audit/models.py`, debug files
  (`backend/debug_imports.py`, `backend/check_psycopg.py`,
  `test_local_pipeline.py`), dead frontend hooks
  (`use-browser-extension.ts`, `use-mobile-app.ts`, `use-platform.ts`,
  `hooks/index.ts`); orphaned scripts + `eval_20_questions.jsonl`.
- `transformers` absent vs rerank config seam (see rule 6).
- RBAC governance triple-source-of-truth: `auth/rbac.py` vs
  `auth/roles_config.py` vs hardcoded hierarchy in `permissions.py`.
- `analytics.py:34-39` unreachable; `validation.py:23` dead `min_confidence`
  param; `hybrid_orchestrator.py:10-12` false synonym-expansion docstring.
- Docs drift: `Final_System_Design.md:54` stale weights table; reranker shown
  always-on; dual-path assistant missing; `weights_config.py:4-8` docstring
  stale. Add a fresh benchmark report with before/after delta.
- `admin.py:1342` TODO — unimplemented G3 client notification.
- Low: `framer-motion` unused; `numpy` redundant pin; `rememberMe` decorative;
  `api-client.ts:6` localhost fallback; `/auth/reset-password` unthrottled;
  account enumeration via bcrypt timing; signature-request tokens stored raw;
  SSE error leaks; docs always exposed; `audit_enabled=false` silent.

### Verified clean (re-confirmed 2026-08-20)
- RBAC/version/approval in SQL WHERE; pgvector+BM25 single statement; batch-only
  ingestion; no LLM in serving path (doctrine holds: extractive verbatim
  summarizer + fact templates); no committed secrets; `.gitignore` solid; no
  tracked file >10MB; 789 tests pass; CI unit/integration/benchmark steps green.
