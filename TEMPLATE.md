# Asto — Working Template & Conventions

> This file defines **how every session is run**. Read it at the start of every
> session, follow it for every task. It is the "method" companion to
> `SESSION.md` (state + next steps) and `CLAUDE.md` (hard rules).

---

## 1. Session Protocol (every time)

1. **Read first:** `CLAUDE.md` (rules) → `SESSION.md` (where we are) →
   `TEMPLATE.md` (this file) → `SKILL.md` (build order) if resuming build work.
2. **State the plan aloud:** before each action, tell the user what you're
   doing, why, and what the expected result is.
3. **Think "can this be done better?"** Before implementing, consider: simpler
   alternative? existing pattern to reuse? config over constants? benchmark gate
   required?
4. **Work in phases, track with todos:** always maintain a todo list; complete
   one phase before the next.
5. **Explain before you touch:** "I'm doing X because Y" for every significant
   action, especially file changes, installs, and destructive ops.
6. **Verify:** run tests/lint/typecheck after every change; run the evaluation
   benchmark when retrieval/ranking/confidence is affected.
7. **Update `SESSION.md` at session end:** what was done, what's next, new
   decisions, open questions. Keep it current — never let it drift.
8. **Never commit unless asked.**

## 2. Tool / Skill Usage

- Use the `shadcn` skill when adding UI components (chat UI, admin panels).
- Use `ui-styling` / `ui-ux-pro-max` when designing the chat UX or dashboard.
- Use the `customize-opencode` skill only for opencode config itself.
- Install relevant skills from the web/GitHub when a task maps to a known
  skill (e.g., shadcn for component work); record the install in SESSION.md.

## 3. Architectural Rules (from CLAUDE.md — never violate)

1. **No LLM generation in the serving path.** No `Answer` field — only
   `Response Package` (retrieved excerpts). Never assemble sentences or
   paraphrase retrieved content. Exception: the extractive summary
   (`response/summarizer.py`, Sumy TextRank) may select up to 4 sentences
   **verbatim** from the top excerpts — no paraphrasing or inventing text.
2. **RBAC + active-version filtering in the Postgres WHERE clause** at query
   time — validation.py may re-check but is never the only enforcement.
3. **One Postgres per host, one DB per project.** Never add per-project
   Postgres/Qdrant/Redis/MinIO containers.
4. **pgvector in the same SQL statement** as BM25 + RBAC filter.
5. **`--workers 1`, socket-activated, idle-stop.** No background threads/
   schedulers in the API process.
6. **Ingestion (OCR/chunk/embed) only in the batch script**, never in request
   handlers.
7. **Reranker <200ms p95** — check via latency benchmark before merging.
8. **Ranking weights & confidence thresholds are configuration**, changed only
   with an evaluation benchmark showing improvement.
9. **Audit-log every query** — never skip, even for test queries.
10. **Base images: `python:3.11-slim`** for onnxruntime-touching services;
    `nginx:alpine` is fine. Never `python:3.11-alpine`.
11. **Memory caps stay** (Postgres ~200MB, Nginx ~30MB, Backend ~200MB) —
    investigate OOM cause, don't raise caps blindly.

## 4. Ports & Naming (single source of truth)

| Thing | Value |
|---|---|
| Postgres host port | **5433** |
| Backend port | **8011** |
| Frontend port | **3011** |
| DB name | `asto_assistant` |
| DB user | `asto_app` |
| Env prefix | `ASTO_` |
| Product name | **Asto** |
| Systemd units | `asto-backend.socket/service`, `asto-backend-idle.timer/service` |
| Frontend package name | `asto-frontend` |

Keep these consistent in every new file, config, or doc. If ports need to
change again, update docker-compose, Dockerfile, nginx, systemd, .env examples,
api-client.ts, package.json, infra scripts, README/SKILL/design docs, and this
file + SESSION.md together.

## 5. Feature Checklist (before calling a task done)

- [ ] Respects every rule in §3.
- [ ] Tests exist (unit and/or integration) under `backend/tests/`.
- [ ] Retrieval-affecting? → `evaluation/run_benchmark.py` run before/after,
      delta recorded in `evaluation/reports/`.
- [ ] Docs updated if the change alters an established decision.
- [ ] New ports/naming follow §4.
- [ ] `SESSION.md` next-steps list updated.

## 6. Code Style

- No comments unless they explain *why* (not what). Match existing style.
- Python: type hints (`from __future__ import annotations`), pydantic for
  config, psycopg3 async-free (sync acquire used today).
- TS/React: functional components, Tailwind + shadcn/ui, client-side auth.
- No secrets in code; env vars via `ASTO_` prefix; `.env` never committed.
