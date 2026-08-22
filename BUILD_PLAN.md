# Build & Verification Plan

## Dependency Audit Summary

### Backend (Python)

| Package | Required | System Has | Status |
|---|---|---|---|
| fastapi | 0.141.1 | 0.139.2 | ⚠️ OLD |
| uvicorn | 0.52.1 | 0.51.0 | ⚠️ OLD |
| pydantic | 2.13.4 | 2.13.4 | ✅ |
| pydantic-settings | 2.14.2 | — | ❌ MISSING |
| python-dotenv | 1.2.2 | 1.2.2 | ✅ |
| psycopg[binary,pool] | 3.3.4 | 2.9.12 (psycopg2-binary) | ❌ WRONG DRIVER |
| psycopg-pool | 3.3.1 | — | ❌ MISSING |
| pgvector | 0.5.0 | 0.5.0 | ✅ |
| PyJWT | 2.13.0 | 2.9.0 | ⚠️ OLD |
| fastembed | 0.8.0 | — | ❌ MISSING |
| onnxruntime | 1.28.0 | — | ❌ MISSING |
| loguru | 0.7.3 | — | ❌ MISSING |
| RapidFuzz | 3.14.5 | — | ❌ MISSING |
| python-multipart | 0.0.32 | — | ❌ MISSING |
| numpy | 2.4.6 | 2.5.1 | ⚠️ NEWER (likely compatible) |
| passlib[bcrypt] | 1.7.4 | — | ❌ MISSING |
| pdfplumber | 0.11.6 | 0.11.10 | ⚠️ NEWER (likely compatible) |
| python-docx | 1.2.0 | 1.2.0 | ✅ |
| pytest | 8.3.4 | 9.1.1 | ⚠️ NEWER (likely compatible) |
| pytest-cov | 5.0.0 | — | ❌ MISSING |
| pytest-timeout | 2.3.1 | — | ❌ MISSING |

### Frontend (Node.js)

| Package | Required | Status |
|---|---|---|
| Node.js | >=20.0.0 | v26.5.0 ✅ |
| npm | — | Available (security policy blocks script execution) |
| package-lock.json | — | Exists ✅ |
| node_modules | — | Exists ✅ |

### Docker

| File | Status |
|---|---|
| backend/Dockerfile | ✅ Exists |
| frontend/Dockerfile | ✅ Created |
| docker-compose.yml | ✅ Created |
| backend/.dockerignore | ✅ Created |

### Models (Downloaded at Runtime)

| Model | Location | Status |
|---|---|---|
| bge-small-en-v1.5 (ONNX Int8) | nlp_models/embeddings/ | Downloaded by FastEmbed at runtime |
| bge-reranker-base/small (ONNX Int8) | nlp_models/reranker/ | Downloaded by transformers at runtime |
| — (no NLP model needed) | — | Dictionary-based entity extraction — no model required |

## Compatibility Issues Found

1. **psycopg2-binary vs psycopg**: System has `psycopg2-binary` (v2.x) but project requires `psycopg[binary,pool]` (v3.x). These are different drivers. Must uninstall old and install new.
2. **fastapi 0.139.2 vs 0.141.1**: Old version installed. Must upgrade.
3. **uvicorn 0.51.0 vs 0.52.1**: Old version installed. Must upgrade.
4. **PyJWT 2.9.0 vs 2.13.0**: Old version installed. Must upgrade.
5. **Missing pydantic-settings**: Required by `config.py`.
6. **Missing fastembed, onnxruntime, RapidFuzz, python-multipart, passlib**: All required but not installed.
7. **npm security policy**: Running scripts is disabled on this system. Need to adjust execution policy for npm.

## Step-by-Step Plan

### Phase A: Fix Dependencies

- [x] A1: Create backend virtual environment (Python 3.11.15 via uv at `backend/.venv`)
- [x] A2: Install all backend requirements (requirements.txt + requirements-dev.txt)
- [x] A3: Fix npm execution policy for frontend (deferred — frontend verified via Docker)
- [x] A4: Install frontend dependencies (npm ci) (deferred — verified via Docker build)

### Phase B: Run Tests

- [x] B1: Run backend unit tests (107 passed — fixed by creating `backend/.env`)
- [x] B2: Run backend integration tests (7 passed, 4 skipped — skipped need live Postgres; pass after compose up)
- [x] B3: Fix any test failures

### Phase C: Build Docker

- [x] C1: Build backend Docker image
- [x] C2: Build frontend Docker image
- [x] C3: Run docker-compose up (ports 5433/8011/3011 — all healthy)
- [x] C4: Verify all services are healthy (`/health` → healthy)

### Phase D: Verify Application

- [x] D1: Test health endpoints
- [x] D2: Test search endpoint with auth (login admin@asto.local/admin123 → search returns answer + summary)
- [x] D3: Test frontend serves correctly (3011 → 200)
- [x] D4: Run evaluation benchmark (`evaluation/reports/benchmark_20260808_005649.json`)

### Phase E: Session Continuation

- [x] E1: Document how to resume this session (SESSION.md updated through Session 4)

### Phase D-feature (Session 4): Frontend UX

- [x] F1: Chat-style conversation view at `/` (user/assistant bubbles, typing indicator)
- [x] F2: 24h localStorage chat history (`hooks/use-chat-history.ts`)
- [x] F3: Client portal `/portal` + Staff/Client login tabs
- [x] F4: Admin dashboard `/admin` (approvals, documents+upload, users, clients, analytics)
- [x] F5: Build + lint clean; frontend container rebuilt and serving 200
- [x] F6: API shape smoke test — all new frontend calls match live backend

---

## How to Continue This Session Tomorrow

### Option 1: From the same machine

1. Open PowerShell in this directory:
   ```
   cd C:\Users\chait\Downloads\Asto v1
   ```
2. Check where we left off by reading `SESSION.md` (read this first — it's the
   single source of truth for current state and next steps).
3. Resume from the last unchecked task.

### Option 2: Start a new session

1. Navigate to the project root:
   ```
   cd C:\Users\chait\Downloads\Asto v1
   ```
2. Read the session summary first:
   ```
   cat SESSION.md
   ```
3. Read the audit document:
   ```
   cat AUDIT.md
   ```
4. Check the current state of files with git status or by reviewing recent changes
5. Resume from where you left off

### Key files to remember

- `AUDIT.md` — Full audit findings and phase-wise TODO tasks
- `BUILD_PLAN.md` — This file, the build verification plan
- `backend/requirements.txt` — Backend Python dependencies
- `backend/requirements-dev.txt` — Dev/test dependencies
- `frontend/package.json` — Frontend Node.js dependencies
- `docker-compose.yml` — Docker orchestration for local dev
- `backend/Dockerfile` — Backend container definition 
 
- `frontend/Dockerfile` — Frontend container definition
- `.github/workflows/` — CI/CD pipelines
- `backend/app/` — Main application source code
- `backend/tests/` — Test suite