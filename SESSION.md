# SESSION.md — Progress log

### Session 34 - 2026-08-15 (Phase J complete + Phase K start)

**Done (Phase J finalized):**
- **J1-J7**: all 7 items complete (highlighting, faceted filters, autocomplete, spike alerting, analytics, saved searches). All live-verified against rebuilt containers.
- **J3**: benchmark-gated; comparison report run: linear_0.2_0.8 baseline = 92.8% hit_rate@1; best feedback-weighted variant = 44.8% hit_rate@1 (includes irrelevant chunks of same doc). Proven delta: feedback_boost stays 0.0 - no change to ranking/weights_config.py. Report saved in evaluation/reports/ with before/after delta.
- **J8**: deferred (benchmark-gated, Effort M).

**Transition to Phase K:**
- K1 (Document Checklist) kicked off: schema case_document_requirements(case_id, name, description, required_from, status) derived from case + its documents + seeded defaults per case type. Client Home/My Case gains checklist card; staff can add/remove items.
- **Phase J tracker**: all items in ROADMAP.md tracker now checked (J3 ticked with no proven delta notation, J8 deferred pending future benchmark).

**Noted:**
- No in-process schedulers or background threads added (CLAUDE.md rule 4: `--workers 1` + socket-activated).
- RBAC + version filtering persists in SQL WHERE clause (rule 1).

### Session 35 - 2026-08-16 (Phase K complete + Phase L start)

**Done (Phase K finalized):**
- **K1**: Document checklist — `GET /client/cases/{case_id}/checklist` with clean EXISTS-subquery SQL; `Checklist` component in the client Cases view.
- **K2**: Client uploads with metadata — `clientUploadDocument` sends `doc_type` + `title`; fixed `json.dumps(..., encoding="utf-8")` bug (encoding moved to `write_text`).
- **K3**: Application-status timeline — `GET /client/cases/{case_id}/timeline` + client "View timeline" UI.
- **K4**: Client profile settings — `clients.notification_prefs` column, `PATCH /me` returns updated profile, `ClientProfileCard` in SettingsModal.
- **K5**: E-sign / document request — fixed admin `sign_signature_request` SQL, added client `GET /client/signature-requests` + `POST /client/signature-requests/{id}/sign`, `SignatureRequestsCard` in client Documents view.
- Backend unit suite: 533 passed. Frontend builds clean.

**Phase L started (backend first):**
- **L1**: Client 360 view — `GET /staff/clients/{client_id}/360` (profile, properties, cases+timeline, documents, conversations; SQL-scoped per CLAUDE.md rule 1).
- **L2**: Real tasks CRUD replacing derived `/tasks` — `tasks` table, `_task_visible_scope`, `GET/POST /staff/tasks`, `PATCH /staff/tasks/{id}`; assignee notified on assign, creator notified on complete.
- **L3**: Overdue/SLA — dashboard returns `overdue_workflows` + `overdue_tasks` counts (same visibility scope as `/tasks`).
- **L4**: Config-driven workflow definitions — `GET/POST/DELETE /staff/workflow-definitions` (create/delete admin-only).
- **L5**: Message templates — `GET/POST/DELETE /staff/message-templates` (department-scoped for non-admins).
- **L6**: Calendar/appointments — `GET/POST /staff/appointments` (ISO parse, end > start, department-scoped).

**Noted:**
- Fixed dashboard overdue-task count bug: admin previously got `ANY([])` (always 0); now uses `_task_visible_scope`.
- Added `require_role` import from `app.auth.permissions`; task notifications use `notify_user` (not `notify_admins`).

### Session 36 - 2026-08-18 (Phase L complete)

**Done (Phase L finalized):**
- **L1**: Client 360 view frontend — "360 view" button on each client card + `Client360Tab` drill-down (properties, documents, cases+timeline, conversations).
- **L2**: Staff Tasks tab rebuilt on real tasks — create (title/description/case/assignee/due), complete, mark overdue, stat cards.
- **L3**: Dashboard stat cards now show overdue workflows + overdue tasks.
- **L4**: Definitions tab — list/read, admin create (name/description/stages), admin deactivate.
- **L5**: Templates tab — create (name/body/department), delete, list.
- **L6**: Calendar tab — create/list appointments, sorted by start time.
- Tests: 18 new unit tests for L endpoints (360 scoping, tasks CRUD + notifications, definitions admin-only, template scoping, appointment validation). Backend suite: **551 passed**.
- Live verification: all Phase L routes return 401 unauthenticated through nginx (3011) and backend (8011) — wired correctly.
- ROADMAP.md tracker: K1-K5 and L1-L6 ticked.

**Noted:**
- No in-process schedulers or background threads added (CLAUDE.md rule 4).
- RBAC + version filtering persists in SQL WHERE clause (rule 1).
- All Phase I/J/K/L work remains uncommitted in the working tree (git head: fc9d342 Phase H).

### Session 37 - 2026-08-18 (Phase M — System / Admin / Ops)

**Done (Phase M finalized, M2 deferred):**
- **M1**: Audit log export — `GET /api/v1/admin/audit/export` (CSV/JSON, shared `_audit_filter_clause`, itself audit-logged) + admin Export button. 7 tests.
- **M6**: Backup/restore — `scripts/backup_db.py` / `scripts/restore_db.py` (rotating pg_dump, wrapper-supporting), `asto-backup.service/.timer` + runbook. **Live round-trip verified**: backup → restore into scratch DB (31 tables, 4 users, 2064 audit rows). 8 tests.
- **M7**: `/api/v1/health` now reports DB, storage writability, last ingest, version; admin Dashboard gains a System status card. 7 tests. Live: DB connected, storage writable, last_ingest present.
- **M8**: Feature flags — `feature_flags` table (kept the pre-existing committed DDL), TTL-cached `is_enabled()`, `GET/POST /admin/flags` (audit-logged), Settings-tab toggles, gates the M1 export endpoint. 12 tests. **Live verification caught a real bug**: psycopg `dict_row` unpacks dict keys (not values) with `for name, enabled in rows` → cache stored `{'name': True}`; fixed to `row["name"]`/`row["enabled"]` and the test fake now returns dict rows. Toggle round-trip live-verified.
- **M3**: `scripts/maintenance.py` — `VACUUM (ANALYZE)` + bloat-gated `REINDEX INDEX CONCURRENTLY` (HNSW + FTS GIN), `asto-maintenance.timer` (Sun 04:00). 10 tests. Live dry-run reported bloat 0.3571 (would reindex).
- **M4**: `app/logging/middleware.py` — one JSON log line per request (request_id, method, path, status, latency, user scope) with `x-request-id` echoed to clients. 7 tests. Live: header echoed, JSON lines present in container logs.
- **M5**: GDPR export — `GET /client/me/export` + admin `GET /admin/clients/{id}/export` (profile, properties, cases, documents+content, conversations/messages, feedback, audit; password_hash never included; both audit-logged) + `scripts/retention.py` (per-table policy, dry-run, run itself audit-logged) + `asto-retention.timer` (02:30). 21 tests. Live export built for client 1 (no hash leak, JSON-safe).

**Backend suite:** 623 unit tests passed. A follow-up fix (same session) resolved the 15 pre-existing `test_faceted_filters.py` integration failures: the `synonyms` table was referenced by `hybrid_orchestrator.py` and the admin endpoints but had no DDL anywhere — added `CREATE TABLE IF NOT EXISTS synonyms (id, canonical, alias, UNIQUE(canonical, alias))` to `schema.py` and applied `ensure_schema()` to the dev DB. **Full suite now 705 passed, 0 failed.**

**Frontend:** `tsc --noEmit` clean, `next lint` clean. Both `asto_backend` and `asto_frontend` containers rebuilt and live-verified.

**Noted:**
- M2 (Alembic) deferred per DEC-4 — idempotent DDL (`ensure_schema()`) remains the approach.
- All batch jobs ship as systemd timers on the shared host + manual runs locally; no in-process schedulers (rule 5).
- ROADMAP.md Phase M tracker: M1, M3–M8 ticked; M2 left unticked with a deferred note.

### Session 38 - 2026-08-19 (Phase N — Polish / DX complete)

**Done (Phase N finalized):**
- **N1**: Dark mode — `lib/theme.ts` (persist `asto_theme`, resolve system pref), `ThemeProvider` (hydration-safe), `ThemeToggle` (light→dark→system), no-flash inline script + `suppressHydrationWarning` in the root layout, Appearance card in `SettingsModal`. tsc + lint clean.
- **N2**: i18n — tiny typed dictionary (`lib/i18n/en.ts` with `TranslationKey` via `NestedKeys`) + `translate()`/`useI18n()` hook; applied to the login page (all four modes: login/2fa/forgot/reset). JWT/API payloads stay language-neutral. tsc + lint clean.
- **N3**: PWA/mobile — `public/manifest.webmanifest`, `icon.svg` + `icon-maskable.svg`, static-export-friendly `sw.js` (app-shell cache, network-first for `/api/`, offline JSON fallback), `offline.html`, `ServiceWorkerRegister` client component, manifest/theme-color metadata. Mobile pass: client portal already uses h-16 bottom tabs; bumped SearchBar send button to 44px (w-11 h-11) + urgency toggle, widened input padding. tsc + lint clean.
- **N4**: Accessibility — `scripts/axe-audit.mjs` + `npm run a11y` (Playwright + `@axe-core/playwright`; graceful skip if chromium missing) over `/`, `/login/`, `/admin/`; manual pass: skip-to-content link + `#main-content` target in `AppShell`, `aria-hidden` on the drawer backdrop, larger `accent-primary` feature-flag checkboxes. tsc + lint clean.
- **N5**: Onboarding + empty states — `OnboardingTour` (3-step staff/admin variants, localStorage-gated, Radix Dialog for focus trap) mounted in admin + staff pages; KB-empty CTA in admin Documents tab ("Upload documents above…"); client sample query chips already existed via `HeroSection`. tsc + lint clean.
- **N6**: Real-time notifications — `GET /api/v1/staff/notifications/stream` (SSE: `hello` with unread_count + latest_id, `notification` per new row id > since_id/Last-Event-ID, `ping` keepalives; poll-and-push via `asyncio.to_thread`; `X-Accel-Buffering: no`). Reuses the Session-6 streaming transport. Frontend `openNotificationStream()` (fetch-based SSE, returns abort) replaces the 60s bell poll in the staff page, with baseline-vs-new badge accounting, auto-reconnect w/ backoff resuming from last id, and live dialog refresh. 9 unit tests. **Live-verified**: hello + notification pushed for a real admin token; 401 unauth.
- **N7**: Loading/error polish — `DashboardSkeleton` component (admin + staff dashboards), Retry buttons on error banners (Approvals tab, admin dashboard, ConversationThread), optimistic approve in the admin approvals queue (with rollback on failure), optimistic send in `ConversationThread` (temp negative id, draft restored on failure). tsc + lint clean.

**Backend suite:** 632 unit + 82 integration = **714 passed, 0 failed** (9 new N6 tests; integration requires the dev Postgres running — started `asto_postgres` to confirm).

**Frontend:** `next lint` clean repo-wide, `tsc --noEmit` clean. Both images rebuilt (`astov1-asto-backend`, `astov1-frontend`) and containers started; live-verified: health 1.1.0 healthy, admin/staff/login 200, `sw.js` + `manifest.webmanifest` served, SSE stream pushed a real notification.

**Noted:**
- The SSE stream holds the socket-activated worker open while a bell is connected — the same trade-off the Session-6 search stream already makes; documented in the endpoint docstring.
- ROADMAP.md Phase N tracker: N1–N7 all ticked (Session 38). Phase M tracker unchanged (M2 still deferred per DEC-4).
- Remaining after Phase N: M2 (Alembic, gated on DEC-4), DEC-1 (optional LLM cite-with-LLM mode), DEC-3 (email/SMTP provider — blocks H2 email delivery + L7 email notifications).
### Session 39 - 2026-08-19 (Remaining items: DEC-3 email + DEC-4/M2 Alembic done)

**Done (closing out the remaining, decision-gated items):**
- **DEC-3 - Email (generic SMTP + console fallback):** new `app/email/mailer.py` (`send_email`, `smtp_configured`; provider-agnostic smtplib with STARTTLS or implicit-TLS-465, 10s timeout, never raises - a failed send re-logs the message at INFO so requests never break). Config: `smtp_host/port/user/password/from/use_tls/use_ssl` in `config.py` + `.env.example`. **H2**: `deliver_reset_link` now sends a real email (expiry + link) through the mailer, keeping the greppable `PASSWORD_RESET` log line. **L7**: `notify_user` mirrors every in-app notification to email (looks up the recipient address, title/body/link) - gated on `smtp_configured()` so the extra DB read never runs in tests or SMTP-less dev. 11 unit tests (`test_email_delivery.py`: fallback, SMTP, SSL, failure-no-raise, reset link, notification mirror incl. link + skip paths).
- **DEC-4 / M2 - Alembic:** added `alembic==1.19.1` (SQLAlchemy 2.0.52 transitive). `alembic.ini` + `migrations/env.py` (resolves `ASTO_DATABASE_URL` from settings, translated to `postgresql+psycopg://` for SQLAlchemy's psycopg3 dialect; programmatic `sqlalchemy.url` override supported) + `script.py.mako`. Baseline `0001_baseline` imports `app.db.postgres.schema` statement lists verbatim - zero drift, `CREATE IF NOT EXISTS` semantics make it authoritative on a fresh DB and a no-op on an existing one; `downgrade()` drops tables in reverse creation order. `ensure_schema()` stays as the dev bootstrap (`ASTO_AUTO_CREATE_SCHEMA`); `docker-entrypoint.sh` now runs `alembic upgrade head` before uvicorn (the deploy path, `set -e`). schema.py docstring updated (baseline source of truth, frozen). 4 integration tests (`test_migrations.py`): scratch DB `asto_mig_test` created/dropped with FORCE, upgrade head builds 33 tables + pgvector column, stamps `0001_baseline`, idempotent re-run.

**Backend suite:** 643 unit + 86 integration = **729 passed, 0 failed** (11 new email + 4 new migration tests).

**Live verification:** `alembic upgrade head` run against a fresh scratch DB (33 tables, vector column, stamped) and against the dev `asto_assistant` (no-op + stamped `0001_baseline`); scratch DB dropped after.

**Frontend:** unchanged this session (email + migrations are backend-only).

**Noted:**
- DEC-1 (optional LLM cite-with-LLM mode) remains **open** - awaiting the user's yes/no; it is the last decision-gated item. Everything else on the tracker is now ticked except DEC-1.
- SMTP is unconfigured by default; emails fall back to console logs (dev behavior preserved). Configure ASTO_SMTP_* to enable real delivery.
- Containers not yet rebuilt for the entrypoint change - do `docker compose build asto-backend` + `up -d` to pick up `alembic upgrade head` on start.

### Session 40 - 2026-08-19 (DEC-1 closed as No; hosted-API seam built, OFF)

**Decision:** DEC-1 is closed as **No for now** - the request-serving path keeps the strict verbatim guarantee and never calls an LLM. Per the user's instruction, the hosted-API path is built and *ready* so a future flip of `ASTO_LLM_ENABLED` activates it.

**Done (the ready-but-off seam):**
- **Config + env:** `llm_enabled` (default False, master switch), `llm_provider_url`, `llm_api_key`, `llm_model`, `llm_timeout_s`, `llm_max_tokens`, `llm_temperature` in `config.py` + `.env.example`. Provider URL is OpenAI-compatible (works with OpenAI, Azure, Anthropic-via-gateway, self-hosted vLLM).
- **`app/llm/provider.py`:** `LLMClient` - thin OpenAI-compatible `POST {base_url}/chat/completions` client on stdlib `urllib` (zero new deps), `LLMError` for HTTP/network/parse failures, never crashes a request.
- **`app/llm/citations.py`:** the hook. `maybe_apply_citation_mode(package, query_text)` returns the package **unchanged** while `llm_enabled` is false (pure pass-through, no LLM call, no behavior change). If enabled: builds the citation prompt from retrieved excerpts (`build_citation_prompt`, `[n]` indices), calls the provider, parses sentences + per-sentence `[n]` citations mapped to source titles (`parse_citation_answer`), sets `package.answer` + `package.citations`. Provider failure is logged and the package is returned unchanged (best-effort).
- **Wiring:** `ResponsePackage.citations` field; `SearchResponse.citations` + `_serialize` include it (empty by default); the single call site is in `app/api/v1/search.py` right after `route_by_confidence`.
- **15 unit tests** (`test_llm_citation_hook.py`): off-state is inert (same object returned, no provider call), on-state synthesizes + cites, empty-url skip, provider-failure unchanged, prompt building, sentence parsing (attached + space-separated markers, out-of-range ignored), provider wire format/parse/errors.

**Backend suite:** 658 unit + 86 integration = **744 passed, 0 failed** (15 new).

**Frontend:** unchanged.

**Noted:**
- Enabling the mode later sends retrieved excerpts to the configured provider - the compliance trade-off DEC-1 documented. The flag must stay false until that decision is deliberately revisited (guarded in config docstring).
- Remaining after this: nothing decision-gated. Housekeeping only - all work since Phase H is still uncommitted (git head fc9d342); `npm run a11y` needs `npx playwright install chromium` once.
