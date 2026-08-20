# Asto — Overall Audit 2026-08-20

**Date:** 2026-08-20 · **Mode:** read-only (no files modified)
**Git head:** `cca9468` · **Suite at time of audit:** 789 passed (unit + integration)
**Method:** five parallel streams — (A) CLAUDE.md constraints 0-10, (B) security,
(C) "find, don't generate" doctrine, (D) code health/tech debt, (E) tests, CI/CD,
benchmark evidence, docs-vs-as-built. Key claims re-verified directly against the
tree by the auditor before writing this report.

---

## 1. Executive summary

The architecture is sound and, for the most part, compliant: RBAC/version
filtering lives in SQL, ingestion is batch-only, no LLM reaches the serving
path, no Redis/Qdrant/MinIO, single-worker socket-activated backend, weights and
confidence thresholds are config-driven, and every search is audit-logged.

The highest-priority problems are **deployment/secret hygiene**, **a CI gate
(eval_on_pr.yml) that cannot run**, and **long-known security/UX items that remain
unfixed**. There is exactly **one CRITICAL** cluster (forgeable JWTs on an
improperly-configured deploy), several HIGHs, and a long tail of MEDIUM/LOW
hygiene items, many already catalogued in `AUDIT.md` and still open.

Constraint map: **9/11 compliant, 2 partial** (rule 6 reranker budget, rule 10
memory caps). The two partials are small, well-scoped fixes.

---

## 2. Constraint-compliance map (CLAUDE.md)

| # | Rule | Verdict | Evidence / gap |
|---|---|---|---|
| 0 | Confidence routing = response-time decision, not validation gate | ✅ | `validation.py:20-41` explicitly never checks confidence; `min_confidence` param is unused; low-confidence passes (`test_response.py:104-136`) |
| 1 | RBAC + active-version filter in SQL WHERE at query time | ✅ | `metadata_filters.py:38-97`; `hybrid_orchestrator.py:185-199`; `suggest.py:81-94`; `fact_resolvers.py:76-95`. Note: `get_version_filter()` is dead code (test-only) |
| 2 | One Postgres, one DB; no Qdrant/Redis/MinIO | ✅ | Zero services/deps/imports anywhere (only docs mention removals) |
| 3 | pgvector + BM25 in same SQL statement | ✅ | `hybrid_orchestrator.py:209-224` single SELECT, bound params |
| 4 | `--workers 1`, socket-activated, no background threads | ✅ | systemd service/socket/idle timer; no schedulers; only per-request `to_thread`/SSE loops |
| 5 | Ingestion only in batch; uploads only → `storage/pending/` | ✅ | `run_ingestion.sh:21`; `ingest_batch.main`; upload/staff/client write pending only |
| 6 | Reranker <200ms p95, `latency_benchmark.py` exists | ⚠️ **PARTIAL** | Budget not gated anywhere in CI; reranker loads model per request (`reranker.py:44-48`, no cache); `transformers` absent from requirements so it silently falls back to RRF |
| 7 | Weights/thresholds = config, benchmark-driven | ✅ | Weights bound from `weights_config` (0.2/0.8); reports exist (2026-08-15, hit_rate@1 0.928). Note: `fact_router.py:224-226,345-346` has hardcoded routing constants (outside rule's letter) |
| 8 | Every query audit-logged | ✅ (gap) | Search/fact/document paths logged. **`/search/suggest` (`search.py:436-449`) issues no audit entry**; document file-serving (`client.py:461`, `staff.py:1291`, `documents.py:58`) is not logged |
| 9 | `python:3.11-slim` for ML; `nginx:alpine` fine | ✅ | Backend `FROM python:3.11-slim`; frontend node/nginx alpine (no ML deps) |
| 10 | Per-service memory caps | ⚠️ **PARTIAL** | Compose backend `384m` (`docker-compose.yml:67`) vs **systemd `MemoryMax=200M`** (`asto-backend.service:19`); compose cites ~300MB peak evidence — the prod systemd cap would OOM-kill the same workload |

---

## 3. Security findings

### CRITICAL

**S1 — Deploy can silently ship with a forgeable JWT secret + inert guard.**
- `docker-compose.yml:4` — `ASTO_JWT_SECRET: "${ASTO_JWT_SECRET:-dev-only-secret-change-me-in-production-32chars}"` ships a **known public secret as fallback**; `:5` defaults `ASTO_ENVIRONMENT` to `development`.
- `config.py:30` `environment="development"` + the guard at `config.py:143-151` only rejects an empty secret in non-dev.
- `deploy.yml:70-72` passes `ASTO_JWT_SECRET`/`ASTO_DATABASE_URL` but **never sets `ASTO_ENVIRONMENT=production`**. If the GH secret is ever unset (repo without secrets configured), `secrets.ASTO_JWT_SECRET` is empty → compose fallback applies → the app boots in `development` with the **known** key → every JWT in the system is forgeable (any role, 8h). The guard cannot fire because environment is dev.
- Also `totp.py:29` `secret = (settings.jwt_secret or "asto-dev-2fa-key")` — TOTP/Fernet fallback to a public constant when the secret is empty.
- **Fix:** remove the compose fallback (fail if unset), set `ASTO_ENVIRONMENT=production` in deploy.yml, drop the TOTP fallback, and have the config validator require `len(jwt_secret) >= 32` regardless of environment.

### HIGH

**S2 — `X-Forwarded-For` first element trusted.** `auth.py:58-63` uses `forwarded.split(",")[0]`, and both nginx configs forward the header verbatim (`frontend/nginx.conf:17`, shared-host conf `:26`). Attacker sends `X-Forwarded-For: <victim-IP>` → bypasses login/2FA/reset IP throttles and enables lockout-DoS of any victim IP. Fix: use the last XFF hop / `X-Real-IP`, or have nginx overwrite the header.

**S3 — Password-reset tokens logged in plaintext.** `password_reset_email.py:38`, `mailer.py:49,82` log the full reset link (which contains the one-time token) whenever SMTP is unconfigured/fails — anyone with log access can reset any account. Fix: log recipient + token hash only.

**S4 — `/search/suggest` and all document file-serving bypass audit logging.** `search.py:436-449` queries production data with no `log_query`; `client.py:461`, `staff.py:1291`, `documents.py:58` serve documents invisibly. Violates rule #8's spirit. Fix: add `AuditLogEntry` calls.

**S5 — Watermark bypass serves raw unwatermarked bytes.** `watermark.py:44-56` returns raw bytes for every failure + every non-PDF/image type; `client.py:505-509` serves them with no audit of the bypass. Fix: block/degrade with a header banner + audit the bypass.

### MEDIUM

- **S6** — No magic-byte validation on uploads (`validation.py:89-127`); stored `.html` served inline from API origin → stored XSS risk (`client.py:506-509`). Serve non-PDF/image with safe Content-Type/attachment.
- **S7** — CORS `*` + `allow_credentials=True` (`main.py:64-75`); `backend/.env` sets `ASTO_CORS_ORIGINS=*`.
- **S8** — `/auth/reset-password` unthrottled (`auth.py:752-807`); forgot-password throttled but reset not.
- **S9** — Account enumeration via bcrypt timing (`auth.py:355,382,535`) — verify only runs when the row exists.
- **S10** — Refresh cookie `Secure` defaults false (`config.py:53`), nginx on plain `:80`.
- **S11** — Signature-request tokens stored raw + returned in list responses (`admin.py:1343,1355-1362`); store hash only.
- **S12** — SSE error event leaks raw exception text (`search.py:499-500`); validation failures return 500 with internal reason (`search.py:395-398`).
- **S13** — `audit_enabled=false` silently disables the compliance log (`audit_logger.py:55-56`); no startup warning.
- **S14** — API docs always exposed (`main.py:57-59`); disable in production.
- **S15** — Content-Disposition header built from unsanitized/unbounded title (`client.py:516`).

### LOW
- Login lockout weaponizable for account DoS (`auth.py:84`); 8h access-token lifetime (`config.py:47`); dynamic-table f-string SQL in auth (`auth.py:787,851-878`) — shape-only, not user-controlled, but harden with an allowlist.

### Verified clean (no finding)
- Refresh rotation race guarded by `rowcount` check (`auth.py:608-617`); logout-all enforced in `get_current_user` (`dependencies.py:75,109`); bcrypt everywhere; filename sanitization correct + UUID prefixes (`validation.py:29-45`); upload size capped chunk-by-chunk (`validation.py:59-78`); no committed `.env`/secrets; all endpoints carry `require_auth` + role checks; no missing-auth endpoint found.

---

## 4. "Find, don't generate" doctrine

| Area | Verdict | Notes |
|---|---|---|
| LLM seam reachability | ⚠️ **PARTIAL (documented)** | Single live call site `search.py:365 → llm/citations.py:113 → provider.py:67`, but gated off by `config.py:134 llm_enabled=false` (never true anywhere, incl. `.env.example`); unit-tested no-op when off. Sanctioned DEC-1 exception. **No structural enforcement** — a one-flag flip activates abstractive synthesis in the serving path. |
| Response packaging | ✅ | `answer` is a verbatim-summary join (`search.py:356-358`) or fact-template assembly (`fact_path.py:220-232`); `title`/excerpts are stored values; `answer` field default `""`. |
| Summarizer | ✅ | Sumy TextRank, extractive only (`summarizer.py:17-19`); verbatim verified via normalized substring + drop-on-mismatch (`:72-82,118-120`); per-sentence source metadata (`:121-128`). Minor: first-match citation ambiguity when identical sentence appears in multiple excerpts. |
| Fact path templates | ✅ | Fixed templates insert `str(value)` verbatim (`fact_path.py:135-137`); empty slots omitted; no placeholders (tested `test_fact_path.py:497-499`). |
| Query-processing pipeline | ✅ | Deterministic transforms of user's own text; only user-facing string is the constant `CLARIFY_PROMPT`. |
| Other text (suggest, notifications, emails) | ✅ | Suggestions are SQL-retrieved past queries (`suggest.py:84-100`); all templates interpolate stored values; reranker emits scores only and is off by default. |

---

## 5. Code health / tech debt

### HIGH
- **Chat history persists after logout** (`frontend/app/page.tsx:149-173`, `frontend/app/client/page.tsx:1586-1603`, `hooks/use-chat-history.ts:14`, `use-chat-sessions.ts:24-26`) — next user on a shared machine sees prior user's queries/excerpts. Cleared only by explicit "Clear" buttons. Already flagged in `docs/frontend_audit_report.md:132`.
- **A11y gate is vacuous + not wired to CI** (`frontend/scripts/axe-audit.mjs:81-87` exits 0 without Chromium; covers only `/`, `/login/`, `/admin/`; CI never runs lint or a11y).

### MEDIUM
- **`transformers` absent while `ASTO_RERANK_ENABLED` seam exists** (`requirements.txt` vs `config.py:124`, `reranker.py:36-39`) — flipping the flag silently no-ops. Remove the seam or add the dep + CI latency gate.
- **Dead module `backend/app/audit/models.py`** (zero references).
- **Committed debug files** — `backend/debug_imports.py`, `backend/check_psycopg.py`, `test_local_pipeline.py` (contains dev admin creds) — scheduled for removal in `AUDIT.md:250`, still present.
- **Dead frontend hooks cluster** — `use-browser-extension.ts`, `use-mobile-app.ts`, `use-platform.ts`, `hooks/index.ts`.
- **RBAC governance triple-source-of-truth / false control** — `auth/rbac.py` vs `auth/roles_config.py` (duplicated `ROLE_DEPARTMENTS`/`ADMIN_ROLES`/`can()`) while `permissions.py:22` uses a hardcoded hierarchy; editing `roles_config.py` via `PUT /admin/governance` doesn't change enforcement.
- **No frontend tests, no typecheck script** (`package.json:5-11`); CI builds only.

### LOW
- `analytics.py:34-39` unreachable code; `validation.py:23` dead `min_confidence` param.
- Orphaned scripts (`backfill_embeddings.py`, `seed_demo_data.py`, `check_overdue.py`, `probe_router.py`, `import_clients.py`) + orphaned `eval_20_questions.jsonl`.
- `entity_extraction.py` name collision (documents vs query_processing); `rbac.get_search_filter` test-only duplicate of `metadata_filters.get_search_filter`.
- `hybrid_orchestrator.py:10-12` docstring claims synonym expansion feeds both branches, but `build_tsquery(combined_text)` uses the unexpanded text; `synonyms` table fetched uncached every request (`:116-121`).
- `framer-motion` unused dep; `numpy==2.4.6` redundant pin; `api-client.ts:6` localhost fallback; `rememberMe` decorative (`lib/auth.ts:54-56` ignores it).
- Single backend TODO: `admin.py:1342` (unimplemented G3 client notification).

### Verified clean
- No tracked file >10MB; git history ~12MB; `.gitignore` covers `.env`, `nlp_models/`, `storage/`; no committed env/secrets; no TODO/FIXME in frontend; upload validation centralized; `recursive_chunker.py` already deleted.

---

## 6. Tests, CI/CD, benchmark, docs drift

### Tests
- **47 unit files / 698 test funcs, 15 integration files / 91 test funcs; suite green (789).**
- **Untested modules:** `feedback_weighting.py`, `ocr.py`, `file_serve.py`, admin `upload.py`, `feedback.py`, `pgvector_search.py`, several `query_processing` submodules.
- **Weak-test patterns:** unit `conftest.py:31-37` autouse mock empties all DB rows (many unit tests pass on empty data); some streaming tests assert 401 only; RLS/fact tests exist but several don't assert SQL; silent-skip risk on missing DB.

### CI/CD
- `ci.yml` — unit + integration (fresh pgvector service, schema ensured) + benchmark job: **works** (verified this session).
- **`eval_on_pr.yml` is broken as a gate: it has no embedding-model pre-download step**, but `run_benchmark` needs the model with `local_files_only=True` — it will fail exactly as the CI benchmark job did before commit `028ccf6`. Its regression check compares only `sub_question_accuracy`/`intent_accuracy`/`entity_accuracy`/`hit_rate@10` — **no latency check**.
- **Reranker <200ms p95 budget (rule 6) enforced nowhere** — `benchmark_reranker`/`check_reranker_budget` unused by `run_benchmark`; latency only measured when `rerank_enabled` (default off).
- `deploy.yml` — secret-gated, ssh-action, health checks; **migrations are covered** via `docker-entrypoint.sh:13-14` (`alembic upgrade head`) before uvicorn (agent claim to the contrary is refuted). `ASTO_ENVIRONMENT` not pinned to production (see S1).
- CI never runs frontend lint or a11y.

### Benchmark evidence
- Reports exist through **2026-08-15** (`ranking_comparison_20260815_072851.json`: 0.2/0.8 hit_rate@1 0.928). **Stale** — nothing newer than 2026-08-15 despite 08-19/20 work. Only one before/after delta doc. `compare_rankings.py` is manual-only (hardcoded Windows path) — can't run in CI.

### Docs-vs-as-built drift
- `docs/Final_System_Design.md:54` — weights table still lists the old `40/30/15/10/5` RRF-era scheme (actual: RRF + linear 0.2/0.8).
- `weights_config.py:4-8` docstring cites the stale 08-08 sweep, contradicted by the 08-15 report (0.928).
- `Final_System_Design.md` shows reranker always-on (default OFF) and omits the dual-path assistant (only in `docs/architecture/dual_path_assistant.md`).
- `Final_Tech_Stack.md` / `Final_Folder_Structure.md` still mention removed pieces (NER, recursive_chunker) in places.

---

## 7. Prioritized remediation plan

### P0 (do first)
1. **S1** — Kill the known-JWT-secret deploy path: remove compose fallback, require `len(secret) >= 32` in config regardless of environment, set `ASTO_ENVIRONMENT=production` in deploy.yml, remove TOTP Fernet fallback (`totp.py:29`).
2. **eval_on_pr.yml** — add the embedding-model pre-download step (mirror `ci.yml`) or it can never pass; optionally wire the reranker latency budget (`check_reranker_budget`) into both gates (rule 6).

### P1 (security/audit)
3. **S2** — Fix X-Forwarded-For trust (last hop / X-Real-IP).
4. **S3** — Stop logging raw reset tokens; log hash.
5. **S4/S5** — Audit-log `/suggest` and document file-serving; remove silent raw-bytes watermark bypass.
6. **S6/S7** — Magic-byte upload validation; tighten CORS (`*` + credentials).
7. Frontend logout purge of chat localStorage + sessions.

### P2 (correctness/CI/docs)
8. Reconcile systemd `MemoryMax=200M` vs compose `384m` evidence (rule 10).
9. Frontend: add `tsc --noEmit`, lint + a11y to CI; make a11y Chromium-missing a hard fail; add `/client/`+`/staff/`.
10. Freeze docs (weights, reranker default, dual-path) + refresh `weights_config.py` docstring; add a fresh benchmark report with before/after delta.
11. Dead code: delete `audit/models.py`, debug files, dead hooks; promote or document `feedback_weighting.py` as eval tooling.

### P3 (long tail)
12. Throttle reset-password; timing-safe login; signature-token hashing; docs-off-in-prod; generic error bodies on SSE/validation; trust boundary cleanup for governance editor.

---

## 8. Verified-clean summary

- RBAC/version/approval filtering enforced in SQL (`metadata_filters`, `hybrid_orchestrator`, `suggest`, fact resolvers) — rule 1.
- No LLM in serving path today; summarizer extractive + verbatim-verified; fact templates verbatim — doctrine holds.
- No Qdrant/Redis/MinIO; one shared Postgres pattern; pgvector+BM25 single-statement.
- `--workers 1` + socket activation + idle-stop; no background threads/schedulers.
- Ingestion batch-only; uploads write `storage/pending/` only.
- Weights/thresholds config-driven; benchmark evidence on file.
- No committed secrets; `.gitignore` solid; no huge tracked artifacts.
- 789 tests pass; CI unit/integration/benchmark steps verified working this session.

---

Report compiled 2026-08-20 at `cca9468` via five parallel read-only audit streams.
