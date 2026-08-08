# Mortgage CRM Intelligent Knowledge Assistant — Final Tech Stack (V3.2)

Companion to `Final_Folder_Structure.md` and `Final_System_Design.md`.
Reflects the shared-host-optimized stack — supersedes the original
tech stack table.

---

## Application Layer

| Layer | Technology | Notes |
|---|---|---|
| Frontend | Next.js + TypeScript | `output: 'export'` — static build, no Node server process |
| UI | Tailwind CSS + Shadcn/UI | unchanged |
| Web Server (frontend) | Nginx | serves static export directly; also reverse-proxies to backend |
| Backend | FastAPI | single Uvicorn worker (`--workers 1`) |
| Backend Runtime Mode | Systemd socket activation | starts on first request, idle-stops after 10 min |
| Authentication | JWT | enforced backend-side; frontend has no server-side auth layer |

## Data Layer

| Layer | Technology | Notes |
|---|---|---|
| Database | PostgreSQL (shared instance) | **one instance for all projects on the host**, one database per project |
| Vector Search | **pgvector extension** | replaces Qdrant; embeddings stored as a column, queried via cosine distance in the same SQL query as BM25 |
| Keyword Search | PostgreSQL Full Text Search (BM25) | unchanged |
| Cache | ~~Redis~~ **Removed for MVP** | reintroduce only when real traffic justifies the RAM cost |
| Object Storage | ~~MinIO~~ **Local filesystem** | `storage/pending/` and `storage/processed/` on the instance's EBS volume |

## NLP / ML Layer

| Purpose | Technology | Notes |
|---|---|---|
| NLP Pipeline | — | Dictionary-based entity extraction (entity_extraction.py) — no spaCy/GLiNER |
| Entity Recognition | Domain term dictionary | Replaced GLiNER — lighter (~0 MB, microseconds) for the 1 GiB shared host |
| Embeddings | FastEmbed + BAAI/bge-small-en-v1.5 (ONNX Int8) | ~35MB RAM, unchanged from V3.1 — already optimal |
| Re-ranking | bge-reranker-base/small, **ONNX Int8 quantized** | quantization added to protect the <200ms p95 latency budget on a shared host |
| OCR | Tesseract (optional) | unchanged |

## Search & Ranking Algorithms

| Purpose | Algorithm | Notes |
|---|---|---|
| Keyword Search | BM25 | via Postgres full-text search |
| Semantic Search | Cosine Similarity | via pgvector, not Qdrant/HNSW |
| Vector Index | pgvector IVFFlat or HNSW index | Postgres-native, not a separate service |
| Rank Fusion | Reciprocal Rank Fusion (RRF) | unchanged |
| Re-ranking | Cross-Encoder (quantized) | unchanged model choice, quantized deployment |
| Spell Correction | RapidFuzz / SymSpell | unchanged |
| Query Expansion | Synonym Dictionary | unchanged |
| Chunking | Hybrid Structural Chunking | unchanged (tables/checklists as atomic chunks) |
| Confidence | Weighted Scoring | initial default thresholds, tuned via Evaluation Framework |

## Infrastructure Layer

| Layer | Technology | Notes |
|---|---|---|
| Compute | AWS EC2 (t2.micro / t3.micro, 1 GiB RAM) | free tier; shared across multiple projects |
| Container Base Images | `python:3.11-slim`, `nginx:1.27-alpine` | **not** `python:3.11-alpine` — onnxruntime compiled deps are unreliable on musl libc |
| Process Management | systemd (socket + service + timer units) | on-demand activation, idle-timeout stop |
| Reverse Proxy | Nginx (shared, one instance for all projects) | one server block per project |
| Swap | 2GB file on EBS | OOM-killer prevention only, not a performance feature |
| Monitoring | Prometheus + Grafana | added: CPU credit balance dashboard |
| Logging | stdlib logging (file rotation) | synchronous file writes |
| Audit Logging | Dedicated append-only Postgres table/schema | separate from analytics, compliance artifact |
| CI/CD | GitHub Actions | includes `eval_on_pr.yml` — blocks merge on retrieval-quality regression |

## Explicitly Removed From V3.1 Stack

| Removed | Reason |
|---|---|
| Qdrant | Replaced by pgvector — one fewer standing process |
| Redis | Not a hard dependency for MVP; adds idle RAM cost |
| MinIO | Local filesystem storage is sufficient at this scale |
| Per-project Postgres instances | Consolidated into one shared instance with per-project databases |
| Always-running backend process | Replaced by socket-activated, idle-stopped process |
| In-process document ingestion | Moved to a decoupled batch script (`run_ingestion.sh`) |

## Known Unmitigated Risks (carried forward from architecture review)

- **CPU credit contention**: burstable instance types share one CPU
  credit pool across every project on the box. This stack optimizes
  memory, not CPU — tracked via monitoring, not solved architecturally.
- **Cold-start latency**: the first request to an idle project (after
  the 10-minute idle-stop) will be slower. Acceptable for demo/low-traffic
  use; not acceptable for any project with a hard latency SLA.
- **Single point of failure**: one instance hosting multiple projects
  means one instance failure takes all of them down. Fine for side
  projects; not a substitute for real infrastructure once any one
  project has real users or revenue depending on it.
