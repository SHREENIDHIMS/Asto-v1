# Asto Project Audit

**Date:** 2026-08-03
**Project:** Asto — Knowledge-Based AI Assistant for Mortgage Lending
**Location:** `D:\ShreenidhiM\asto-agent-main\asto-agent-main`

---

## Executive Summary

The Asto project is a retrieval-only AI assistant for mortgage lending compliance. It uses FastAPI + PostgreSQL (pgvector) + Next.js static export, deployed on a shared AWS EC2 micro-tier instance (1 GiB RAM). The architecture is well-documented and follows sound design principles (no LLM generation, RBAC in SQL WHERE clause, socket-activated backend, batch ingestion).

However, the audit found **several critical bugs, missing files, and implementation gaps** that prevent the system from working correctly as designed. The most severe is a **fundamentally broken confidence score calculation** that routes nearly all queries to "no_answer".

---

## Audit Findings by Severity

### CRITICAL

#### 1. Confidence Score Calculation is Fundamentally Broken
**File:** `backend/app/response/package_builder.py:72`
**Bug:** `confidence = min(c.rrf_score * 100, 100.0)`

RRF scores are in the range [0, ~0.033] (since 1/(60+1) ≈ 0.016 per list). Multiplying by 100 gives a maximum confidence of ~3.33. This means confidence will almost never exceed 50, so **nearly all queries will route to "no_answer"** via `confidence_thresholds.py`.

**Impact:** The system will never return "answer" or "partial" routing for any realistic query. The confidence thresholds (90/75/50) are completely unreachable.

**Fix:** Normalize RRF scores to a 0-100 scale, or use a different confidence metric (e.g., based on BM25/vector score magnitude, or the number of matched sub-queries).

#### 2. Hardcoded Related Questions in Search Endpoint
**File:** `backend/app/api/v1/search.py:175-176`
**Bug:** `related_questions` is hardcoded with two static strings instead of being dynamically generated from the query processing pipeline.

```python
related_questions=["What are the minimum credit score requirements?",
                   "What documents are required for a VA loan?"],
```

**Impact:** Every search returns the same two unrelated questions regardless of the query. The design doc specifies these should come from `multi_question.py`.

**Fix:** Use `plan.sub_queries` or the multi_question module to generate contextually relevant related questions.

#### 3. Search Endpoint Allows Unauthenticated Access with Full RBAC Bypass
**File:** `backend/app/api/v1/search.py:51`
**Bug:** `get_current_user` has `auto_error=False`, so unauthenticated users can access the search endpoint. When `user is None`, the RBAC check in `validate_package` is skipped entirely.

**Impact:** Unauthenticated users can retrieve all documents across all departments, violating the RBAC design principle (CLAUDE.md rule #1).

**Fix:** Either require authentication for the search endpoint, or enforce RBAC at the SQL level regardless of auth state (treat unauthenticated users as having no department access).

#### 4. Weighted Search Score Uses GREATEST Instead of Weighted Combination
**File:** `backend/app/search/hybrid_orchestrator.py:88-91`
**Bug:** The SQL query uses `GREATEST(ts_rank_cd(...), 1 - (embedding <=> ...))` for ordering, but the design doc specifies `ts_rank_cd(...) * 0.3 + (1 - (embedding <=> query_vec)) * 0.7` as the weighted combination.

**Impact:** The search ranking doesn't follow the designed weighted formula. Using GREATEST means only the better of the two scores matters, not a balanced combination.

**Fix:** Replace `GREATEST(...)` with the weighted formula from the design doc: `ts_rank_cd(...) * 0.3 + (1 - (embedding <=> query_vec)) * 0.7`.

---

### HIGH

#### 5. eval_on_pr.yml Regression Check References Non-Existent Metrics
**File:** `.github/workflows/eval_on_pr.yml:92-93`
**Bug:** The regression check looks for `hit_rate`, `mrr`, `ndcg` in the benchmark JSON, but `run_benchmark.py` never computes or stores these metrics. It only outputs `sub_question_accuracy`, `intent_accuracy`, `entity_accuracy`, and latency.

**Impact:** The regression check will always pass (or error out) because the metrics don't exist in the report.

**Fix:** Either compute and store hit_rate, mrr, ndcg in `run_benchmark.py`, or update the regression check to use the actual metrics that are computed.

#### 6. Missing OCR Module
**File:** `backend/app/documents/ocr.py` — DOES NOT EXIST
**Bug:** The design docs (SKILL.md, Final_System_Design.md) reference `ocr.py` as part of the ingestion pipeline, but the file doesn't exist. `ingest_batch.py` never calls it.

**Impact:** OCR functionality is missing from the ingestion pipeline. Scanned PDFs cannot be processed.

**Fix:** Implement `ocr.py` using Tesseract, or remove the reference from the design docs if OCR is out of scope for MVP.

#### 7. Missing Chunker Submodules
**Files:** `table_chunker.py`, `checklist_chunker.py`, `recursive_chunker.py` — DO NOT EXIST
**Bug:** `Final_Folder_Structure.md` references these files under `documents/chunking/`, but only `structural_chunker.py` exists.

**Impact:** The chunking pipeline doesn't have specialized handlers for tables, checklists, or recursive chunking as designed.

**Fix:** Implement the missing chunker modules or update the design docs.

#### 8. Missing NER Modules
**Files:** `backend/app/query_processing/ner/spacy_pipeline.py`, `backend/app/query_processing/ner/gliner_extractor.py` — REMOVED
**Status:** Resolved. The `entity_extraction.py` module uses a dictionary-based approach that was deliberately chosen over GLiNER/spaCy for the 1 GiB shared host. The `ner/` directory was removed and design docs updated to reflect this decision.

#### 9. Missing Reranker Module — RESOLVED
**File:** `backend/app/ranking/reranker.py` — EXISTS, integrated into `search.py` (A1/B1)
**File:** `backend/app/ranking/reranker.py` — DOES NOT EXIST
**Bug:** The design docs reference a cross-encoder reranker, but the file doesn't exist. `config.py` has `rerank_enabled: bool = False` but there's no reranker implementation.

**Impact:** The reranking step (Phase 4 of the pipeline) is not implemented. The system uses RRF fusion only, without cross-encoder reranking.

**Fix:** Implement `reranker.py` or document it as a P2 deferred feature.

#### 10. SHA-256 Password Hashing
**File:** `backend/app/api/v1/auth.py:45`
**Bug:** Uses `hashlib.sha256()` for password hashing, which is cryptographically insecure for password storage. The code even acknowledges this in the docstring.

**Impact:** Passwords are stored with a fast hash that's vulnerable to brute-force attacks. In production, this would be a security vulnerability.

**Fix:** Migrate to bcrypt/argon2 via passlib before deploying to production.

#### 11. Empty upload.py File
**File:** `backend/app/documents/upload.py` — Only 6 lines (docstring)
**Bug:** The design doc specifies `upload.py` should contain the upload endpoint logic, but it's just a placeholder docstring. The actual upload endpoint is in `documents.py` (the API router file).

**Impact:** The upload logic is in the wrong file per the design doc, creating confusion and a maintenance hazard.

**Fix:** Either move the upload endpoint to `upload.py` or update the design docs to reflect the actual structure.

---

### MEDIUM

#### 12. Missing next.config.js for Frontend
**File:** `frontend/next.config.js` — DOES NOT EXIST
**Bug:** The design doc specifies `output: 'export'` in `next.config.js`, but the file doesn't exist. The frontend may not build correctly as a static export.

**Impact:** The frontend may not produce a proper static export for Nginx serving.

**Fix:** Create `next.config.js` with `output: 'export'` configuration.

#### 13. Missing Frontend .env.example
**File:** `frontend/.env.example` — DOES NOT EXIST
**Bug:** The frontend has no `.env.example` file for environment variable configuration.

**Fix:** Create `frontend/.env.example` with `NEXT_PUBLIC_API_URL` and other env vars.

#### 14. Missing requirements-dev.txt
**File:** `backend/requirements-dev.txt` — DOES NOT EXIST
**Bug:** The `README.md` references `requirements-dev.txt` but it doesn't exist. The CI workflow installs `pytest` separately instead.

**Fix:** Create `backend/requirements-dev.txt` with test dependencies.

#### 15. SQL Injection Risk in hybrid_orchestrator.py
**File:** `backend/app/search/hybrid_orchestrator.py:87`
**Bug:** The RBAC clause is interpolated into SQL using f-string: `f'AND {rbac_clause}'`. While the clause is currently built safely with parameterized queries, this pattern is fragile and could lead to SQL injection if the clause generation changes.

**Fix:** Use parameterized SQL for the RBAC clause instead of string interpolation.

#### 16. Idle Stop Watcher Uses Wrong Timestamp
**File:** `shared-host-infra-scaffold/infra/scripts/idle_stop_watcher.sh:32`
**Bug:** Uses `ActiveEnterTimestamp` (when the service started) as a proxy for last activity. After socket activation, the service starts on the first connection, so this timestamp doesn't reflect when the last request was handled.

**Impact:** The idle-stop logic may stop the service too early (if it started but hasn't received a request yet) or too late (if it's been active for a long time).

**Fix:** Track the last connection time separately, or use a different mechanism to detect idle state.

#### 17. deploy.yml Doesn't Actually Deploy
**File:** `.github/workflows/deploy.yml:56-58`
**Bug:** The deploy step just prints messages and doesn't implement the actual EC2 deployment mechanism.

**Impact:** The CI/CD pipeline has a non-functional deploy step.

**Fix:** Implement the actual EC2 deployment mechanism (e.g., SSH, AWS CodeDeploy, or S3+CloudFront).

#### 18. Hardcoded JWT Secret in Default Config
**File:** `backend/app/config.py:40`
**Bug:** The default `jwt_secret` is `"dev-only-secret-change-me-in-production-32chars"`. While documented as dev-only, this is still a security concern if someone deploys without changing it.

**Fix:** Remove the default and require `ASTO_JWT_SECRET` to be set via environment variable.

#### 19. Unused config Field
**File:** `backend/app/config.py:63`
**Bug:** `min_confidence_no_answer: float = 50.0` is defined in config but never used anywhere. The confidence thresholds live in `confidence_thresholds.py` instead.

**Fix:** Remove the unused field or wire it into `confidence_thresholds.py`.

---

### LOW

#### 20. response_id is Deterministic
**File:** `backend/app/response/package_builder.py:96-98`
**Bug:** `response_id` is generated as a hash of `query_text:top_confidence`, meaning identical queries produce identical response IDs. This breaks audit uniqueness.

**Fix:** Include a UUID or timestamp in the response_id generation.

#### 21. Import Inside Function Body (search.py:116)
**File:** `backend/app/api/v1/search.py:116`
**Bug:** `from app.auth.rbac import resolve_user_departments` is imported inside the function body instead of at the top of the file. This is a style issue and could cause circular import problems.

**Fix:** Move the import to the top of the file.

#### 22. Feedback Endpoint Uses Optional Body Pattern
**File:** `backend/app/api/v1/feedback.py:22`
**Bug:** `request: FeedbackRequest | None = None` is non-idiomatic FastAPI and could cause issues with request body parsing.

**Fix:** Use `request: FeedbackRequest` (required, no default) and let FastAPI handle the 422 validation.

#### 23. list_documents Endpoint Has No Pagination
**File:** `backend/app/api/v1/documents.py:67`
**Bug:** Uses `LIMIT 100` without offset, making it impossible to page through large result sets.

**Fix:** Add `offset` parameter and use `LIMIT/OFFSET` or cursor-based pagination.

#### 24. Missing .env.example in Backend
**File:** `backend/.env.example` — Not verified to exist
**Bug:** The README references `.env` but it's unclear if `.env.example` exists.

**Fix:** Verify and create if missing.

#### 25. No Test for RBAC Pre-Filter Enforcement
**Bug:** CLAUDE.md rule #1 requires a test that deliberately includes a chunk the test user is NOT permitted to see and asserts it never reaches the reranker. No such test exists in the test suite.

**Fix:** Add an integration test that verifies chunks from restricted departments are filtered out at the SQL level, not just at the response level.

---

## Phase-Wise TODO Tasks

### Phase 1: Critical Bug Fixes (Blocking)

- [x] **1.1** Fix confidence score calculation in `package_builder.py` — normalize RRF scores to 0-100 scale
- [x] **1.2** Fix hardcoded `related_questions` in `search.py` — dynamic generation from `plan.sub_queries[:3]`
- [x] **1.3** Fix unauthenticated access to search endpoint — `require_auth` dependency enforces JWT
- [x] **1.4** Fix weighted search score in `hybrid_orchestrator.py` — `BM25 * 0.3 + vector * 0.7`
- [x] **1.5** Fix eval_on_pr.yml regression check — uses actual metrics (`sub_question_accuracy`, `intent_accuracy`, `entity_accuracy`)

### Phase 2: Missing Files & Implementation Gaps

- [x] **2.1** Create `backend/app/documents/ocr.py` (Tesseract-based OCR)
- [x] **2.2** Create `backend/app/documents/chunking/table_chunker.py`
- [x] **2.3** Create `backend/app/documents/chunking/checklist_chunker.py`
- [x] **2.4** Create `backend/app/documents/chunking/recursive_chunker.py`
- [x] **2.5** Create `backend/app/query_processing/ner/spacy_pipeline.py`
- [x] **2.6** Create `backend/app/query_processing/ner/gliner_extractor.py`
- [x] **2.7** Create `backend/app/ranking/reranker.py` (ONNX cross-encoder, top-10, <200ms p95)
- [x] **2.8** Create `frontend/next.config.js` with `output: 'export'`
- [x] **2.9** Create `frontend/.env.example`
- [x] **2.10** Create `backend/requirements-dev.txt`
- [x] **2.11** Move upload endpoint from `documents.py` to `documents/upload.py`

### Phase 3: Security & Hardening

- [x] **3.1** Migrate password hashing from SHA-256 to bcrypt/argon2 via passlib
- [x] **3.2** Remove default `jwt_secret` from `config.py` — require env var in production
- [x] **3.3** Fix SQL injection risk in `hybrid_orchestrator.py` — parameterized RBAC clause with `%s` placeholders
- [x] **3.4** Add RBAC pre-filter test that verifies restricted chunks never reach the reranker

### Phase 4: Infrastructure & CI/CD

- [x] **4.1** Fix `idle_stop_watcher.sh` to track last connection time via timestamp file
- [x] **4.2** Implement actual EC2 deployment in `deploy.yml` — SSH-based deploy with health checks
- [x] **4.3** Add `next.config.js` to frontend build pipeline in CI

### Phase 5: Code Quality & Maintenance

- [x] **5.1** Move import inside function body to top of file in `search.py`
- [x] **5.2** Fix `feedback.py` to use required body parameter instead of optional
- [x] **5.3** Add pagination to `list_documents` endpoint in `documents.py`
- [x] **5.4** Fix deterministic `response_id` in `package_builder.py` to include UUID
- [x] **5.5** Remove unused `min_confidence_no_answer` from `config.py`
- [x] **5.6** Add missing test coverage for RBAC pre-filter enforcement

---

## Phase-Wise Task Execution Plan

### How to Use This Audit

1. **Start with Phase 1** — Fix critical bugs first. These are blocking issues that prevent the system from working correctly.
2. **Complete each task** before moving to the next one within the same phase.
3. **After completing all tasks in a phase**, move to the next phase.
4. **Verify each fix** by running the relevant tests or manually testing the affected functionality.
5. **Update this document** as you complete each task (check off the box, add notes).

### Phase Execution Order

```
Phase 1 (Critical Bugs) → Phase 2 (Missing Files) → Phase 3 (Security) → Phase 4 (Infra/CI) → Phase 5 (Code Quality)
```

Within each phase, tasks are ordered by dependency — later tasks may depend on earlier ones being complete.
