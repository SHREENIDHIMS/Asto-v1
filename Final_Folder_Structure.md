# Mortgage CRM Intelligent Knowledge Assistant — Final Folder Structure (V3.2)

Reflects every decision made through the shared-host addendum: pgvector
replaces Qdrant, Redis/MinIO removed for MVP, ingestion runs as a batch
script, backend is socket-activated. **Updated 2026-08-08 (Sessions 3–4)**
for the dual-audience model (client auth), the approval workflow, and the
chat/client-portal/admin frontend. This supersedes the earlier
single-project version.

```
asto-knowledge-assistant/
│
├── frontend/                              # Next.js + TypeScript + Shadcn/UI
│   ├── app/                               # NOTE: no app/api/ route handlers —
│   │   │                                  # static export has no server runtime.
│   │   │                                  # Frontend calls FastAPI directly via
│   │   │                                  # lib/api-client.ts; JWT auth is
│   │   │                                  # enforced backend-side.
│   │   ├── page.tsx                       # Chat view (/) — user/assistant bubbles
│   │   ├── layout.tsx
│   │   ├── login/page.tsx                 # Staff / Client tabs
│   │   ├── portal/page.tsx                # Client self-service (me, properties, cases, docs)
│   │   └── admin/page.tsx                 # Admin dashboard (approvals, documents, users, clients, analytics)
│   ├── components/
│   │   ├── ui/                            # Shadcn primitives
│   │   ├── search/
│   │   │   ├── SearchBar.tsx
│   │   │   ├── ResponsePackageCard.tsx
│   │   │   ├── ConfidenceBadge.tsx
│   │   │   ├── SourceCitation.tsx
│   │   │   └── RelatedQuestions.tsx
│   │   ├── chat/
│   │   │   └── ChatMessage.tsx            # assistant bubble wrapping ResponsePackageCard
│   │   ├── feedback/
│   │   │   └── ThumbsFeedback.tsx
│   │   └── home/
│   │       └── HeroSection.tsx
│   ├── hooks/
│   │   └── use-chat-history.ts            # 24h localStorage history (TTL purge)
│   ├── lib/
│   │   ├── api-client.ts                  # calls FastAPI directly, no BFF proxy
│   │   ├── auth.ts                        # JWT stored client-side, sent per-request; decodeToken
│   │   └── utils.ts
│   ├── public/
│   ├── styles/
│   │   └── globals.css
│   ├── .env.example                       # NEXT_PUBLIC_API_URL
│   ├── next.config.js                     # output: 'export'
│   ├── nginx.conf                         # frontend container static serving
│   ├── Dockerfile                         # node:20-alpine build → nginx:1.27-alpine
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   └── package.json
│
├── backend/                                # FastAPI application (socket-activated)
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py                       # imports weights_config.py / confidence_thresholds.py — file-based, benchmark-gated (not DB-driven)
│   │   ├── dependencies.py                 # get_current_user resolves staff (users) OR client (clients)
│   │   │
│   │   ├── api/
│   │   │   ├── v1/
│   │   │   │   ├── auth.py                 # /auth/login (staff) + /auth/client-login
│   │   │   │   ├── search.py
│   │   │   │   ├── documents.py            # list (admin review)
│   │   │   │   ├── upload.py               # upload only — queues for batch ingestion
│   │   │   │   ├── feedback.py
│   │   │   │   ├── analytics.py            # knowledge gaps
│   │   │   │   ├── admin.py                # users/clients/assignments (Phase C3)
│   │   │   │   ├── approvals.py            # pending/approve/reject/history (Phase B3)
│   │   │   │   └── client.py               # /client/me|properties|cases|documents (Phase C)
│   │   │   └── router.py
│   │   │
│   │   ├── query_processing/
│   │   │   ├── spell_correction.py
│   │   │   ├── normalization.py
│   │   │   ├── intent_detection.py
│   │   │   ├── entity_extraction.py            # dictionary-based, no NER model
│   │   │   ├── query_expansion.py
│   │   │   ├── multi_question.py
│   │   │   └── pipeline.py
│   │   │
│   │   ├── search/                         # Hybrid Search Engine
│   │   │   ├── metadata_filters.py         # RBAC + approval + active-version pre-filter (enforced HERE)
│   │   │   └── hybrid_orchestrator.py      # single SQL query: BM25 + pgvector + filters
│   │   │
│   │   ├── ranking/
│   │   │   ├── rrf.py
│   │   │   ├── weights_config.py           # initial default weights
│   │   │   └── reranker.py                 # ONNX Int8 cross-encoder, top-10 candidates
│   │   │
│   │   ├── response/
│   │   │   ├── package_builder.py
│   │   │   ├── summarizer.py               # extractive (Sumy TextRank), verbatim only
│   │   │   ├── confidence_thresholds.py    # initial default thresholds
│   │   │   └── validation.py               # redundant permission/version check (never rejects low confidence)
│   │   │
│   │   ├── documents/                       # shared by API (upload) and batch ingestion
│   │   │   ├── validation.py
│   │   │   ├── ingest_batch.py              # entry point for run_ingestion.sh — NOT imported by main.py
│   │   │   ├── text_extraction.py
│   │   │   ├── chunking/
│   │   │   │   ├── structural_chunker.py
│   │   │   │   ├── table_chunker.py
│   │   │   │   └── checklist_chunker.py
│   │   │   ├── metadata_extraction.py
│   │   │   ├── embedding.py                 # FastEmbed + bge-small-en-v1.5, batch-time
│   │   │   └── indexing.py                  # inserts as pending (approval_status='pending')
│   │   │
│   │   ├── auth/
│   │   │   ├── jwt_handler.py               # audience + client_id claims
│   │   │   ├── rbac.py
│   │   │   └── permissions.py               # require_role fail-closed for clients
│   │   │
│   │   ├── audit/
│   │   │   └── audit_logger.py
│   │   │
│   │   ├── knowledge_gap/
│   │   │   └── gap_detector.py
│   │   │
│   │   └── db/
│   │       └── postgres/
│   │           ├── models.py                 # row→dict helpers (client/case)
│   │           └── session.py                # connects to shared instance, own database
│   │
│   ├── scripts/
│   │   └── seed_db.py                        # admin + client + property + case + assignment + pending doc
│   ├── tests/
│   │   ├── unit/                             # 140 tests
│   │   │   ├── test_approvals.py
│   │   │   ├── test_client_auth.py
│   │   │   ├── test_backend_skeleton.py
│   │   │   ├── test_documents.py
│   │   │   ├── test_search_ranking.py
│   │   │   ├── test_response.py
│   │   │   ├── test_spell_correction.py
│   │   │   └── test_summarizer.py
│   │   ├── integration/                      # 11 tests (live Postgres)
│   │   │   ├── test_rbac_prefilter.py
│   │   │   ├── test_dual_audience.py
│   │   │   ├── test_end_to_end.py
│   │   │   └── test_approvals.py
│   │   └── conftest.py
│   ├── requirements.txt                     # slim base image, no onnxruntime-on-alpine issues
│   ├── Dockerfile                           # python:3.11-slim, not alpine
│   └── .env.example
│
├── evaluation/
│   ├── datasets/
│   │   └── eval_20_questions.jsonl
│   ├── metrics/
│   │   ├── precision_recall.py
│   │   ├── mrr.py
│   │   ├── ndcg.py
│   │   ├── hit_rate.py
│   │   └── latency_benchmark.py             # includes reranker + cold-start latency checks
│   ├── run_benchmark.py
│   └── reports/
│       └── benchmark_20260808_005649.json   # baseline (Session 2)
│
├── shared-host-infra-scaffold/               # Production deployment
│   └── infra/
│       ├── README.md                        # setup steps, run in order
│       ├── shared/                          # docker-compose (Postgres + Nginx) + nginx conf
│       ├── systemd/                         # socket/service/timer units
│       └── scripts/                         # migrate_db.sh, run_ingestion.sh, idle-stop
│
├── storage/                                  # local filesystem — replaces MinIO
│   ├── pending/                              # uploaded, awaiting batch ingestion
│   └── processed/                            # ingested source files, kept for citation/audit
│
├── .github/
│   └── workflows/
│       ├── ci.yml
│       ├── eval_on_pr.yml
│       └── deploy.yml
│
├── CLAUDE.md                                 # hard architectural rules
├── SESSION.md                                # session state / next steps (read first)
├── BUILD_PLAN.md
├── README.md
└── LICENSE
```

## What's different from the single-project version

| Removed | Why |
|---|---|
| `backend/app/db/qdrant/` | Replaced by pgvector column inside `db/postgres/` |
| `backend/app/cache/redis_client.py` | Redis dropped for MVP |
| MinIO service/config | Replaced by `storage/` on local filesystem |
| `frontend/src/app/api/` route handlers | Static export has no server runtime; frontend calls FastAPI directly |
| Per-project `docker-compose.yml` for Postgres | Now lives once in `/opt/shared-infra/`, not per project |

| Added | Why |
|---|---|
| `search/pgvector_search.py` + rewritten `hybrid_orchestrator.py` | BM25 + vector + metadata filter can now be one SQL query |
| `documents/ingest_batch.py` | Entry point for on-demand ingestion, decoupled from the API process |
| `infra/systemd/` | Socket activation + idle-timeout units for this project's backend |
| `storage/pending/` + `storage/processed/` | Local filesystem replacing MinIO |
| `cpu-credit-balance.json` dashboard | CPU contention across shared-host projects is now a tracked risk, not just RAM |

## Added 2026-08-08 (Sessions 3–4 — dual-audience, approvals, frontend)

| Added | Why |
|---|---|
| `api/v1/approvals.py` | Document approval workflow (pending → approve/reject/history) with `approval_log` audit trail |
| `api/v1/client.py` | Client-scoped self-service endpoints (`me`, `properties`, `cases`, `documents`) |
| `api/v1/admin.py` (extended) | User/client management + staff↔client assignments |
| `auth/jwt_handler.py` (extended) | `audience` + `client_id` claims; `auth.py` gains `/auth/client-login` |
| `dependencies.py` (extended) | `get_current_user` resolves staff (`users`) OR client (`clients`) |
| `documents/indexing.py` (extended) | Ingestion inserts documents as `pending` (approval-gated) |
| `scripts/seed_db.py` | Dev seed: admin + client + property + case + assignment + pending doc |
| `frontend/app/page.tsx` → chat | ChatGPT-style conversation view with typing indicator |
| `frontend/app/login/page.tsx` | Staff / Client login tabs |
| `frontend/app/portal/page.tsx` | Client self-service dashboard |
| `frontend/app/admin/page.tsx` | Admin dashboard: approvals, documents+upload, users, clients, analytics |
| `frontend/hooks/use-chat-history.ts` | 24h localStorage chat history (TTL purge) |
| `tests/unit/test_approvals.py`, `test_client_auth.py` | New unit coverage (140 total) |
| `tests/integration/test_dual_audience.py` + approvals integration | New integration coverage (11 total) |

## Correction (post-review)

`config.py`'s annotation previously read "ranking weights / thresholds,
DB-driven," which contradicted `weights_config.py` /
`confidence_thresholds.py` being described elsewhere as benchmark-gated
defaults (CLAUDE.md rule #7, `Final_System_Design.md` §10.8). Corrected
to reflect the file-based design: `config.py` imports the values from
those two files rather than reading them from a database, so a change
can't bypass `eval_on_pr.yml`'s benchmark gate. If live DB-tunable config
is actually wanted, that's a deliberate architecture change requiring its
own enforcement mechanism (see review discussion) — not a doc fix.