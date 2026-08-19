# Asto Product Roadmap — Phase H onward (v1.1)

> Working document for turning Asto into a full-fledged product. This is the
> **single source of truth for planned features** — every addition is planned
> here first, then implemented phase-by-phase, then ticked off. Companion
> files: `SESSION.md` (what exists now + session log), `CLAUDE.md` (hard
> rules), `SKILL.md` (build order).
>
> Read the entire file once before starting. Then implement strictly
> phase-by-phase in the order below — each feature has tests + live-verify as
> its DoD, so the app stays shippable at every step.

---

## 0. How to use this document

1. Every feature has an ID (`H1`, `I2`, …). Use the ID in commit messages,
   SESSION.md entries, and branch names.
2. Work in phase order. Inside a phase, work top-to-bottom (dependencies are
   listed where they exist).
3. When a feature is done (DoD met), tick its checkbox in Part 6.
4. When a phase is fully ticked, write a Session log entry in `SESSION.md`
   and (if it alters an established decision) update the design docs.
5. Anything not in this file is out of scope unless the user adds it here.

---

## 1. Guardrails (repeat these before every feature)

From `CLAUDE.md` — non-negotiable:

- **No LLM call in the request-serving path.** No `Answer` field — only
  `Response Package` (retrieved excerpts). Extractive summary only.
  Any feature that would add abstractive generation **requires an explicit
  decision first** (see Part 2).
- **One Postgres per host, one DB per project.** Never add Qdrant/Redis/MinIO
  or a per-project Postgres container. If a feature "needs" one, stop and ask.
- **RBAC + active-version filtering in the SQL WHERE clause**, never as a
  post-hoc check only.
- **Ingestion/OCR/embeddings run only in the batch script**, never in a
  request handler or background thread.
- **`--workers 1` + socket-activated backend.** No in-process schedulers.
- **Cross-encoder rerank stays <200ms p95**; ranking weights and confidence
  thresholds are config, changed only on benchmark evidence
  (`evaluation/run_benchmark.py` → report in `evaluation/reports/`).
- **Every query is audit-logged.** Never skipped.
- **Base images:** `python:3.11-slim` for anything touching onnxruntime.
- **Memory caps stay.** Investigate, don't just raise the cap.

Global "definition of done" (applies to every feature):
- [ ] Respects every guardrail above.
- [ ] Backend: endpoint(s) tested under `backend/tests/` (unit or
      integration) — full suite stays green.
- [ ] Frontend: `tsc --noEmit` + `next lint` clean.
- [ ] Affects retrieval quality → benchmark before/after recorded in
      `evaluation/reports/`.
- [ ] SESSION.md updated; this roadmap checkbox ticked.
- [ ] Live-verified against rebuilt containers.

---

## 2. Architecture decisions (flag before touching — require user sign-off)

### DEC-1 — Optional LLM "cite-with-LLM" mode
- **What:** an *opt-in, per-query* mode that asks an LLM to draft an answer
  strictly over the retrieved excerpts (RAG), always showing citations.
  Disabled by default; every response still carries verbatim excerpts.
- **Why:** users want natural-language answers; the compliance guarantee is
  preserved because the mode is explicit, sourced, and off by default.
- **Cost:** new external dependency (LLM API), latency, cost, and a
  documented carve-out to the core doctrine.
- **Decision needed:** yes/no. If yes, is it a separate endpoint
  (`POST /search/llm`) and a UI toggle?

### DEC-2 — Redis / Qdrant / MinIO
- **Status: keep removed.** Revisit only if vector scale or caching metrics
  prove we need them (see M3/M4 first — they solve most of it).

### DEC-3 — Email/SMS delivery
- **Recommended:** SMTP from the **batch** path (no new container, no
  in-process scheduler). A `notifications.email_pending` flag + a
  `scripts/send_pending_emails.py` batch job. Supports forgot-password,
  review outcomes, message pings. SMS deferred unless a specific provider is
  chosen.
- **Decision needed:** which SMTP/relay and which events send mail
  (start with forgot-password + review outcomes + message ping).

---

## 3. Phase H — Security & Auth hardening

### H1 — JWT in HttpOnly cookie (replace localStorage)
- **Why:** localStorage is readable by any XSS payload — the single biggest
  real security risk today. HttpOnly cookies can't be read by JS.
- **Effort:** M. **Depends on:** nothing.
- **Steps:**
  1. Backend: on login, set `Set-Cookie: asto_access=<jwt>; HttpOnly;
     SameSite=Lax; Path=/; Secure` (Secure behind TLS; config-gated).
  2. Add `GET /auth/csrf-token` + a CSRF check on mutating requests
     (double-submit cookie or header) — required once auth moves to cookies.
  3. Add **refresh-token rotation**: short access (e.g. 15m) + `POST
     /auth/refresh` issuing a new pair from a signed refresh token stored
     hashed in a `refresh_tokens` table (supports H5 revocation).
  4. Backend dependency `get_current_user` reads the cookie when no
     `Authorization` header is present (keep Bearer for tests/API clients).
  5. Frontend: `lib/auth.ts` stops persisting JWT to localStorage; api-client
     sends `credentials: 'include'` and attaches the CSRF header; a
     silent-refresh interceptor re-issues before expiry.
  6. `POST /auth/logout` clears the cookie + revokes the refresh token.
  7. Tests: cookie set/secure flags, CSRF missing → 403, refresh rotation
     (old refresh rejected), logout clears cookie. Keep Bearer path working
     (existing tests stay green).
  8. Docs: `docs/Final_System_Design.md` auth section; SESSION.md.

### H2 — Forgot-password / reset flow
- **Why:** the login page already links "forgot password" — it currently
  does nothing. Table-stakes for a real product.
- **Effort:** M. **Depends on:** DEC-3 (email) or a dev-friendly log-to-console
  fallback.
- **Steps:**
  1. `POST /auth/forgot-password` — resolves email across users+clients
     (generic 200 to avoid enumeration), inserts a `password_resets`
     row (token hash, expiry 1h), queues email via the notifications batch
     (or logs the link when SMTP is unconfigured).
  2. `POST /auth/reset-password` (token + new password) — validates expiry,
     reuses existing bcrypt + password-strength rules, invalidates the token,
     revokes sessions.
  3. Frontend: reset-request + reset form views on `/login`; link in the
     existing forgot-password affordance.
  4. Tests: forgot generic-200 for both known/unknown emails, reset happy
     path + expired token + weak password 422, token single-use.
  5. Docs: SESSION.md.

### H3 — Login rate limiting + account lockout
- **Why:** brute-force protection. No new service — a Postgres-backed
  `login_attempts` table (per-email + per-IP), checked in `auth.py`.
- **Effort:** S.
- **Steps:**
  1. Table: `login_attempts(email, ip, attempted_at, success)` + index on
     (email, attempted_at desc). Prune older than 24h in the same transaction.
  2. In `POST /auth/login` and `/auth/client-login`: fail if ≥5 failed in
     the last 15m (429), lockout message; record every attempt.
  3. Tests: 5 failures → 429, window expiry re-enables login, success resets
     the counter.
  4. SESSION.md.

### H4 — Admin 2FA (TOTP)
- **Why:** protects the account that can approve docs and see the audit log.
- **Effort:** M. **Depends on:** none (pure Postgres + `pyotp`).
- **Steps:**
  1. Backend: `POST /admin/2fa/setup` returns `otpauth://` URI + secret;
     `POST /admin/2fa/verify` validates and stores `totp_secret` (encrypted)
     on the user row; `POST /admin/2fa/disable` (requires password).
  2. Login: when a user has 2FA enabled, `/auth/login` returns a
     `requires_2fa` marker + short-lived `2fa_token`; `POST /auth/2fa` swaps
     it for the real JWT.
  3. Frontend: 2FA setup/verify modal in admin Settings; login shows the
     code field when required.
  4. Tests: setup/verify/disable, login flow with and without 2FA,
     wrong code → 401, `2fa_token` single-use.
  5. SESSION.md.

### H5 — Session revocation (logout-all / admin kill)
- **Why:** leaked tokens should be killable; complements H1 refresh rotation.
- **Effort:** S. **Depends on:** H1 (refresh tokens) for full value.
- **Steps:**
  1. Refresh tokens get a `jti`; `POST /auth/logout-all` deletes all rows for
     the user; admin `DELETE /admin/users/{id}/sessions` kills a user's
     sessions.
  2. Access-token revocation for the rare emergency: optional short-lived
     `revoked_jtis` check on refresh path (documented trade-off — access
     tokens stay valid until expiry).
  3. Tests: logout-all revokes refresh, admin kill, normal logout.
  4. SESSION.md.

### H6 — Password change UI (staff + client)
- **Why:** users can only use seeded passwords today.
- **Effort:** S. **Depends on:** nothing.
- **Steps:**
  1. Backend: `POST /me/password` (current + new, strength rules), scoped to
     both audiences; revoke sessions after change.
  2. Frontend: "Change password" in client Settings and staff/admin Settings.
  3. Tests: wrong current → 403, weak new → 422, both audiences.
  4. SESSION.md.

### H7 — Role & department editor UI (make config editable)
- **Why:** Roles & Permissions / Departments are read-only today. Admins
  should self-serve without editing `roles_config.py`.
- **Effort:** M. **Depends on:** none.
- **Steps:**
  1. Decision: keep Python config as source of truth vs move to DB. **Option
     A (recommended for v1.1):** write-back endpoint that edits
     `roles_config.py` (atomic rewrite + reload) — no schema change. **Option
     B:** `roles_config` table (needs cache invalidation).
  2. Backend: `PUT /admin/governance` guarded by a new `manage_governance`
     permission (admin/super_admin only), audit-logged.
  3. Frontend: Governance tabs gain edit mode (add/rename departments,
     toggle capability per role).
  4. Tests: write-back persists + reloads, permission gating, invalid role
     name 422.
  5. SESSION.md.

---

## 4. Phase I — Documents & Review (core loop)

### I1 — Inline PDF preview (not just open-in-new-tab)
- **Why:** opening a new tab for every doc feels like a prototype.
- **Effort:** M.
- **Steps:**
  1. Frontend: a `DocumentPreviewDialog` using an embedded `<iframe>`/object
     with the blob URL (no new dep) or `react-pdf` if interactions needed.
  2. Reuse `getDocumentFile`; add prev/next across a list (e.g. approvals
     queue) + zoom controls.
  3. Apply everywhere a View button exists (admin approvals/documents,
     staff clients, client documents).
  4. Verify: tsc + lint; live-view a seeded PDF and a real upload.

### I2 — Bulk approve / bulk reject
- **Why:** admins review dozens of pending docs; clicking each is slow.
- **Effort:** S. **Depends on:** G2's reject-reason infrastructure.
- **Steps:**
  1. Backend: `POST /admin/documents/bulk-approve` and
     `/admin/documents/bulk-reject` taking `{document_ids, reason?}` —
     one transaction, per-doc approval_log rows, per-uploader notifications
     (G3 helper reused).
  2. Frontend: checkboxes on pending cards + "Approve N" / "Reject N (reason)"
     toolbar; reject opens the existing RejectForm.
  3. Tests: mixed-status ids → per-doc correct transitions + notify each
     uploader; invalid id → 404 rollback of the batch.
  4. SESSION.md.

### I3 — Resubmit fixed version after rejection
- **Why:** closes the reject loop — today a rejected doc just sits.
- **Effort:** M. **Depends on:** G1 upload + version bump (exists).
- **Steps:**
  1. Rejected docs become **re-submittable**: uploader (staff/clients) can
     upload a corrected file for the same client/title; it becomes a new
     version with `approval_status=pending` (reuse `index_document` bump).
  2. `GET /documents/{id}/rejections` returns latest rejection reason(s) so
     the upload UI can pre-fill context.
  3. UI: on the staff Clients tab and client Documents, rejected docs show
     the reason + "Upload corrected version" action.
  4. Tests: re-upload after reject → new pending version, old stays rejected,
     reason surfaced.
  5. SESSION.md.

### I4 — Version history + diff viewer
- **Why:** versions exist (v1, v2…) but no UI to see them.
- **Effort:** M. **Depends on:** nothing.
- **Steps:**
  1. Backend: `GET /admin/documents/{id}/versions` (all versions, status,
     uploader, date); extend `GET /documents/{id}/file?version=N`.
  2. Frontend: "Versions" button on admin Documents → list; "Compare" opens
     a side-by-side text diff of the top chunks (plain text, no new dep).
  3. Tests: versions payload, versioned file serving, 404 on missing version.
  4. SESSION.md.

### I5 — Watermark on client document views
- **Why:** compliance-friendly ("Viewed by {client} on {date}") for
  client-facing documents.
- **Effort:** S.
- **Steps:**
  1. Client doc view endpoint stamps a watermark: for PDFs, overlay text via
    `PyPDF2`/`pypdf` when generating the served copy (batch-friendly — can
    cache the watermarked file); for images, simple PIL overlay.
  2. Staff/admin views stay clean (no watermark).
  3. Tests: watermarked bytes differ, watermark contains viewer identity,
    staff view unaffected.
  4. SESSION.md.

### I6 — PII check / redaction flag before client-facing publish
- **Why:** mortgage docs are sensitive; clients see only approved docs.
- **Effort:** M.
- **Steps:**
  1. In `ingest_batch.py` (batch-only, guardrail rule 5): a `pii_check.py`
     scanner flags likely PII (SSN/DOB/address patterns, emails) per chunk —
     heuristic, no LLM.
  2. Store `pii_flagged` on document/chunks; admin approval queue shows the
     flag; approve-with-flag requires an explicit "publish anyway" checkbox.
  3. Tests: scanner finds seeded patterns, flag flows through approval,
     client-facing list excludes nothing silently.
  4. SESSION.md.

### I7 — Drag-and-drop multi-file upload
- **Why:** UX polish for staff + admin upload.
- **Effort:** S.
- **Steps:**
  1. A reusable `FileDropzone` component (native DnD events + input fallback).
  2. Admin Documents + staff Clients upload + client Documents use it; upload
     multiple files sequentially with progress per file.
  3. Verify: tsc + lint; live upload 3 files at once.

### I8 — Document tags/categories taxonomy
- **Why:** richer browse/filtering than free-string doc_type/department.
- **Effort:** M.
- **Steps:**
  1. Schema: `tags` + `document_tags` tables (or a single `text[]` column —
     prefer column for v1.1: `documents.tags text[]`). Admin-editable.
  2. Endpoints: `PUT /admin/documents/{id}/tags`; `GET /admin/tags`
     (aggregate counts). Tag filtering in admin Documents + client documents.
  3. Tests: add/remove tags, invalid tag 422, filter counts.
  4. SESSION.md.

---

## 5. Phase J — Search & Knowledge

### J1 — Search result highlighting (matched terms)
- **Why:** standard expectation; shows *why* a result matched.
- **Effort:** S. **Depends on:** nothing (search already returns match
  positions if BM25/vector exposes them; otherwise highlight via token
  overlap client-side).
- **Status: DONE** (2026-08-15).
- **Steps:**
  1. Backend: include per-excerpt match terms (`matched_terms`) from the
     hybrid query (BM25 `ts_headline` or lexical token overlap).
  2. Frontend: highlight those terms in excerpt + summary text (safe React
     rendering — no `dangerouslySetInnerHTML` with raw HTML; use token
     splitting).
  3. Tests: matched_terms present and correct; highlight helper unit test.
  4. SESSION.md.

### J2 — Faceted filters in chat (dept, doc type, date, client)
- **Why:** richer, narrower answers for staff.
- **Effort:** M. **Depends on:** nothing.
- **Status: DONE** (2026-08-15).
- **Steps:**
  1. `POST /search` gains optional `filters: {departments?, doc_types?,
     date_from?, date_to?, client_id?}` — folded into the existing SQL
     WHERE (guardrail rule 1).
  2. Chat UI: a collapsible filter bar (staff only; clients auto-scoped).
  3. Tests: each filter narrows results correctly + RBAC still holds
     (staff can't filter to clients they're not assigned).
  4. Benchmark: filter changes reduce candidate set only — no ranking/weight
     change, but re-run per rule 7 if any weight changes.
  5. SESSION.md.

### J3 - Was this helpful? feedback → ranking loop

- **Why:** feedback is stored but never used. Per CLAUDE.md rule 7, wire it to ranking weights with a benchmark.
- **Effort:** M.
- **Steps:**
  1. feedback rows already carry query+doc ids. Add an aggregation step: a scoring query counts positive/negative per (query, doc).
  2. Create evaluation/run_benchmark.py support for a feedback-weighted variant of the scoring function; compare against baseline.
  3. Apply the proven delta to ranking/weights_config.py + record the before/after report in evaluation/reports/.
  4. Admin Analytics gains a "feedback ratio by doc" view.
  5. Tests: aggregation query, weight application, report artifact exists.

- **Status: DONE** (2026-08-15). Feedback aggregation proved no improvement over baseline; feedback_boost stays 0.0### J4 — Autocomplete / related-query suggestions as you type
- **Why:** polished chat UX (and reduces no-answer queries).
- **Effort:** S.
- **Status: DONE** (2026-08-15).
- **Steps:**
  1. Backend: `GET /search/suggest?q=…` — prefix match over query terms +
     top related_questions from past successful queries (distinct, dept-scoped).
  2. Frontend: dropdown under the chat input (debounced), Enter selects.
  3. Tests: suggestion scoping (client sees own-scope), empty → empty list.
  4. SESSION.md.

### J5 — No-answer / low-confidence spike alerting
- **Why:** operations visibility into retrieval health.
- **Effort:** S.
- **Status: DONE** (2026-08-15).
- **Steps:**
  1. In the batch path (or a `scripts/report_gaps.py` run via systemd timer —
     note: must be a script, not in-process), aggregate the last 24h of
     `no_answer`/`partial` audit rows.
  2. Create a notification row for admins when the rate crosses a threshold
     (config in `response/confidence_thresholds.py` style).
  3. Tests: aggregation, threshold trigger, notification row.
  4. SESSION.md.

### J6 — Document popularity analytics (which docs answer queries)
- **Why:** data-driven content decisions.
- **Effort:** M.
- **Status: DONE** (2026-08-15).
- **Steps:**
  1. Aggregate from audit_log (query → source document ids) + feedback:
     answered queries per doc, positive/negative ratio, distinct users.
  2. Admin Analytics gains "Top documents by answers" + "Underperforming
     docs" charts.
  3. Tests: aggregation correctness with seeded audit rows.
  4. SESSION.md.

### J7 — Saved searches / search history (per user)
- **Why:** staff re-run the same queries daily.
- **Effort:** S.
- **Status: DONE** (2026-08-15).
- **Steps:**
  1. Table `saved_searches(user_id, query, filters, created_at)`; staff-only
     CRUD endpoints (RBAC in WHERE).
  2. Frontend: "Save this search" + a saved-searches list on the chat page.
  3. Tests: CRUD scoping, max count guard (e.g. 50).
  4. SESSION.md.

### J8 — Synonym/alias management
- **Why:** domain aliases ("mortgage"/"home loan", "DTI"/"debt-to-income")
  improve recall without retraining.
- **Effort:** M.
- **Steps:**
  1. Table `synonyms(canonical, alias)`; `query_processing` expands aliases
     into the BM25/vector query (documented, no LLM).
  2. Admin Knowledge tab: synonym CRUD (bulk-import CSV).
  3. **Benchmark before/after** on the 20-question set (rule 7) — report in
     `evaluation/reports/`.
  4. Tests: expansion in query text, admin CRUD, benchmark report.
  5. SESSION.md.

---

## 6. Phase K — Client Experience

### K1 — Document checklist ("what's still needed")
- **Why:** huge perceived value — clients see exactly what the mortgage
  needs next.
- **Effort:** M.
- **Steps:**
  1. Schema: `case_document_requirements(case_id, name, description,
     required_from, status)` where `status` is derived (required /
     pending / received / approved).
  2. Backend: derive checklist from case + its documents (received =
     any approved/pending doc matching the requirement) + seed a default
     checklist per case type.
  3. Client Home/My Case gains a checklist card; staff can add/remove items.
  4. Tests: derivation logic, staff CRUD, client read-only.
  5. SESSION.md.

### K2 — Client uploads with required metadata fields
- **Why:** cleaner ingestion — today a client upload has no metadata.
- **Effort:** M.
- **Steps:**
  1. Client upload form requires doc_type + title + (optional) case/property
     from their own records; sidecar already supports these fields (G1).
  2. `client.py` upload validates required fields; keep pending→approval flow.
  3. Tests: missing fields 422, sidecar carries metadata.
  4. SESSION.md.

### K3 — Application-status timeline (visual)
- **Why:** the client Cases view is a list; a visual timeline communicates
  progress.
- **Effort:** M.
- **Steps:**
  1. Backend: `GET /client/cases/{id}/timeline` — ordered status events
     (from `case_events`/workflows) with dates.
  2. Frontend: a vertical timeline component (shadcn-ish, no new dep) on
     My Case.
  3. Tests: ordering, scoping to own case.
  4. SESSION.md.

### K4 — Client profile settings
- **Why:** change password + contact details + notification prefs.
- **Effort:** S.
- **Steps:**
  1. Backend: `PATCH /client/me` (contact fields, password via H6 helper);
     notification-prefs per type (reuse `notifications` type strings).
  2. Frontend: Client Settings view (nav item or in Home).
  3. Tests: update + scoping + password rules.
  4. SESSION.md.

### K5 — E-sign / document request (large)
- **Why:** real differentiator; builds on notifications + approvals.
- **Effort:** L. **Depends on:** K1, G3 notifications.
- **Steps:**
  1. `signature_requests(case_id, document_id, requested_from, token,
     signed_at)` — staff request a signature; client gets a notification +
     a signing view.
  2. Signature = typed name + consent checkbox + timestamp (legally
     lightweight; no third-party), or integrate DocuSign later.
  3. Signed PDF baked via `pypdf` (batch-safe) and version-bumped as approved.
  4. Tests: request flow, signing, signed-PDF artifact, notification.
  5. This is its own mini-phase — schedule after H and I are done.

---

## 7. Phase L — Staff & Operations

### L1 — Client 360 view
- **Why:** staff constantly jump between tabs; one screen of everything wins.
- **Effort:** M.
- **Steps:**
  1. Backend: `GET /staff/clients/{id}/360` — client, properties, cases
     (+timeline), documents with status, conversations, recent notifications,
     checklist (K1).
  2. Frontend: a Client 360 tab or drill-down from the Clients tab.
  3. Tests: payload completeness + assignment scoping (staff only assigned;
     admin all).
  4. SESSION.md.

### L2 — Task assignment to teammates
- **Why:** tasks are derived from workflows only today; real teams assign.
- **Effort:** M. **Depends on:** workflows.
- **Steps:**
  1. Schema: `tasks(id, case_id, title, description, assignee_id, due_at,
     status, created_by)` — kept separate from derived workflow tasks.
  2. Staff Tasks tab: create/assign/reassign/complete; assignee gets a
     notification; overdue shown (L3).
  3. Tests: assignment scoping, notification on assign, status transitions.
  4. SESSION.md.

### L3 — Overdue / SLA flags + notifications
- **Why:** drives urgency; ties into existing notifications.
- **Effort:** M.
- **Steps:**
  1. Workflows/tasks gain `due_at` + `sla` config; a `scripts/check_overdue.py`
     batch job (systemd timer) creates overdue notifications.
  2. Staff Dashboard shows "overdue" stat + red flags on items.
  3. Tests: overdue detection, notification creation, dashboard count.
  4. SESSION.md.

### L4 — Config-driven workflow definitions
- **Why:** today workflows are advance-only with fixed stages.
- **Effort:** L. **Depends on:** L3 (due/SLA on stages).
- **Steps:**
  1. `workflow_definitions(name, stages[], transitions, sla)` config
     (Python data like `roles_config.py`) → DB table for runtime.
  2. Staff/admin can define stages + who can advance (role-capability check).
  3. Admin Workflows view (currently disabled "Cases" → add real view).
  4. Tests: definition CRUD, transition validation, RBAC on advance.
  5. SESSION.md.

### L5 — Message templates
- **Why:** fast replies to common client questions.
- **Effort:** S.
- **Steps:**
  1. Table `message_templates(name, body, department)`; staff-only CRUD +
     a picker in the Collaboration composer.
  2. Tests: CRUD + scoping.
  3. SESSION.md.

### L6 — Calendar / appointments (optional stretch)
- **Why:** scheduling for loan officers.
- **Effort:** L. Defer until H–K shipped; single `appointments` table + a
  simple week view, notifications on create/reminder.

---

## 8. Phase M — System / Admin / Ops

### M1 — Audit log export (CSV/JSON)
- **Why:** compliance requests land constantly.
- **Effort:** S.
- **Steps:**
  1. `GET /admin/audit/export?<same filters>` streams CSV (or JSON) with the
     current filters applied; admin-only, audit-logged.
  2. Frontend: "Export" button on the Audit tab.
  3. Tests: format + filters + 403 for staff.
  4. SESSION.md.

### M2 — Database migrations (Alembic)
- **Why:** schema evolves every phase (Phase G added 4 tables); manual
  `ensure_schema` make-and-forget is risky for real deployments.
- **Effort:** M.
- **Steps:**
  1. Add Alembic; baseline from the current schema; `ensure_schema` becomes
     a dev-only bootstrap; compose/systemd run `alembic upgrade head` on
     backend start.
  2. Every future schema change ships a migration.
  3. Tests: CI applies migrations on a fresh DB and the suite passes.
  4. Docs: `Final_System_Design.md` + SESSION.md.
  - *Note:* CLAUDE.md mentions Alembic was dropped as dead artifact — adding
    it back is a small design decision; flag it (DEC-4).

### M3 — Scheduled pgvector/index maintenance
- **Why:** search slows as data grows (wasteful bloat, stale stats).
- **Effort:** S.
- **Steps:**
  1. `scripts/maintenance.py`: `VACUUM ANALYZE documents, document_chunks`,
     `REINDEX` pgvector HNSW when bloat > threshold, refresh FTS.
  2. Run via systemd timer (script, not in-process).
  3. Tests: dry-run + idempotency.
  4. SESSION.md.

### M4 — Structured logs + request tracing
- **Why:** debugging live issues (esp. with `--workers 1` + idle-stop).
- **Effort:** M.
- **Steps:**
  1. JSON structured logging (request id, user id, latency, route) via
     middleware; a `x-request-id` header echoed to the client.
  2. Log rotation via existing systemd journald; no new container.
  3. Tests: middleware attaches id, logs include user scope.
  4. SESSION.md.

### M5 — Data retention / GDPR export
- **Why:** regulatory; clients can request their data.
- **Effort:** M.
- **Steps:**
  1. `GET /client/me/export` → JSON of their profile, properties, cases,
     documents, conversations (their messages), feedback; admin
     `GET /admin/clients/{id}/export`.
  2. Retention: `scripts/retention.py` applies configured retention per
     table (batch), audit-logged.
  3. Tests: export completeness + scoping, retention dry-run.
  4. SESSION.md.

### M6 — Backup/restore automation
- **Why:** no backups today — a data-loss incident is unrecoverable.
- **Effort:** M.
- **Steps:**
  1. `scripts/backup_db.py`: `pg_dump` (schema+data) to a rotating local dir
     + optional object store; `scripts/restore_db.py` documented.
  2. systemd timer nightly; restore tested in CI/staging.
  3. Docs: runbook in `infra/README.md`.
  4. SESSION.md.

### M7 — Health / system status page
- **Why:** operational visibility.
- **Effort:** S.
- **Steps:**
  1. `/health` extended (DB ping, storage writable, last ingest time);
     admin Dashboard shows a system-status card.
  2. Tests: health payload fields.
  3. SESSION.md.

### M8 — Feature flags
- **Why:** ship half-built features safely.
- **Effort:** S.
- **Steps:**
  1. `feature_flags(name, enabled)` table + `app/config` loader + a tiny
     `is_enabled(name)` used by the most-risky new endpoints.
  2. Admin Settings toggles them (audit-logged).
  3. Tests: flag gating.
  4. SESSION.md.

---

## 9. Phase N — Polish / DX (cross-cutting, do anytime)

### N1 — Dark mode
- **Effort:** S. Tailwind `dark:` variant + `next-themes`-style toggle (no
  SSR issues — this app is static-export; use a `useEffect`-based theme
  provider like the hydration fix in Session 11). Persist pref, respect
  `prefers-color-scheme`.

### N2 — i18n framework
- **Effort:** S–M. Introduce `next-intl` (or a tiny dictionary) for the
  static pages; ship English first, structure for translation. Keep JWT/API
  responses language-neutral.

### N3 — PWA / mobile pass
- **Effort:** M. Add a manifest + service worker (static export friendly),
  make the client portal genuinely mobile-optimized (touch targets,
  responsive tables), offline shell for cached pages.

### N4 — Accessibility audit
- **Effort:** S–M. Automated (axe via a dev script) + manual pass: focus
  traps in dialogs, contrast, aria labels, keyboard nav for tabs/sidebar.

### N5 — Onboarding tour + empty states
- **Effort:** S. First-login hint tour for staff/admin (3 steps each),
  better empty states (upload CTA when KB empty, sample query chips).

### N6 — Real-time notification stream
- **Effort:** S–M. SSE endpoint `GET /notifications/stream` (reuse the
  Session-6 streaming approach) so the bell updates without polling.

### N7 — Loading/error state polish
- **Effort:** S. Consistent skeletons, error banners with retry, and
  optimistic updates on the most-clicked actions (approve, send message).

---

## 10. Recommended build order (dependencies)

1. **Phase H** first — it's the security foundation (H1 → H2 → H3 → H5 → H6
   → H4 → H7). H2 needs DEC-3 (email) — start that decision early.
2. **Phase I** — core-loop features that directly grow perceived value.
   I7 and I1 are quick wins; do them first inside the phase.
3. **Phase J** — search quality; J1 + J4 are quick, J3 + J8 need benchmarks.
4. **Phase K** — client-facing wins; K4 is quick.
5. **Phase L** — staff ops; L5 quick, L4 large.
6. **Phase M** — ops hardening; M6 (backups) and M1 are the priorities.
7. **Phase N** — polish, interleaved whenever there's a gap.

**Quick wins available immediately** (do not block on anything): H3, H5, H6,
I7, I1, J1, J4, J5, K4, L5, M1, M7, N1, N5, N7.

---

## 11. Decisions pending user sign-off (gate before starting those items)

| ID | Item | Blocks | Status |
|---|---|---|---|
| DEC-1 | Optional LLM "cite-with-LLM" mode (yes/no + endpoint/UI) | — | **Closed 2026-08-19: No** (verbatim-only). Hosted-API seam `app/llm/` built and wired into `search.py`, gated OFF by `ASTO_LLM_ENABLED=false` — a future decision just flips the flag |
| DEC-3 | Email/SMTP provider + which events email | H2, (L7 email notifications) | **Landed 2026-08-19** — generic SMTP + console fallback (`app/email/mailer.py`); reset link + notification emails wired |
| DEC-4 | Reintroduce Alembic migrations | M2 | **Landed 2026-08-19** — M2 done |

---

## 12. Feature tracker

**Phase H — Security & Auth**
- [x] H1 JWT in HttpOnly cookie + refresh rotation + CSRF
- [x] H2 Forgot-password / reset
- [x] H3 Login rate limiting + lockout
- [x] H4 Admin 2FA (TOTP)
- [x] H5 Session revocation (logout-all / admin kill)
- [x] H6 Password change UI (staff + client)
- [x] H7 Role & department editor UI (Option A: write-back to roles_config.py)

**Phase I — Documents & Review**
- [x] I1 Inline PDF preview
- [x] I2 Bulk approve / bulk reject
- [x] I3 Resubmit fixed version after rejection
- [x] I4 Version history + diff viewer
- [x] I5 Watermark on client doc views
- [x] I6 PII check / redaction flag
- [x] I7 Drag-and-drop multi-file upload
- [x] I8 Document tags/categories

**Phase J — Search & Knowledge**
- [x] J1 Search result highlighting
- [x] J2 Faceted filters in chat   
- [x] J3 - DONE Feedback → ranking loop (benchmark-gated)
- [x] J4 Autocomplete / related-query suggestions 
- [x] J5 No-answer spike alerting
- [x] J6 Document popularity analytics
- [x] J7 Saved searches
- [x] J8 - DONE Synonym/alias management (benchmark-gated)

**Phase K — Client Experience**
- [x] K1 Document checklist
- [x] K2 Client uploads with metadata fields
- [x] K3 Application-status timeline
- [x] K4 Client profile settings
- [x] K5 E-sign / document request (large)

**Phase L — Staff & Operations**
- [x] L1 Client 360 view
- [x] L2 Task assignment
- [x] L3 Overdue / SLA flags + notifications
- [x] L4 Config-driven workflow definitions (large)
- [x] L5 Message templates
- [x] L6 Calendar / appointments (stretch)

**Phase M — System / Admin / Ops**
- [x] M1 Audit log export
- [x] M2 Alembic migrations (DEC-4: landed — `migrations/` baseline `0001_baseline` reuses `schema.py` DDL; entrypoint runs `alembic upgrade head`; `ensure_schema()` stays as dev bootstrap)
- [x] M3 pgvector/index maintenance
- [x] M4 Structured logs + tracing
- [x] M5 Data retention / GDPR export
- [x] M6 Backup/restore automation
- [x] M7 Health / system status
- [x] M8 Feature flags

**Phase N — Polish / DX**
- [x] N1 Dark mode (Session 38)
- [x] N2 i18n framework (Session 38 — tiny typed dictionary, English first)
- [x] N3 PWA / mobile pass (Session 38)
- [x] N4 Accessibility audit (Session 38 — axe dev script + manual pass)
- [x] N5 Onboarding tour + empty states (Session 38)
- [x] N6 Real-time notification stream (Session 38 — SSE)
- [x] N7 Loading/error state polish (Session 38)

---

*Last updated: 2026-08-19. Every ticked item in this tracker must have a
corresponding SESSION.md entry.*
