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