# CLAUDE.md — Knowledge Assistant

This file is read by Claude (via Claude Code or any agent working in this
repo) before making changes. It captures decisions that are **already
settled** — don't re-litigate them without the user explicitly asking to
revisit the architecture. If a task seems to require breaking one of these
rules, stop and ask rather than silently working around it.

Companion docs (read these for full detail, this file is the summary):
- `docs/Final_System_Design.md` — architecture, flowcharts, rationale
- `docs/Final_Tech_Stack.md` — full stack table
- `docs/Final_Folder_Structure.md` — where everything lives
- `.claude/skills/asto-assistant-builder/SKILL.md` — step-by-step build order

---

## Non-negotiable design philosophy

**"Find the right information, don't generate new information."**

- No LLM call anywhere in the request-serving path. No `Answer` field —
  only `Response Package` (retrieved excerpts, never abstractively
  synthesized text).
- One exception, deliberately allowed: an **extractive summary**
  (`response/summarizer.py`, Sumy TextRank) selects up to 4 sentences
  **verbatim** from the top retrieved excerpts. It never paraphrases,
  rewrites, or invents text — every summary sentence must exist verbatim in
  a source chunk and is mapped back to its source for citation.
- If you find yourself writing code that assembles a sentence from
  multiple sources or paraphrases retrieved content, stop — that's
  generation, and it violates the core compliance guarantee of this system.
- Adding any **abstractive** summarizer (an LLM, T5/BART-style models, or
  a "rewrite this in your own words" step) is prohibited without an
  explicit decision to revisit this rule.

## Hard architectural constraints

0. (Implicit from design) **Confidence routing is a response-time decision, not a validation gate.** `confidence_thresholds.py` (`route_by_confidence`) sets `package.routing` to `"answer"`, `"partial"`, or `"no_answer"`. `response/validation.py` only enforces RBAC and approval checks — it must NOT reject low-confidence packages (otherwise "no answer" queries return HTTP 500 instead of a graceful `no_answer` response).

1. **RBAC and active-version filtering happen in the Postgres `WHERE`
   clause at query time** (in `search/hybrid_orchestrator.py` /
   `search/metadata_filters.py`), never as a post-hoc check only.
   `response/validation.py` may re-check as a safety net, but must not be
   the *only* place permissions are enforced.
2. **One Postgres instance for the whole host, one database per project.**
   Never add a per-project Postgres container. Never add Qdrant, Redis, or
   MinIO — those were deliberately removed. If a future task seems to need
   one of them, flag it to the user instead of adding it silently.
3. **Vector search uses pgvector**, queried in the same SQL statement as
   BM25 and the RBAC/version filter where practical — not a separate
   round-trip to a separate service.
4. **The FastAPI backend runs with `--workers 1`** and is socket-activated
   (see `infra/systemd/`) — it is not meant to run continuously. Don't add
   background threads or in-process schedulers that would defeat idle-stop.
5. **Document ingestion (OCR, chunking, embedding generation) runs
   only in the batch script** (`infra/scripts/run_ingestion.sh` →
   `backend/app/documents/ingest_batch.py`), never inside `app/main.py` or
   any request handler. The API's `documents/upload.py` only validates and
   writes to `storage/pending/` — it must not call the ingestion pipeline
   directly.
6. **Cross-encoder reranking has a <200ms p95 latency budget.** Any change
   to the reranker (model swap, candidate count, precision) must be
   checked against this budget via `evaluation/metrics/latency_benchmark.py`
   before merging.
7. **Ranking weights (`ranking/weights_config.py`) and confidence
   thresholds (`response/confidence_thresholds.py`) are configuration,
   not constants.** Change them based on evidence from
   `evaluation/run_benchmark.py` (or a ranking comparison), never on a
   "better-feeling" number. This is a working discipline, not a gate: when
   a change is benchmark-verified — report saved in `evaluation/reports/`
   with the before/after delta — apply it. If a full benchmark can't be
   run, proceed but record the reasoning in the report so the change stays
   auditable.
8. **Every query is audit-logged** (`audit/audit_logger.py`) —
   user, query, retrieved documents, timestamp, confidence, response ID.
   This is separate from `analytics/` and must never be skipped, even for
   "internal" or test queries against production data.
9. **Container base images: `python:3.11-slim` for anything touching
    onnxruntime. Never `python:3.11-alpine`** for those — musl
   libc breaks compiled ML dependencies. `nginx:alpine` is fine (no ML deps).
10. **Memory is capped per-service** (Postgres ~200MB, Nginx ~30MB, backend
    ~200MB — see `infra/shared/docker-compose.yml` and the systemd units).
    Don't remove these caps to "fix" an OOM — investigate why the service
    needs more memory first.

## When adding a new feature

- Check whether it belongs in the always-on API path or the batch
  ingestion path. Heavy/NLP work → batch. Query-time logic → API.
- Check whether it needs a new standing service. It almost never should —
  prefer extending Postgres (new table, new pgvector column) over adding
  a new container.
- If it touches ranking, packaging, or validation, run
  `evaluation/run_benchmark.py` before and after and report the delta.
- If it's a second project sharing this host, it gets its own systemd
  socket/service pair and its own Postgres database — never its own
  Postgres/Nginx/Redis instance. Follow the pattern in `infra/README.md`.

## What "done" looks like for this project

See the SKILL.md build order for phase-by-phase definition-of-done
criteria. At a high level, a feature or phase is done when:
- It respects every constraint above.
- It has a test (unit or integration) under `backend/tests/`.
- If it affects retrieval quality, the evaluation benchmark has been run
  and the result is recorded in `evaluation/reports/`.
- Documentation in `docs/` is updated if the change alters an established
  decision (not just implementation detail).
