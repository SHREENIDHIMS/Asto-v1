# Asto — Session Summary

> **Always read this file at the start of every session and update it at the
> end.** It is the single source of truth for *where the project is now* and
> *what to do next*. Companion files: `TEMPLATE.md` (how we work), `CLAUDE.md`
> (hard rules), `SKILL.md` (build order).

---

## Project Identity (DO NOT CHANGE)

- **Product name:** Asto (renamed from Hexta / HeXta on 2026-08-08 — see Session 1)
- **Positioning:** Dual-audience **Knowledge & Process Assistant**
  1. Internal staff/process efficiency (role, department, and assigned
     client/case scope).
  2. Authenticated external clients — secure self-service access to *their own*
     documents, properties, mortgage/cases, status, requirements, and
     end-to-end process info.
- **Core philosophy (non-negotiable):** *"Find the right information, don't
  generate new information."* No LLM in the serving path. Every response field
  is a verbatim/near-verbatim excerpt with a source citation.

---

## Architecture Snapshot (where we are)

- **Backend:** FastAPI + psycopg3 + pgvector (BM25 + vector in a single SQL
  query), JWT + RBAC (staff **and** client audiences), `--workers 1`,
  socket-activated, idle-stopped.
- **Dual-audience (Session 3):** clients log in via `/auth/client-login`; JWT
  carries `audience` + `client_id`; `get_current_user` resolves both tables.
  Client-scoped API under `/client/*`. Approval workflow under `/admin/documents/*`
  (pending/approve/reject + `approval_log` trail); new ingestions enter as `pending`.
- **Frontend:** Next.js 14 static export (`output: 'export'`), Tailwind +
  shadcn/ui, client-side JWT. Chat view at `/` (bubbles, 24h localStorage
  history), Staff/Client login tabs, client portal at `/portal`, admin
  dashboard at `/admin` (approvals, documents+upload, users, clients,
  analytics). True SSE streaming (Session 6): `POST /search/stream` pushes
  `status` → `fact`/`sentence` → `result` events as content is produced;
  staff + client chat render facts/sentences progressively.
- **Storage:** One Postgres per host, one database per project
  (`asto_assistant`). NO Qdrant / Redis / MinIO (deliberately removed).
- **Ingestion:** Batch-only (`ingest_batch.py`), never in the request path.
- **Evaluation:** `evaluation/run_benchmark.py` + 20-question dataset; CI gates
  ranking/confidence changes.

### Ports (updated 2026-08-08 — moved off common defaults to avoid conflicts)

| Service | Host port | Notes |
|---|---|---|
| Postgres | **5433** | container internal still 5432 |
| Backend (FastAPI) | **8011** | systemd socket + docker-compose |
| Frontend (Next.js/nginx) | **3011** | docker maps 3011→80 |
| Shared-host nginx | 80/443 | host-level, unchanged |

CI workflows keep 5432 internally (isolated runners). Update any new docs/config
to these ports.

---

## Current State Audit (Session 1, 2026-08-08)

**What exists and works:**
- Full retrieval pipeline wired end-to-end: query_processing → hybrid_search →
  RRF → rerank(optional) → package_builder → validate → audit.
- **Extractive summary added (2026-08-08):** `response/summarizer.py` uses Sumy
  TextRank to select up to 4 sentences verbatim from the top excerpts, each
  mapped back to its source. Relaxed CLAUDE.md doctrine accordingly (no LLM,
  no abstractive synthesis — extractive-only, deliberate exception). Wired into
  `ResponsePackage`, `/search` response, and frontend `ResponsePackageCard`.
- RBAC enforced in SQL WHERE clause (with integration tests).
- Schema, audit log, feedback, knowledge gaps, seed scripts, evaluation suite.
- Audit findings from `AUDIT.md` (25 items) were largely remediated in prior
  work (confidence calc, auth gating, weighted score, OCR, chunkers, bcrypt,
  pagination, etc.) — re-verify, don't assume.

**What does NOT exist yet (this is the real work ahead):**
1. ~~**Dual-audience model**~~ — schema (clients/properties/cases/assignments) + RBAC filters
   exist; client AUTH + client-scoped API added (Session 3, see below).
2. ~~**Document approval workflow**~~ — schema + approval API + pending-on-ingest + audit
   trail implemented (Session 3).
3. ~~**Client (external) auth**~~ — client login, audience-scoped JWT, client endpoints
   implemented (Session 3).
4. ~~**ChatGPT-style chat UX**~~ — **DONE (Session 4):** chat thread view at `/`,
   assistant bubbles, 24h localStorage history, typing indicator. True SSE
   streaming **DONE (Session 6):** `/search/stream` pushes `status`/`fact`/
   `sentence`/`result` events progressively; staff + client chat render them.
5. ~~**Admin dashboard**~~ — **DONE (Session 4):** `/admin` with approvals queue,
   documents + upload, users, clients + assignments, knowledge-gap analytics.
   Document view/download verified live (Session 6). Analytics *endpoints*
   verified live and charted in the `/admin` Analytics tab.
6. ~~**Runtime verification**~~ — **DONE (Session 2):** `.venv` (3.11) installed,
   unit (107) + integration (7) tests pass, compose up healthy, benchmark run.

---

## Session Log

### Session 14 — 2026-08-12 (Phase H1 — HttpOnly session cookie + refresh rotation)

**Design decision (user-approved plan, `docs/ROADMAP.md`):** the access JWT
is kept **in JS memory only** (auto-restored on load) and removed from
localStorage; the long-lived session credential moves to an **HttpOnly
`asto_refresh` cookie** (SameSite=Lax, rotated on use, stored hashed). This
closes the XSS token-theft hole (nothing persistent readable by JS) and lays
the refresh-token groundwork for H5's logout-all/revocation.

**Backend:**
- `db/postgres/schema.py`: new `refresh_tokens` table — only the **SHA-256
  hash** of each token is stored (`token_hash` UNIQUE), plus `user_id` XOR
  `client_id` per audience, `expires_at`, soft `revoked_at`; index by
  (user_id, client_id, revoked_at).
- `auth/jwt_handler.py`: `new_refresh_token()` (opaque `token_urlsafe(48)`,
  never a JWT) + `hash_refresh_token()`.
- `api/v1/auth.py`:
  - `POST /auth/login` (+ legacy `/auth/client-login`) now also issues a
    refresh token and sets the HttpOnly cookie; the JSON body still returns
    the access JWT (bearer auth path unchanged for all 58 api-client calls).
  - `POST /auth/refresh` — exchanges the cookie for a fresh access JWT
    **and rotates** the refresh token (old row revoked, new issued); active
    identity re-resolved from DB for current role/claims. Rejects
    unknown/revoked/expired tokens (expired rows are revoked too).
  - `POST /auth/logout` — revokes the presented token + clears the cookie.
  - `POST /auth/logout-all` (bearer-authenticated) — revokes every refresh
    row for the current identity (H5 hook).
  - CSRF: `require_csrf` dependency checks the `X-Asto-CSRF: 1` header on
    the cookie-authenticated endpoints (SameSite=Lax is the primary defense;
    the header is defense-in-depth).
- `config.py`: `refresh_token_ttl_days=30`, cookie name/secure/samesite
  settings. `cors_origins` default is now explicit origins
  (`http://localhost:3011,http://127.0.0.1:3011`) because browsers reject
  `*` + credentials.
- `docker-compose.yml`: backend env passes explicit `ASTO_CORS_ORIGINS` +
  `ASTO_AUTH_COOKIE_SECURE`/`ASTO_AUTH_COOKIE_SAMESITE` (Secure must be
  enabled behind TLS in production).
- Tests: new `tests/unit/test_h1_http_cookie.py` (11 tests) — login sets
  HttpOnly cookie + stores only the hash, invalid creds set no cookie,
  refresh requires CSRF, rotation revokes old + issues new, revoked token
  401, logout revokes + clears, logout-all revokes per user, refresh-token
  helpers. Full suite: **401 passed** (was 390).

**Frontend:**
- `lib/auth.ts` rewritten: in-memory token (`getToken`/`storeToken`/
  `clearToken`), new `restoreSession()` (re-exchanges the cookie on page
  load/hard reload), `getSession()` restores then verifies. No
  localStorage persistence anywhere.
- `lib/api-client.ts`: new `apiFetch()` wrapper adds
  `credentials:'include'` to **all** requests (58 sites) so the cookie
  travels and Set-Cookie is accepted; new `refreshSession()`, `logout()`,
  `logoutAll()`.
- Gates on `/`, `/admin`, `/staff`, `/client` converted to
  `restoreSession().then(...)` so a hard refresh restores the session
  before routing/data-load; logout handlers now call `logout()` (best-effort
  cookie revoke) + `clearToken()`.
- `tsc --noEmit` clean, ESLint clean, `npm run build` clean.

**Live verified** (rebuilt + recreated `asto-backend` + `frontend`): admin
login via curl cookie jar → JWT in body + `asto_refresh` HttpOnly cookie;
`/auth/refresh` with CSRF header → fresh JWT + **rotated** cookie;
replaying the old token → `401 Invalid refresh token`; missing CSRF header →
`403 CSRF check failed`; `/auth/logout` → `{ok:true}` and the cookie is
cleared; `refresh_tokens` rows show only 64-char hashes with revoked flags
for rotated tokens; all routes 200; deployed chunk carries `auth/refresh`
and **zero** `asto_auth_token` references remain in the build.

**Docs:** `docs/ROADMAP.md` H1 ticked; this SESSION.md entry.

**H2 — Forgot-password / reset flow (continued in this session):**

- New `password_resets` table — one-time, 1h-expiry reset tokens (only
  SHA-256 hashes stored), audiences staff/client, single-use via `used_at`.
- `POST /auth/forgot-password` — resolves email across users+clients,
  returns the **same generic 200 for known and unknown emails** (no account
  enumeration), inserts the hashed token row, and delivers the link via the
  new `app/auth/password_reset_email.deliver_reset_link` (console/log
  fallback while DEC-3 SMTP is undecided, interface stays the same when a
  real transport lands).
- `POST /auth/reset-password` — validates unused + unexpired token,
  reuses bcrypt + min-8 password rule, marks the token used, and revokes
  **all** of the identity's refresh sessions (password change = logout
  everywhere, piggybacks on H1's `refresh_tokens`).
- Frontend: `/login` now has three modes — login / forgot (email → generic
  success message) / reset (opened from `?reset=<token>` links; token is
  stripped from the URL via `history.replaceState` after reading);
  `forgotPassword()` + `resetPassword()` added to `api-client.ts`.
- Logging fix: uvicorn's default config attaches no root handler, so app
  INFO logs were silently dropped — `app/main.py` now calls
  `logging.basicConfig` so the console-reset-link transport (and future
  app logs) actually reaches the container logs.
- Tests: `tests/unit/test_h2_password_reset.py` (11) +
  `tests/integration/test_h2_password_reset.py` (6). Full suite:
  **417 passed** (was 401). `tsc`/`lint`/`build` all clean.
- Live-verified: known + unknown forgot links return identical 200s; DB
  stores only hashes; token reset succeeds; old password → 401, new
  password → 200; token replay → 400; reset logged the staff account out.
- Note: the live demo `staff@asto.local` password was consumed by the reset
  verification and is now `ResetPass2026!` (was `admin123`).
- Docs: `docs/ROADMAP.md` H2 ticked.

**Next:** H3 — login rate limiting + account lockout.

### Session 15 — 2026-08-12 (Phase H3 — login rate limiting + lockout, completed)

**Context:** H3's backend was already written into the working tree (throttle
helpers in `auth.py`, `login_max_failures`/`login_max_ip_failures`/
`login_lockout_minutes`/`login_attempt_prune_hours` in `config.py`, the
`login_attempts` table + indexes in `schema.py`) but was **incomplete**: it
broke the pre-existing H1 login test and had no H3 tests of its own. This
session closed H3 properly.

**Fix for the H1 regression:** `post /auth/login` now runs the throttle —
prune stale rows (DELETE), COUNT recent failures (SELECT), raise 429 when an
counter is at its cap — *before* the user lookup. The H1 unit test
(`test_h1_http_cookie.py::test_login_sets_httponly_cookie_and_hashes_token`)
mocked `cur.fetchone` to return the staff-user row directly, so the throttle
COUNT query consumed that row and the `email_fails` key was missing
(`KeyError`). The mock now yields a throttle row (`{"email_fails": 0,
"ip_fails": 0}`) first, then the staff user.

**New tests:**
- `tests/unit/test_h3_login_rate_limit.py` (10 tests): 429 when email is at
  the 5-failure cap or IP at the 10-failure cap (with `Retry-After` /
  `X-RateLimit-*` response headers), below-threshold proceeds to lookup,
  prune runs on every attempt, successful login clears the email's failure
  history, failures (including unknown emails) are recorded with an IP,
  and `/auth/client-login` shares the same throttle + reset.
- `tests/integration/test_h3_login_rate_limit.py` (5 tests): real-DB
  lockout at 5 failures + 429 with the correct password on the 6th attempt,
  4 failures still allow login, the shared client-login throttle, stale
  (>15m) failures no longer block login, and success resets the counter.
- Full suite: **389 passed, 43 skipped** (was 379 passed). The 43 skips are
  integration tests that need a live Postgres (Docker not running this
  session) — they collect and skip cleanly and will run when the container
  is up.

**Docs:** `docs/ROADMAP.md` H3 ticked.

**Next:** H5 — session revocation (logout-all already exists behind H1; the
remaining piece is the admin `DELETE /admin/users/{id}/sessions` kill) or
H6 — password change UI (backend endpoint exists; needs the frontend
Settings wiring).

### Session 16 — 2026-08-12 (Phase H5 — session revocation, admin session-kill)

**Design (per `docs/ROADMAP.md` H5):** H1 already made refresh tokens
opaque, stored hashed in `refresh_tokens`, with `logout-all` (revoke every
row for the identity) and rotation. H5 closed the remaining gaps: an **admin
session-kill** (see who is logged in, kill a user's/client's refresh
sessions) and an **emergency access-token kill** via a token `jti`.

**Backend:**
- `auth/jwt_handler.py`: every access JWT now carries a unique **`jti`**
  claim (`secrets.token_urlsafe(16)`).
- `db/postgres/schema.py`: new `revoked_jtis (jti PRIMARY KEY, created_at)`
  table — the emergency kill-list for single access tokens.
- `dependencies.py`: `get_current_user` threads the token's `jti` into the
  resolved user dict so endpoints can reference it.
- `api/v1/admin.py` (4 new endpoints, all `require_role(user, "admin")`):
  - `GET /admin/users/{id}/sessions` + `GET /admin/clients/{id}/sessions` —
    active (non-revoked, unexpired) refresh sessions with count; 404 for
    unknown user/client.
  - `POST /admin/users/{id}/sessions/revoke` + `POST /admin/clients/{id}/
    sessions/revoke` — revoke every active refresh row for the identity
    (`UPDATE ... SET revoked_at = now() WHERE revoked_at IS NULL`), return
    the count. Kills re-auth; already-issued access JWTs stay valid until
    expiry (documented H5 trade-off).
- `api/v1/auth.py`:
  - `POST /auth/logout-all` now also `INSERT ... ON CONFLICT DO NOTHING`
    the caller's `jti` into `revoked_jtis` — the very token used to call it
    dies immediately (audience-agnostic, works for staff and clients).
  - `POST /auth/verify` refuses tokens whose `jti` is in `revoked_jtis`.

**Tests:** `tests/unit/test_h5_session_revocation.py` (16 tests) — route
wiring, 401, client 403 on all four admin routes, session-list SQL scoping
(active-only + per-identity), revoke SQL + count, 404s, logout-all records
the jti + still revokes refresh rows, verify refuses/accepts revoked jti.
Full suite: **448 passed** (was 389; the 43 previously-skipped integration
tests ran live because Docker is up).

**Frontend:**
- `lib/api-client.ts`: `ActiveSession` type + `listUserSessions` /
  `revokeUserSessions` / `listClientSessions` / `revokeClientSessions`.
- `app/admin/page.tsx`: new reusable **`SessionsDialog`** (active-session
  list + Refresh + "Revoke all sessions" with confirmation-style flow) wired
  into both the **Users** tab (Sessions button per row) and **Clients** tab.
  `tsc --noEmit` + `next lint` clean.

**Live verified:** rebuilt + recreated `asto-backend` + `frontend`. Admin
login → `GET /admin/users/{id}/sessions` for a staff user with an active
login shows `active_sessions=1`; after `POST …/sessions/revoke` the same
refresh cookie fails `/auth/refresh` (401) while a fresh login still works;
`POST /auth/logout-all` inserts the token's jti into `revoked_jtis` and
`/auth/verify` on that token returns `valid:false`. All routes 200.

**Docs:** `docs/ROADMAP.md` H5 ticked; this SESSION.md entry.

**Next:** H6 — password change UI (backend `POST /me/password`-style
`/auth/change-password` endpoint already exists for both audiences; needs
the frontend Settings wiring).

### Session 17 — 2026-08-12 (Phase H6 — password change UI, staff + client)

**Context:** `POST /auth/change-password` (both audiences, current-password
verify, strength rules) already existed behind H2-era work, and the client
portal wired it through `SettingsModal`. Two gaps closed this session.

**Backend — revoke sessions after change (ROADMAP H6 step 1):** the
endpoint only updated `password_hash`; it now also revokes every live
`refresh_tokens` row for the identity (`user_id`/`client_id` + audience
scoped) so a stolen session dies the moment the password changes. The
current access token keeps working until expiry. Wrong-current / weak-new
behavior unchanged.

**Tests:** `tests/unit/test_change_password.py` extended — asserts the
`UPDATE refresh_tokens` statement runs for staff (`user_id` + `'staff'`)
and client (`client_id` + `'client'`) after a successful change. Suite:
**448 passed**.

**Frontend — staff/admin Settings wiring (ROADMAP H6 step 2):** the
AppShell "Settings" button was a no-op on the staff and admin pages because
neither passed `onSettings`. Both now render `SettingsModal` (which includes
the Change-password form), so staff and admins can rotate their passwords:
- `app/staff/page.tsx`: `settingsOpen` state, `onSettings` on AppShell, and
  `<SettingsModal>` with `user` + sign-out handlers.
- `app/admin/page.tsx`: same (return now wrapped in a fragment for the
  sibling modal).
- Both also got a real `handleLogoutAll` (calls `logoutAll(token)` then
  clears the local session) instead of reusing plain logout.
- Fixed the same pre-existing shortcut on `app/page.tsx` (staff chat) and
  `app/client/page.tsx`: the "Sign out on all devices" button called local
  logout only — it now actually calls `POST /auth/logout-all` (H5's
  endpoint) via the new `handleLogoutAll`.
- `tsc --noEmit` + `next lint` clean.

**Live verified:** rebuilt + recreated `asto-backend` + `frontend`. For a
staff user: wrong current password → 401, weak new password → 422, correct
change → 200 `{"updated":true}`; the old password then fails login while the
new password succeeds, and the pre-change refresh cookie is rejected at
`/auth/refresh` (401) — confirming the H6 session revocation. `/admin`
serves 200.

**Docs:** `docs/ROADMAP.md` H6 ticked; this SESSION.md entry.

**Next:** H4 — admin 2FA (TOTP), the last open Phase H item.

### Session 18 — 2026-08-12 (Phase H4 — admin 2FA, TOTP)

**Context:** protects the account that approves documents and reads the audit
log. Delivered end to end: enrollment endpoints, a split login flow, and the
two frontend touchpoints. H4 was the last open Phase H item.

**Backend:**
- `app/auth/totp.py`: `new_secret` / `provisioning_uri` (otpauth://, issuer
  `Asto`), `encrypt_secret` / `decrypt_secret` (Fernet, key from
  `settings.secret_key`), `verify_code` with ±1-window tolerance.
- `app/api/v1/admin.py`: `POST /admin/2fa/setup` (returns secret + otpauth
  URI, stores the secret encrypted, 409 when already enabled),
  `POST /admin/2fa/verify` (checks the pending secret, enables on a valid
  code, 401 on wrong code), `POST /admin/2fa/disable` (requires the current
  password, 401 otherwise), `GET /admin/2fa/status`. All gated to the
  `admin` role via `require_role`.
- `app/api/v1/auth.py`: `/auth/login` now reads `totp_enabled`;
  `requires_2fa=true` + a short-lived, single-use `two_fa_token` is returned
  (no access JWT, no refresh cookie) when the account has TOTP on.
  `POST /auth/2fa` verifies purpose=2fa + the code, records the jti in
  `revoked_jtis` (single-use), then issues the refresh cookie and access JWT.
- `app/db/postgres/schema.py`: `users.totp_secret` (TEXT) +
  `users.totp_enabled` (BOOL NOT NULL DEFAULT false) in the CREATE TABLE and
  as idempotent `ALTER TABLE` statements for pre-existing schemas.
- `app/config.py`: `two_fa_token_ttl_minutes` (5) + `secret_key` used for
  secret encryption sets `app/auth/totp.py` up.

**Tests:** new `tests/unit/test_h4_2fa.py` (25 cases: setup/verify/disable
permissions + codes, login with and without 2FA, wrong code, `two_fa_token`
single-use, access JWT rejected as a 2FA token, status). Existing
H1/H3 mocks updated for the new `totp_enabled` column. Also fixed a
pre-existing flaky integration test: `tests/integration/test_h3_login_rate_limit.py`
purged only by email while the throttle counts the shared `testclient` IP —
`_purge_attempts` and teardown now clear both. Suite: **466 passed**.

**Frontend:**
- `lib/api-client.ts`: `AuthLoginResponse` extended with `requires_2fa` /
  `two_fa_token`; new `twoFactorLogin`, `twoFaStatus`, `twoFaSetup`,
  `twoFaVerify`, `twoFaDisable`.
- `app/login/page.tsx`: a new `2fa` mode — after the password is accepted
  the login screen shows a 6-digit code field and swaps the token via
  `/auth/2fa`, then routes normally.
- `components/settings/SettingsModal.tsx`: admin-only **TwoFactorCard**
  (status check on open; Set-up flow showing the secret + otpauth URI with
  copy, then Confirm & enable; Disable flow requiring the current password).
  `tsc --noEmit` + `next lint` clean.

**Docs:** `docs/ROADMAP.md` H4 ticked; this SESSION.md entry.

**Next:** H7 — role & department editor UI (config write-back vs DB table is
open as H7-OPT).

### Session 19 — 2026-08-12 (Phase H7 — governance editor, write-back to roles_config.py)

**Context:** Roles & Permissions / Departments were read-only, requiring
hand-editing `app/auth/roles_config.py`. Took ROADMAP H7 **Option A** (the
recommended one): keep the Python config as source of truth and add a
write-back endpoint + admin edit UI. No schema change. H7-OPT is resolved —
removed from the pending decisions table.

**Backend:**
- `app/auth/governance.py`: pure `render_config` (regenerates the full
  `roles_config.py` source: `ROLE_DEPARTMENTS`, `ADMIN_ROLES`,
  `ROLE_HIERARCHY`, `DEFAULT_DEPARTMENT`, `ROLE_CAPABILITIES`, `ROLES`,
  `DEPARTMENTS`, `can()`, `role_access()`) and `write_config` — same-dir temp
  file + `os.replace` (atomic), then `importlib.reload` so running handlers
  pick up the change; `config_path` / `module` injectable for tests. Exposes
  `KNOWN_CAPABILITIES` whitelist and `DEPT_NAME_RE`.
- `app/auth/permissions.py`: `require_manage_governance` — the new
  `manage_governance` permission, satisfied only by admin/super_admin via
  `roles_config.can()` (stays config-consistent).
- `app/api/v1/admin.py`: `PUT /admin/governance` — permission gate, then
  validation (role names must match the existing set, capabilities must be
  known, department names must match `[a-z][a-z0-9_]*` and be unique, role
  access can only reference submitted departments, hierarchy must cover the
  roles) → 422s; positional department rename detection; DB migration of
  every department column (`users.department`, `users.allowed_departments`,
  `documents`, `document_chunks`, `sops`, `sop_access_requests`,
  `workflows`) with best-effort rollback if the config write fails;
  `DEFAULT_DEPARTMENT` follows a renamed `general`; audit-logged. `GET
  /admin/governance` now returns `capabilities` per role.

**Tests:** new `tests/unit/test_h7_governance.py` (16 cases): renderer
round-trip (valid Python, edited values, "all"→[] access), write+reload
from a temp file (reload re-executes the new content), admin PUT persists to
disk, permission gating (staff 403 / client 403 / unauthenticated 401),
invalid role name 422, unknown capability 422, invalid department name 422,
role→unknown-department 422, department rename migrates every column + tracks
`default_department`, and no-write-no-audit on validation failure. Suite:
**482 passed**.

**Frontend:**
- `lib/api-client.ts`: `GovernanceRole.capabilities`, new
  `GovernanceUpdateInput` + `updateGovernance` (`PUT /admin/governance`).
- `app/admin/page.tsx`: GovernanceTab gained an Edit mode — edit role
  label/description, toggle capabilities per role (checkboxes derived from
  the union of current capabilities), add/rename departments (renames
  propagate into role access lists client-side), client-side validation
  mirroring the backend, Save/Cancel. `tsc --noEmit` + `next lint` clean.

**Docs:** `docs/ROADMAP.md` H7 ticked, H7-OPT removed from pending
decisions; this SESSION.md entry.

**Next:** Phase I — Documents & Review (I7 drag-and-drop multi-file upload
and I1 inline PDF preview are the quick wins).

### Session 4 — 2026-08-08 (Phase D — frontend: chat UX, client portal, admin dashboard)

**Done (Phase D):**
- **D1 Chat view** (`/`): converted the single search box into a ChatGPT-style
  conversation. User questions render as right-aligned bubbles; each Asto
  answer renders as an assistant bubble wrapping the existing
  `ResponsePackageCard` (title, confidence badge, verbatim summary with
  citations, source excerpts) + thumbs feedback. Related questions append to
  the conversation; a typing indicator + skeleton shows while a query runs.
- **D2 24h local-only history**: new `hooks/use-chat-history.ts` persists
  turns (query + full response package) to `localStorage` keyed
  `asto_chat_history`, purges entries older than 24h on load, and supports
  clear-all ("New conversation") and per-turn remove. No server persistence.
- **Client portal** (`/portal`): authenticated client-only dashboard showing
  profile, properties, cases (loan amount/status), and approved documents.
  Redirects non-client JWTs to `/login`. Header links to "Ask Asto".
- **Client login**: `/login` now has a Staff/Client tab — client tab calls
  `/auth/client-login` and stores the client-scoped JWT (audience="client").
- **D3 Admin dashboard** (`/admin`): admin-role-only management UI with five
  tabs:
  - Approvals — pending-queue (approve/reject writes the audit trail, refresh)
    + per-document approval history dialog.
  - Documents — upload (multipart → `/documents/upload`, explains pending +
    batch-ingest flow) + list-all with status badges.
  - Users — list + create staff users (role/department selects).
  - Clients — list + create client accounts + assign staff to client.
  - Analytics — knowledge gaps (no-answer / low-confidence queries).
- **Auth routing**: `auth.ts` gained `decodeToken()` (reads `audience`, `role`,
  `client_id`, `exp` from the JWT payload) used by all three pages to gate and
  route. `/` and `/admin` redirect unauthenticated / wrong-audience visitors to
  `/login`. Client audience gets a "you can only see your own approved
  documents" banner.
- **API client**: `api-client.ts` extended with clientLogin, client
  me/properties/cases/documents, admin approvals (pending/approve/reject/
  history), documents list + upload, users (list/create), clients
  (list/create/assign), and knowledge-gaps — all typed to the live response
  shapes.
- **Baseline gap closed (Session 2 carry-over):** host `npm ci` deps present,
  `npm run build` + `npm run lint` both clean on the host.
- **Verified live**: built + deployed the frontend container (`docker compose
  build frontend && up -d`). `/`, `/login`, `/admin`, `/portal` all serve 200.
  API smoke test confirmed every new frontend call matches the real backend
  shapes (staff+client login, pending queue, history keys, users/clients keys,
  portal me/properties/cases/documents keys, knowledge-gaps keys, search
  `related_questions` array) and that authz holds (staff→/client/me 403,
  client→/admin/users 403, duplicate user create 409).

**Not done / carry to next session:**
- Phase E (docs/README/design-doc consistency) — not started.
- Streaming response (real SSE streaming-lite) — the UI shows a skeleton while
  awaiting the response; not yet token streaming (backend is request/response).
- Admin dashboard has no analytics charts (only the knowledge-gaps list) and no
  document view/download; client portal has no document open/download.
  *(Both since resolved — Session 6: document view/download + analytics charts.)*
- The deployed frontend uses the baked-in `localhost:8011` API base (no
  NEXT_PUBLIC_API_URL build arg) — fine for local dev, must be set explicitly
  for a remote host (see nginx + compose).

### Session 5 — 2026-08-08 (Phase E — documentation & consistency)

**Done (Phase E):**
- **E1 Docs updated for dual-audience + approval workflow:**
  - `README.md` — rewritten intro (staff + client audiences, approval
    workflow), architecture diagram, constraints table, step-1 auth + step-1b
    approval workflow sections, frontend component table, project structure
    matching reality, quick start with seed accounts
    (`admin@asto.local/admin123`, `client@asto.local/client123`), testing
    section (140 unit + 11 integration, module names verified against the
    tree), evaluation section pointing at
    `evaluation/reports/benchmark_20260808_005649.json`.
  - `Final_System_Design.md` — §8b **Dual-Audience Authentication**
    (mermaid login flow), §8c **Document Approval Workflow** (state diagram +
    gate in the search WHERE clause), component-responsibility table gained
    Approval Workflow + Dual-Audience Auth rows, design decisions #11 and #12.
  - `Final_Folder_Structure.md` — rewrote the tree to match the actual
    repository (flat `frontend/app/` pages `page/login/portal/admin`, `lib`
    `api-client.ts` + `auth.ts` with `decodeToken`,
    `hooks/use-chat-history.ts`, `components/chat/ChatMessage.tsx`; backend
    gained `api/v1/approvals.py`, `api/v1/client.py`, extended
    `admin.py`/`jwt_handler.py`/`dependencies.py`/`indexing.py`,
    `scripts/seed_db.py`, new tests). Added a "Added 2026-08-08" table for
    the Session 3–4 deltas. Dropped dead artifacts (Qdrant, Redis, MinIO,
    per-project Postgres, `infra/monitoring/`, `nlp_models/`, Alembic —
    none exist in the repo).
- **E2 SKILL.md** — inserted **Phase 6.5 — Dual-Audience Auth + Approval
  Workflow + Frontend UX** after Phase 6: approval workflow, approval filter
  in the search WHERE clause, client JWT auth (audience + client_id),
  client-scoped API, admin user/client endpoints, chat/portal/admin frontend,
  seeding, DoD (151 tests, live approve→searchable / reject→not-searchable,
  build+lint clean, all four routes 200).
- **E3 Benchmark gate** — **no re-run needed.** Audited the retrieval path:
  the only change in Sessions 3–4 was adding the `is_approved`/`is_active`
  hard pre-filter (`search/metadata_filters.py` `get_version_filter`, line
  100) plus the client/department RBAC clause — both reduce the candidate
  set; ranking weights, confidence thresholds, and the reranker are
  untouched. Baseline `benchmark_20260808_005649.json` remains the gate.

**Noted as carry-overs (unchanged from Session 4):**
- True SSE token streaming not started; admin dashboard has no charts and no
  document view/download; client portal has no document open/download; the
  deployed frontend still uses the baked-in `localhost:8011` API base.
  *(Resolved Session 6: streaming, document view/download, analytics charts.)*

### Session 6 — 2026-08-10 (True SSE streaming + document view/download + analytics verification)

**Done (Phase D carry-overs closed):**
- **Verified document view/download (#2):** admin `GET /documents/{id}/file`
  and client `GET /client/documents/{id}/file` both serve stored files (admin
  resolve confirmed 200 with the stored file). Seeded demo docs reference
  `/docs/*.pdf` that were never placed in storage, so those rows 404 — the
  endpoint logic is correct and works whenever a real file is on disk
  (`documents/file_serve.py` searches processed/ then pending/ by basename).
- **Verified analytics (#3):** `GET /analytics/summary` + `/analytics/knowledge-gaps`
  live on `admin@asto.local` (empty until real gaps accumulate — gap logging is
  wired into the pipeline).
- **True SSE streaming (backend):** replaced the "streaming-lite" buffered
  stream in `api/v1/search.py`. `_run_pipeline` now emits typed events via a
  `(event_type, data)` callback; `POST /search/stream` runs the sync pipeline
  in a worker thread (`asyncio.to_thread`) draining an `asyncio.Queue` so each
  event is flushed as soon as it is produced — no more single buffered payload.
  Event order: `status` (processing/searching/ranking/packaging/done) →
  one `fact` event per structured-fact row (fact path) or one `sentence`
  event per extractive summary sentence (document path) → `result` (same
  payload as the sync endpoint) → `error` on failure. No LLM, no generated
  text — every streamed item is a verbatim retrieved value.
- **Frontend streaming UI:** `lib/api-client.ts`
  `searchKnowledgeBaseStream` now takes a handlers object
  (`onStage`/`onFact`/`onSentence`); new
  `components/chat/StreamingPreview.tsx` renders the stage label plus facts /
  summary sentences as they arrive; wired into the staff chat (`/`) and client
  chat (`/client`) loading bubbles (reset on new search/regenerate, replaced by
  the full `ChatMessage` when `result` lands). Staff page supports case-context
  fact streaming; client page streams own-case facts + document summaries.
- **Tests:** new integration tests — `test_fact_path_integration.py`
  `test_stream_emits_fact_events_then_result` (SSE stream: statuses → fact
  events → result, one fact event per fact, verbatim values + sources) and
  `test_end_to_end.py` `test_document_path_stream_emits_sentence_events`
  (sentence events == summary rows). Full suite: **311 passed**
  (unit + integration, live Postgres).
- **Live verification:** rebuilt `asto-backend` + `frontend`, recreated both.
  Client fact query over `/search/stream` returned
  status → 5 fact events → result; admin document query returned
  status → 2 sentence events → result; sync `/search/` still returns a full
  package (routing=answer, confidence 100). Frontend container serves the
  `StreamingPreview` chunk.
- **Build hygiene:** `npm run build` clean, `tsc --noEmit` clean, ESLint clean
  on changed files.

**Not done / carry to next session:**
- Admin dashboard still shows only the raw knowledge-gap list (no charts yet) —
  the analytics *endpoints* are verified; a chart UI is the remaining piece.
  *(Fixed: `/admin` Analytics tab renders charts — see Session 8.)*
- Seeded demo docs have no real source files on disk (they 404 on view) —
  either place PDFs in `storage/processed/` matching their basenames or upload
  fresh docs to see view/download end-to-end.
- Phase E docs (README/design-doc) not re-touched for streaming; this entry is
  the record.

### Session 7 — 2026-08-10 (Unified single sign-in — no Staff/Client selector)

**Done:**
- **Unified `POST /auth/login`:** `api/v1/auth.py` now resolves the identity
  across both tables in one request — checks `users` (staff) first, then
  `clients` (external). Returns the audience-scoped JWT (staff →
  role/department claims; client → `audience="client"` + `client_id`). The
  frontend already auto-routed by JWT claims, so removing the tabs completes
  the flow: **one login form, identity auto-detected from email/password.**
- **Single generic 401:** a failed match on both tables returns one
  "Invalid credentials" error, so the response never reveals which table an
  email belongs to.
- **Deterministic precedence:** an email present in both tables resolves as
  staff (documented in `auth.py` docstring).
- **Frontend:** `app/login/page.tsx` rewritten as a single form (email +
  password + remember-me + forgot-password), tabs removed. Removed the now
  unused `clientLogin` helper from `lib/api-client.ts`; `/auth/client-login`
  endpoint kept for backward compatibility.
- **Tests:** new `tests/integration/test_unified_login.py` (4 tests) — staff
  and client both resolve via `/auth/login` with correct JWT claims, bad
  password/unknown email → generic 401, legacy `/auth/client-login` still
  works. Full suite: **315 passed** (unit + integration, live Postgres).
- **Live verified:** rebuilt `asto-backend` + `frontend`. `admin@asto.local`
  and `client@asto.local` both log in via `/auth/login`; wrong password → 401;
  `/login` serves 200 and the login page chunk contains zero `TabsTrigger`
  references.

**Not done / carry to next session:**
- Admin analytics tab still shows the raw knowledge-gap list (no charts yet) —
  the analytics endpoints are verified; a chart UI is the remaining piece.
  *(Fixed: `/admin` Analytics tab renders charts — see Session 8.)*
- Seeded demo docs still reference `/docs/*.pdf` that were never placed on
  disk (they 404 on view) — place PDFs in `storage/processed/` matching their
  basenames or upload fresh docs to see view/download end-to-end.

### Session 8 — 2026-08-10 (Phase F1 — seeded doc View 404 + stale SESSION notes)

**Done:**
- **Seeded doc View fixed:** `scripts/seed_db.py` now generates real PDFs
  into `storage/processed/` matching each seeded `source_path` basename
  (`draft_credit_policy.pdf`, `sample_policy.pdf`, `eligibility.pdf`) via a
  new `ensure_seed_files()` step (idempotent — skips existing files). Ran it
  against the live DB; all three seeded docs (448/449/450) now resolve via
  `resolve_stored_file` and the admin `/documents/{id}/file` endpoint returns
  **200** (was 404).
- **Stale analytics notes fixed:** the carry-over notes claiming the admin
  Analytics tab has "no charts yet" were outdated — the `/admin` Analytics tab
  already renders charts. Marked each as resolved in the Session 4/5/6/7 log
  entries.
- **Orphaned demo rows noted:** docs 444–447 (client-uploaded demo docs from a
  prior session) have empty `source_path` and no files on disk — View will
  still 404 for them. Flagged; not in seed scope.

**Phase F2 — Admin Dashboard + Settings (same session):**
- **`GET /admin/summary`:** new endpoint in `api/v1/admin.py` returning 7
  admin-only aggregate counts (pending approvals, total documents, users,
  clients, active cases, knowledge gaps, pending SOP access requests).
- **Frontend:** admin `Dashboard` + `Settings` nav items enabled; new
  `DashboardTab` (stat-card grid with refresh) and `SettingsTab` (browser-local
  prefs: default landing tab + audit-banner toggle) in `app/admin/page.tsx`;
  `getAdminSummary` client added. Default landing tab now honors the saved pref.
- **Tests:** `tests/unit/test_admin_summary.py` (5 tests) — route wiring, 401,
  client 403, payload counts, null-count → 0. Full suite: **320 passed**.
- **Live verified:** rebuilt `asto-backend` + `frontend`; `/admin/summary`
  returns live counts; admin page 200 and its compiled chunk references the new
  components.

**Phase F3 — Admin governance views (same session):**
- **Design decision (user):** Roles & Permissions / Departments are
  **config-driven** — `app/auth/roles_config.py` is the single source of truth
  for roles, their department access, the role hierarchy, and the departments
  list (Python data, not YAML, to avoid a new dependency). Enforcement stays in
  `rbac.py`/`permissions.py`; the admin view is read-only for now.
- **Endpoints** in `api/v1/admin.py`: `GET /admin/documents/{id}/chunks`
  (read-only KB browse), `GET /admin/sops` (admin read-all SOPs), and
  `GET /admin/governance` (config-driven roles + departments).
- **Frontend:** admin `Knowledge`, `SOPs`, `Roles`, `Departments` nav items
  enabled; new `KnowledgeBaseTab` (document picker + chunk list),
  `SopManagementTab` (SOP list + access-request approve/reject), and
  `GovernanceTab` (read-only roles/departments, shared by Roles + Departments).
- **Tests:** `tests/unit/test_admin_governance.py` (9 tests) — route wiring,
  401, client 403, chunk payload + 404, SOP payload, governance config.
  Full suite: **329 passed**.
- **Live verified:** all three endpoints return correct data against the live
  DB; admin page 200 with the new components in its compiled chunk.

**Phase F4 — Staff operational views (same session):**
- **New `/staff` page** (`app/staff/page.tsx`) — four tabs all wired to the
  existing backend (no backend change): Dashboard (stat cards + recent
  workflows from `/staff/dashboard`), My Cases (case cards + case-notes
  view/add via `/staff/cases/{id}/notes`), Workflows (advance stage via
  `/staff/workflows/{id}/advance`), SOPs (list + create for approved authors +
  access-request submit + own requests list).
- **Login routing:** non-admin staff now route to `/staff` (was `/` chat page).
- **Nav:** staff Dashboard / My Cases / Workflows / SOPs enabled; Tasks and
  Collaboration stay disabled.
- **Live verified:** `/staff` serves 200 with the new components in its chunk;
  `/staff/dashboard` returns live cases + workflows + SOPs for `staff@asto.local`.

**Phase F5 — Staff Tasks + client Home/Help (same session):**
- **Design decision (user):** Staff Tasks are **derived from workflows** — no
  new `tasks` table. Each active (in_progress/review) workflow in the staff
  member's departments is a task with an Advance action.
- **Client Home:** new `HomeView` in `app/client/page.tsx` — overview cards
  (active case, properties, documents) from the already-loaded
  me/properties/cases/documents endpoints + a latest-update card from
  `latest_event`. Client now lands on Home after login (was chat).
- **Client Help:** new `HelpView` — static FAQ-style sections. Client Home +
  Help nav items enabled.
- **Staff Tasks:** new `TasksTab` in `app/staff/page.tsx` — open/completed
  stat cards + actionable workflows with Advance (reuses `/staff/workflows/
  {id}/advance`). Tasks nav item enabled.
- **Live verified:** `/client` and `/staff` both 200; compiled chunks reference
  the new Home/Help/Tasks components. Full backend suite still **329 passed**.

**Not done / carry to next session:**
- Remaining Phase F views (F6 messages/collaboration, F7 audit log) — next in
  build order.

### Session 9 — 2026-08-11 (Phase F6 — Messages + Collaboration)

**Design decision (user):** **Full messages system** — new `conversations` +
`messages` tables, client-scoped, case-anchored. No shared-storage message bus;
every conversation belongs to exactly one client, optionally tied to a case.
RBAC is enforced in the SQL WHERE clause (CLAUDE.md rule 1): clients only see
`conversations.client_id = their id`; staff only see conversations for clients
they are assigned to (`staff_client_assignments`); admins see all.

**Backend:**
- `db/postgres/schema.py`: two new tables — `conversations` (case_id nullable,
  client_id NOT NULL → clients ON DELETE CASCADE, subject, timestamps) and
  `messages` (conversation_id → CASCADE, sender_type CHECK staff|client,
  sender_user_id / sender_client_id, body, created_at) + 3 indexes
  (conversations by client/case, messages by conversation+time).
- `db/postgres/models.py`: `conversation_row_to_dict` + `message_row_to_dict`.
- New `api/v1/messaging.py`: shared helpers — client/staff conversation access
  checks (`_assert_conversation_access_client/staff`), SQL-scoped listers
  (`_list_conversations_client/staff`), `_list_messages` (JOINs users + clients
  for `sender_name`), `_touch_conversation` (bumps `updated_at` for sort).
- `api/v1/client.py`: `GET/POST /client/conversations`, `GET/POST
  /client/conversations/{id}/messages` — client-only, scoped by JWT client_id;
  `_assert_owns_case` gates the optional `case_id`.
- `api/v1/staff.py`: `GET/POST /staff/conversations`, `GET/POST
  /staff/conversations/{id}/messages` — staff-only; `_assert_client_visible`
  and the access helpers enforce assignment scoping (admins unrestricted).
- Tests: `tests/unit/test_messaging.py` (16 tests) — route wiring, 401, client
  403 on staff routes, staff 403 on client routes, client list SQL scopes by
  client_id, create conversation, blank-subject/body 422, ownership 404,
  staff list admin-all vs assignment-scoped SQL, message read JOINs
  `sender_name`. Full suite: **345 passed** (329 + 16).

**Frontend:**
- `lib/api-client.ts`: `Conversation`/`Message` types + `jsonOrThrow` helper +
  8 functions (client: list/create/conversation messages/send; staff: same).
- `config/navigation.tsx`: client `messages` and staff `collaboration` nav
  items enabled (were disabled).
- New `components/messages/ConversationThread.tsx`: shared two-pane thread —
  conversation list (subject + case # + client name), message bubbles
  (mine/other by `selfSenderType`, sender name on the other side, timestamps),
  auto-scroll, Enter-to-send. Used by both portals.
- Client `app/client/page.tsx`: `messages` view added to `View`/nav maps +
  header title; new `MessagesView` (conversation list, New-conversation form
  with subject + optional linked case, refresh) rendering `ConversationThread`.
- Staff `app/staff/page.tsx`: new `CollaborationTab` (conversation list,
  New-conversation form with subject + client picker + optional case filtered
  to that client) rendering `ConversationThread`; TabsList 5 → 6 columns.
- `tsc --noEmit` clean, ESLint clean on changed files.

**Live verified (rebuilt + recreated `asto-backend` + `frontend`):**
- Tables `conversations` + `messages` created on startup schema init.
- client@asto.local creates a conversation → client sends "Hi, can you review
  my docs?" → admin sees it under `/staff/conversations` → admin replies →
  client thread returns both messages with correct `sender_name`s
  ("Client User" / "Admin User").
- Cross-client read of another client's conversation → **404** (SQL scoping
  holds). Left the demo thread in place as sample data.

**Phase F7 — Admin Audit Log viewer (same session):**
- **`GET /admin/audit`** in `api/v1/admin.py` — filterable + paginated read of
  the immutable audit_log table (CLAUDE.md rule 8). Filters (AND-combined):
  `q` (query-text ILIKE), `actor` (email/full_name across BOTH audiences via
  LEFT JOINs users + clients — audit rows carry no audience tag), `outcome`
  (exact, e.g. answer/partial/no_answer/no_sub_queries/validation_failed:…),
  `from`/`to` (created_at range), plus `limit`/`offset` pagination. Returns
  `{total, limit, offset, entries}`; entries resolved with actor name/email.
- `db/postgres/models.py`: `audit_row_to_dict` (actor + actor_email fields).
- Tests: `tests/unit/test_admin_audit.py` (10 tests) — route wiring, 401,
  client 403, payload shape, q/actor/outcome/date filters land in SQL with
  correct params, pagination limit/offset, bad limit 422. Full suite:
  **355 passed** (345 + 10).
- Frontend: admin `Audit` nav enabled; new `AuditLogTab` in
  `app/admin/page.tsx` — filter card (query text, actor, outcome select,
  from/to date pickers), entry list (query, outcome badge, actor, confidence,
  latency, timestamp, source IDs), pagination (Prev/Next + total count),
  refresh. TabsList 11 → 12 columns. `getAdminAudit` + `AuditEntry`/
  `AuditFilters` types in `lib/api-client.ts`.
- `tsc --noEmit` clean, ESLint clean.
- **Live verified:** `/admin/audit` returns **671** entries total (50 per
  page); `?outcome=answer` → 562, `?actor=admin` → 536, pagination
  offset/limit honored; staff (loan_officer) → **403**; `/admin` page 200
  with the AuditLogTab in its compiled chunk.

**Phase F now complete — every Phase F view (F1–F7) is built, tested, and
live. This session also re-verified the F6 messaging flow end-to-end
(logins, thread, staff scoping) after the user asked for a completeness
review.**

### Session 10 — 2026-08-11 (One-page client onboarding + version bump re-upload)

**Done:**
- **Client onboarding (staff → new client account):**
  `backend/app/api/v1/staff.py` endpoint `POST /staff/clients` guarded by the
  new `onboard_clients` permission (`roles_config.py`, granted to
  `super_admin`/`admin`/`loan_officer`) + `_require_staff`. In one DB
  transaction it (a) rejects a duplicate email (409), (b) inserts the client
  (`bcrypt`-hashed password), (c) inserts a property row when any address
  field is provided, and (d) inserts an initial case (`CAS-YYYY-NNNN` via
  `_next_case_number`) when a loan amount or property exists. Response carries
  `client_id`, `property_id`, `case_id`, `case_number`. CRM import hook
  (`app/clients/client_import.py`, `ClientSource` protocol + registry +
  `scripts/import_clients.py` stub) documented beside it so manual onboarding
  and future CRM-driven import stay identical.
- **Frontend Onboard Client dialog** (`frontend/app/staff/page.tsx`): an
  "Onboard client" button in the staff header opens a `Dialog` with
  name/email/password + optional property + optional loan amount; calls
  `onboardClient()` (new `frontend/lib/api-client.ts`); on success refreshes
  the dashboard. No new nav entry — it lives in the header.
- **"Stale pending approvals"** on the admin dashboard:
  `backend/app/api/v1/admin.py` `/admin/summary` now also returns
  `stale_pending_approvals` (documents pending for 7+ days);
  `frontend/app/admin/page.tsx` shows it as an amber-alert stat card and
  `AdminSummary` gains the field. Test updated in
  `backend/tests/unit/test_admin_summary.py`.
- **Re-upload = version bump** (`backend/app/documents/indexing.py`): before
  inserting, `index_document` looks up the latest *active* document with the
  same title/department/client/property; if found it deactivates the old row
  and inserts the new one with `version = old + 1`. First upload stays
  `version = 1` (DB default). Old versions remain queryable but are excluded
  from search (`d.is_active = true`).

**Tests added/updated (all green):**
- `backend/tests/unit/test_onboard_client.py` (new, 9 tests): route wiring,
  401/403 gating (client token, staff role without `onboard_clients`),
  happy path (client+property+case), no-property path (no property/case),
  duplicate-email 409, invalid email / short password 422.
- `backend/tests/unit/test_approvals.py`: 2 new tests for the version bump
  (re-upload carries `version = old+1` and deactivates the old row; first
  upload is version 1) + fixed existing mocks for the new version-lookup
  query.
- `backend/tests/unit/test_admin_summary.py`: asserted
  `stale_pending_approvals`.

**Verified:** `npx tsc --noEmit` + `npm run lint` clean in `frontend/`;
backend unit suite 320 passed (was 309) / 7 failed. The 7 failures are
**not** regression: they are JWT-secret/env config issues
(`test_client_auth.py`, `test_backend_skeleton.py` JWT cases,
`test_streaming_files.py`) failing on unset `JWT_SECRET` before this session
too. **Live-verified against rebuilt containers** (docker compose
astv1-asto-backend + astv1-frontend): admin login 200 +
`/admin/summary` returns `stale_pending_approvals`; `POST /staff/clients`
onboards client+property+case (201, `CAS-2026-0003`) and rejects a
duplicate email (409); re-ingesting the same title deactivates the old
document (id 808, v1 → inactive) and indexes the new one as version 2.

### Session 11 — 2026-08-11 (Hydration-error fix — React #418/#423 on all pages)

**Symptom:** minified `Uncaught Error: React error #418` (hydration mismatch)
+ #423 (error while hydrating a Suspense boundary) repeated across pages,
with the follow-on "message channel closed before a response was received".

**Root cause:** classic hydration mismatch. `useState` lazy initializers read
`localStorage` with a `typeof window === "undefined"` guard, so at static
build the server renders with the default, but on the client's **hydration**
render the initializer returns the *stored* value → server HTML ≠ client HTML.
After the mismatch React bails the root to client rendering (#423) and the
React DevTools/`MessagePort` bridge then reports the channel-closed noise.

**Affected sites fixed (localStorage reads moved out of `useState`
initializers into `useEffect`, which runs after hydration):**
- `frontend/components/layout/AppShell.tsx` — `collapsed` /
  `asto_sidebar_collapsed`.
- `frontend/app/admin/page.tsx` — `SettingsTab` seeds from
  `loadSettings()` instead of a lazy initializer.
- `frontend/app/page.tsx` + `frontend/app/client/page.tsx` —
  `showSuggestions` / `sessionTimeout`. Chat/history hooks
  (`use-chat-history.ts`, `use-chat-sessions.ts`) were already effect-based.

**Verified:** `npx tsc --noEmit` + `npm run lint` clean; `docker compose
build frontend` and `up -d` redeployed; served HTML now references rebuilt
page chunks (`app/page-cbdceb64b838174c.js`, client `9197bd008cac54a2.js`)
that carry the `asto_smart_suggestions` marker with **no** lazy
`typeof window ===` guard. The `fd9d1056…` chunk still present in the image
is shared React internals (where the error is *thrown*), not the mismatch
source, and is unchanged because its code didn't change.

### Session 12 — 2026-08-12 (Role-gate fix: super_admin treated as staff + identity display)

**Symptom:** logging in with the seeded admin (`admin@asto.local`) landed on
the **staff** workspace, and the chat ("Ask Asto") showed identity "Staff
super admin". The admin panel's own gate would have blocked `super_admin`.

**Root cause:** the seed creates the admin as role `super_admin`
(`backend/scripts/seed_db.py`), and the backend correctly treats it as admin
(`rbac.ADMIN_ROLES = {"super_admin", "admin"}`), but **every frontend gate
compared the exact string `role === "admin"`**:
- `frontend/app/login/page.tsx:36` — `super_admin` failed the check → routed
  to `/staff` instead of `/admin`.
- `frontend/app/staff/page.tsx` — only rejected `"admin"`, so `super_admin`
  was kept in the staff panel.
- `frontend/app/page.tsx` (Ask Asto chat) — `super_admin` was not redirected
  to `/admin`, stayed on the chat.
- `frontend/app/admin/page.tsx` — gate was `claims?.role !== "admin"`, so a
  `super_admin` would actually be **blocked** from the admin page.

Additionally the chat hardcoded the identity as `name: "Staff"`, producing
"Staff super admin" for a real admin.

**Fix:**
- Added `isAdminRole()` / `isStaffRole()` helpers in
  `frontend/lib/auth.ts` mirroring backend `rbac.ADMIN_ROLES`.
- Swapped all four gates (`login`, `page`/chat, `staff`, `admin`) to use
  `isAdminRole()` so `super_admin` routes/behaves identically to `admin`.
- Added a `name` claim to JWTs (`backend/app/auth/jwt_handler.py` +
  `backend/app/api/v1/auth.py`, sourced from `users.full_name` /
  `clients.full_name`, falling back to email) so the UI can show the real
  name. `TokenClaims` + chat/staff/admin AppShell + SettingsModal now prefer
  `claims.name`.
- Chat, staff, and admin pages no longer hardcode identity labels; they
  derive from JWT claims.

**Verified:** `npx tsc --noEmit` + `npm run lint` clean; backend `pytest -q`
→ **366 passed** (including the 7 env-dependent tests that previously
failed). No retrieval/ranking/confidence changes — no benchmark re-run
required (CLAUDE.md rule 7).

**Not done / carry to next session:**
- Phase G (staff client-data interface, staff document upload → admin
  review with metadata edit + reject reason, notifications) — designed,
  not yet implemented. See Next Steps below.

### Session 13 — 2026-08-12 (Phase G — staff client interface + doc review with metadata edit + notifications)

**Design decision (user):** Notifications are a **generic** table (`user_id`,
`type`, `title`, `body`, `link`, `is_read`) so SOP outcomes + message pings
are just new rows later. Staff document upload mirrors the existing client
upload flow (validate → `storage/pending/` sidecar, batch ingestion later,
never inline) and **auto-notifies admins**; admin approve/reject
**auto-notifies the uploader**.

**Backend:**
- `db/postgres/schema.py`: new `notifications` table + index (user_id, unread
  first, created_at desc).
- New `api/v1/notifications.py`: `GET /staff/notifications` (own only,
  RBAC in WHERE — `user_id = current`), `POST /staff/notifications/{id}/read`
  (scoped, 404 when not found), `POST /staff/notifications/read-all`. Generic
  `create_notification()` helper used by the review + upload paths.
- `api/v1/approvals.py` (G2 + G3): `PATCH /admin/documents/{id}` — metadata
  only (title / doc_type / department, empty or no-op patch → 400, only
  `pending` docs editable); reject now **requires a non-blank `reason`** (422
  otherwise) persisted to `approval_log.reason`; approve/reject both
  auto-create a notification for the uploader (approve note / reject reason).
- `api/v1/staff.py` (G1): `POST /staff/documents/upload` — scoped to a client
  the staff member is assigned to (`staff_client_assignments` in SQL),
  validates file + client, writes `storage/pending/` sidecar, sets
  `uploaded_by`, auto-notifies admins.
- `api/v1/staff.py` (G4): `GET /staff/clients` — assigned clients each with
  `properties`, `cases`, and `documents` **including `approval_status`** +
  `uploaded_by` (admins see all clients).
- `documents/indexing.py` / `db/postgres/models.py`: `uploaded_by` column +
  row mapping; version-bump lookup prefers active rows.
- Tests: new `tests/unit/test_phase_g.py` (24 tests) — route wiring, 401/403
  audience gating, assignment-scoped staff clients SQL, upload validation +
  pending sidecar + admin notification, metadata edit (empty/approved/ok),
  reject-reason required + persisted + uploader notified, notifications
  list/mark-read scoping/read-all. Full suite: **390 passed** (was 366).

**Frontend:**
- `lib/api-client.ts`: `Notification` type + staff notifications
  (list/mark-read/mark-all), `updateDocumentMetadata`, staff
  `uploadDocument` + `onboardClient`, staff clients list, `rejectDocument`
  now takes a `reason`.
- Staff `app/staff/page.tsx` (G4 + G5): new **Clients tab** — assigned-client
  cards with properties, cases, and documents with approval status badges; a
  **document-upload dialog** (client picker + file) per client; Onboard-client
  dialog in the header.
- `app/admin/page.tsx` (G6): Approvals queue cards gained **Edit** (metadata
  dialog: title/type/department via `PATCH`) and **Reject** now opens a
  required-reason dialog before submitting; uploader email shown on pending
  cards; `EditMetadataForm` + `RejectForm` subcomponents.
- `components/layout/AppShell.tsx` + `config/navigation.tsx`: **notification
  bell** with unread badge + dropdown in the staff header (own notifications,
  mark-read / mark-all), new Clients nav entry.
- `tsc --noEmit` clean, ESLint clean.

**Live verified (rebuilt + recreated `asto-backend` + `frontend`):**
- Staff login (`staff@asto.local`, password inherited `admin123` from the
  demo seed that cloned the admin hash) → `GET /staff/clients` returns the 2
  assigned clients each with properties/cases/documents incl. `approval_status`
  (client 1 → docs 444 approved + 445 pending; client 37 → doc 446 approved).
- **End-to-end flow (full chain):** staff `POST /staff/documents/upload` for
  client 1 → 201, `storage/pending/<uuid>_phase_g_test.txt` + `.meta.json`
  sidecar (`client_id=1, uploaded_by=29`), and the admin was auto-notified
  ("New document awaiting review - staff@asto.local uploaded 'phase_g_test.txt'",
  `document_upload`, unread=1). Ran `python -m app.documents.ingest_batch` in
  the container → indexed **doc 1025**, version 1, `approval_status=pending`,
  `uploaded_by_email=staff@asto.local`. Admin then `PATCH /admin/documents/1025`
  (→ `updated=[title,doc_type]`) and `POST …/1025/reject` with reason
  "Missing client signature on page 3" (→ `{message, reason}`).
- Staff notifications after the reject: **unread=1**, `[document_rejected]`
  "Document rejected — 'Phase G Live Doc (edited)' was rejected: Missing client
  signature on page 3" (link `/staff?tab=clients`); `POST …/notifications/2/read`
  → unread 0. Approval history for 1025 shows `pending → rejected` by
  admin@asto.local with the reason persisted.
- All routes 200 after `-L`: `/login`, `/admin`, `/staff`, `/client`, `/portal`;
  the deployed admin chunk (`page-490b73f66fa732c8.js`) contains the new
  "Edit document metadata" / "Reject document — reason is required" UI markers.

**Not done / carry to next session:**
- None for Phase G.

### Session 3 — 2026-08-08

**Done (Phase B3 + Phase C — approval workflow + client auth backend):**
- **Approval workflow (B3):**
  - `indexing.py` now inserts documents/chunks with `approval_status='pending'`,
    `is_approved=false` by default (opt-in `approval_status="approved"` for seed/backfill).
    Pending docs are invisible to search (search filters on `is_approved=true`).
  - New `api/v1/approvals.py`: `GET /admin/documents/pending`,
    `POST /admin/documents/{id}/approve`, `POST /admin/documents/{id}/reject`,
    `GET /admin/documents/{id}/history`. Transitions document + all chunks
    transactionally and writes `approval_log` (reviewer, from→to, timestamp).
  - `documents.py` list now exposes `approval_status`/`approved_by`/`approved_at`.
- **Client auth (C):**
  - `jwt_handler.create_token` gains `audience` ("staff"/"client") + optional
    `client_id` claims.
  - `POST /auth/client-login` authenticates against the `clients` table.
  - `dependencies.get_current_user` resolves BOTH audiences: staff → `users`,
    client → `clients` tagged `audience="client"` + `client_id`.
  - `permissions.require_role` is now fail-closed for the client audience and
    unknown roles (closed a fail-open hole that let "client" pass role checks).
  - New `api/v1/client.py` (client-scoped, own data only): `/client/me`,
    `/client/properties`, `/client/cases`, `/client/documents`.
  - `api/v1/admin.py` extended (C3): `POST /admin/users`, `GET+POST /admin/clients`,
    `POST /admin/assignments` (staff↔client scoping).
- **Seed:** `scripts/seed_db.py` seeds client@asto.local / **client123**, a property,
  a case (CAS-2026-0001), admin→client assignment, and a pending-review document.
- **Tests:** 140 unit + 11 integration pass (151 total). New `test_approvals.py` and
  `test_client_auth.py`. Fixed a subtle test-isolation issue: `test_approvals.py`
  originally imported `app.main` at module scope, which bound
  `dependencies.acquire` to the real DB function before conftest's autouse mock ran
  (breaking the "mock DB has no users" assumption for later files) — imports are now
  lazy inside test bodies, matching existing convention.
- **Live verification** (docker compose backend rebuilt + restarted): client login → me/
  properties/cases/documents all 200; client search returns scoped results; client
  hitting `/admin/*` → 403; admin list pending → approve → searchable + audit trail;
  reject → not searchable (`no_answer`) + audit trail.

**Not done / carry to next session:**
- Phase D: chat UX (thread UI, 24h localStorage history, typing UX) — not started.
- Phase E: admin dashboard UI — not started.
- `frontend` npm deps still not installed on host (verified via Docker build only).
- No new evaluation benchmark run needed (no ranking/confidence changes this session).

### Session 2 — 2026-08-08

**Done (Phase A — baseline verification):**
- Added **Sumy extractive summary** (user-approved, CLAUDE.md doctrine relaxed):
  `response/summarizer.py` (TextRank, 4 verbatim sentences, self-contained
  tokenizer — no NLTK model download), wired into ResponsePackage, `/search`,
  and frontend `ResponsePackageCard` "Key Points" card. Fixed circular import.
- Created `backend/.venv` (CPython 3.11.15 via uv) + installed requirements/dev.
  Note: host Python 3.14 is too new for fastembed/onnxruntime — use the venv.
- **107 unit tests pass** (fixed: needed `backend/.env` from `.env.example` —
  empty `jwt_secret` caused 2 PyJWT failures).
- **7 integration tests pass, 4 skipped** (e2e tests need live Postgres; run
  after compose is up).
- `docker compose up -d --build` (ports 5433/8011/3011): all 3 containers
  healthy. `/health` → `{"status":"healthy"}`. Frontend serves on 3011.
- Seeded DB (`scripts/seed_db.py`, admin@asto.local / **admin123**) then ran
  `scripts/backfill_embeddings.py` (6 chunks had no embedding). First search
  returned no results because search requires `embedding IS NOT NULL`.
- Verified end-to-end: login → search "minimum credit score for loan" →
  routing=answer, title + 3-sentence summary with source citations + 2 excerpts.
- **Evaluation benchmark run** → `evaluation/reports/benchmark_20260808_005649.json`:
  sub-question 100%, intent 58.3%, entity 91.7%; hit_rate@5 91.7%, ndcg@10
  85.4%, MRR 75%; end-to-end search p50 10.8ms / p95 20.8ms; cold start 368ms.
- Downloaded bge-small-en-v1.5 (~66MB) to host `backend/nlp_models/embeddings/`
  (user-approved) for benchmark retrieval phase.

**Not done / blocked:**
- `frontend` npm deps still not installed (`npm ci`) — frontend verified via
  Docker build, not `npm run lint`/`next build` on host.
- None of Phase B–E (dual-audience model, approval workflow, client auth, chat
  UX, admin dashboard).

### Session 1 — 2026-08-08

**Done:**
- Audited project structure, docs, compose, schema, search pipeline, infra.
- Renamed project **Hexta/HeXta → Asto** everywhere (39 files + 6 file renames):
  env prefix `HEXA_`→`ASTO_`, DB `hexa_assistant`→`asto_assistant`, user
  `hexa_app`→`asto_app`, containers/services `hexa-*`→`asto-*`, systemd units,
  nginx conf, package.json name, UI title, docs, CI. Verified zero `hexa`
  matches remain (excluding node_modules/.venv).
- Reassigned ports to avoid clashes: 5433 / 8011 / 3011 (see table above),
  updated compose, Dockerfile, nginx, systemd, .env examples, api-client,
  package.json dev script, infra scripts, README/SKILL/design docs, deploy CI.
- Created this file (`SESSION.md`) + `TEMPLATE.md`.

**Not done / blocked (carry to next session):**
- Full runtime test run (needs venv: Python 3.11 + `pip install -r
  requirements.txt -r requirements-dev.txt`).
- Docker compose up + health check (needs Docker running).
- All the new dual-audience / approval / chat / admin work below.

---

## Next Steps (prioritized — work in this order)

### Phase A — Baseline verification ✅ DONE (Session 2)
- [x] A1: Create `backend/.venv` with Python 3.11; install requirements + dev.
- [x] A2: `pytest tests/unit -q` and `pytest tests/integration -q` — fix failures.
      (Includes new `tests/unit/test_summarizer.py` — Sumy extractive summary.)
- [x] A3: `docker compose up -d` (ports 5433/8011/3011) and hit `/health`.
- [x] A4: Run `evaluation/run_benchmark.py`, record report in `evaluation/reports/`
      (`benchmark_20260808_005649.json`).

### Phase B — Data model for dual-audience (schema + models + migrations)
- [x] B1: Add tables: `clients`, `properties`, `cases` (mortgage/case), and
      `client_document_access` / ownership links. (Schema existed; verified + seeded.)
- [x] B2: Scope staff by assigned client/case (`staff_client_assignments`), keep
      department RBAC. (Filters existed; admin assignment endpoint added Session 3.)
- [x] B3: Add document **Pending/Approved/Rejected** state machine + reviewer
      audit trail (who/when approved). (API + pending-on-ingest + audit trail added
      Session 3.)
- [x] B4: Wire scoping into `search/metadata_filters.py` WHERE clause (staff =
      dept ∩ assigned clients; client = own client_id only). Keep rule #1. (Existed;
      verified end-to-end with client audience.)

### Phase C — Auth for both audiences
- [x] C1: Client role + client identity in JWT; separate login for clients.
- [x] C2: Authorization **before** retrieval and before any context reaches LLM
      (there is no LLM today — preserve that guarantee).
- [x] C3: Admin/super_admin-only endpoints for approval + user management.

### Phase D — UX
- [x] D1: Chat view (chat-style conversation, message bubbles, streaming-lite).
      (Conversation + typing indicator done Session 4; true streaming not started.)
- [x] D2: 24-hour local-only history (localStorage), no server persistence by
      default. (Done Session 4 — `use-chat-history.ts`.)
- [x] D3: Separate admin dashboard (approvals queue, uploads, analytics).
      (Done Session 4 — `/admin`; uploads + knowledge-gaps + user/client mgmt.)
- [x] D4: Client portal + client login (added Session 4 alongside D1–D3:
      `/portal`, Staff/Client login tabs).

### Phase E — Documentation & consistency (done Session 5, 2026-08-08)
- [x] E1: Update `README.md`, `Final_System_Design.md`, `Final_Folder_Structure.md`
      for dual-audience + approval workflow.
- [x] E2: Update `SKILL.md` build order with new phases if architecture changes
      (added Phase 6.5 — Dual-Audience Auth + Approval Workflow + Frontend UX).
- [x] E3: Re-run evaluation benchmark after any retrieval-affecting change —
      **none made.** The only retrieval-path change in Sessions 3–4 was the
      `is_approved`/`is_active` hard pre-filter in
      `search/metadata_filters.py` (`get_version_filter`, line 100), which
      reduces the candidate set without touching ranking weights, confidence
      thresholds, or the reranker. Baseline `benchmark_20260808_005649.json`
      stands; no re-run required.

### Phase F — Remaining views: not-implemented features (added 2026-08-10)
Build order for the disabled sidebar views + carry-overs. **Audit Log is last
by design.** Existing-backend items come before new-schema items. Each phase's
DoD: endpoints tested under `backend/tests/`, docs updated, live-verified after
rebuild. ⚠️ = needs a design decision before building (stop and ask).

- [x] **F1 Foundation & carry-over fixes:** place real PDFs matching seeded
      `source_path` basenames into `storage/processed/` so admin + client
      document View works end-to-end; fix stale analytics carry-over note
      (charts already exist in `/admin` Analytics tab). *(Done Session 8 —
      seed generates PDFs into `storage/processed/`; View returns 200.)*
- [x] **F2 Admin Dashboard + Settings:** new `/admin/summary` endpoint
      (pending approvals, documents, users, clients, gaps) + admin Dashboard
      stat-card view; admin Settings view (frontend prefs). *(Done Session 8 —
      summary returns 7 counts; Dashboard + Settings tabs live.)*
- [x] **F3 Admin governance:** Knowledge Base browse (read-only
      `/admin/documents/{id}/chunks` + view); SOP Management view (reuse
      `/staff/sops` + `/admin/sop-access-requests` review, add admin read-all
      SOPs endpoint); Roles & Permissions / Departments — **config-driven**
      editor (`app/auth/roles_config.py` is the single source of truth; admin
      read-only governance view). *(Done Session 8 — decision: config over DB.)*
- [x] **F4 Staff operational views (backend exists — frontend only):**
      Dashboard (`/staff/dashboard`), My Cases (`/staff/cases/{id}/notes`),
      Workflows (`/staff/workflows/{id}/advance`), SOPs (CRUD + access
      requests). *(Done Session 8 — new `/staff` page + login routing.)*
- [x] **F5 Staff Tasks + client Home/Help:** Tasks — **derived from workflows**
      (decision: no new table — each active in_progress/review workflow is a
      task with an Advance action); client Home (overview cards from existing
      me/properties/cases/documents endpoints); client Help (static content).
      *(Done Session 8.)*
- [x] **F6 Messages + Collaboration (new schema):** ⚠️ neither exists; both
      need new tables + endpoints with RBAC scoping in the SQL WHERE clause
      (CLAUDE.md rule 1). *(Done Session 9 — user chose full messages system:
      `conversations` + `messages` tables, case-anchored; client `messages` +
      staff `collaboration` views; 16 tests; 345 total.)*
- [x] **F7 Audit Log viewer (LAST):** new `/admin/audit` endpoint (filterable:
      user, date-range, outcome) + admin Audit Log view with pagination.
      *(Done Session 9 — filterable + paginated audit view; 10 tests; 355
      total. Phase F fully complete.)*

### Phase H+ — Product roadmap (added 2026-08-12)

> **Full detailed plan lives in `docs/ROADMAP.md`** — every planned feature
> (security hardening, documents/review, search, client experience, staff ops,
> system/ops, polish) with implementation steps, DoD, dependencies, and a
> feature tracker. Implementation proceeds phase-by-phase from that file.

### Phase G — Staff client-data interface + doc review w/ metadata edit + notifications (added 2026-08-12)
User-driven feature set. Each phase DoD: endpoints tested under
`backend/tests/`, docs updated, live-verified after rebuild. DoD per
CLAUDE.md (RBAC in the SQL WHERE clause, batch-only ingestion, no new
standing services).

- [x] **G0 Notifications (new schema):** generic `notifications` table
      (`id`, `user_id`, `type`, `title`, `body`, `link`, `is_read`,
      `created_at`) + `GET /notifications` (own only, RBAC in WHERE) +
      `POST /notifications/{id}/read` (+ mark-all-read). Generic so SOP
      outcomes + message pings are just new rows later. *(Done Session 13 —
      `api/v1/notifications.py`, scoped reads, read/read-all, generic helper.)*
- [x] **G1 Staff document upload:** add `uploaded_by` (→ users.id) to
      `documents`; new `POST /staff/documents/upload` scoped to a client
      the staff member is assigned to (mirrors `client.py` upload flow:
      validate → `storage/pending/` sidecar, batch ingestion later; never
      inline). Duplicate-titled re-upload = version bump (Session 10).
      *(Done Session 13 — assignment-scoped upload, sidecar, admin notified.)*
- [x] **G2 Admin review enhancement:** `PATCH /admin/documents/{id}` for
      **metadata only** (title / doc_type / department — no file replace);
      reject endpoint gains a **required `reason`** (persisted to the unused
      `approval_log.reason` column). *(Done Session 13.)*
- [x] **G3 Auto-notify on review:** approve/reject auto-creates a
      notification for the uploader (body carries approve note or reject
      reason) — wired in `approvals.py`, never skipped. *(Done Session 13.)*
- [x] **G4 Staff Clients tab:** new staff view listing assigned clients →
      their properties, cases, and documents **with approval status**.
      *(Done Session 13.)*
- [x] **G5 Staff upload UI + notification bell:** document-upload dialog on
      the Clients tab; notifications bell/badge (unread count) in the staff
      AppShell header. *(Done Session 13.)*
- [x] **G6 Admin Approvals tab:** metadata-edit dialog + reject-with-reason
      dialog in the Approvals queue. *(Done Session 13.)*
- [x] **G7 Tests:** unit tests for notifications CRUD, staff upload scoping,
      metadata edit, reject-reason persistence, auto-notify. Full suite must
      stay green (366 → more). *(Done Session 13 — `test_phase_g.py` 24
      tests; full suite **390 passed**.)*
- [x] **G8 Verify:** `tsc` + `lint` + `pytest -q`; SESSION.md updated;
      docker rebuild + live verification (staff upload → admin edit/reject →
      staff sees notification). *(Done Session 13 — 390 passed, tsc/lint
      clean, full chain live-verified end-to-end, SESSION.md updated.)*
      **Phase G complete.**
---

## Open Questions / Decisions for the User

1. **Abstractive summarization / LLM on the serving path?** Today: none, by
   design. An **extractive** summary (Sumy TextRank, 4 verbatim sentences with
   citations) was added on 2026-08-08 and is fully compliant. Abstractive
   synthesis (an LLM, T5/BART, "rewrite this in your own words") would break
   the compliance guarantee and requires an explicit decision — not
   recommended.
2. **Client data source** — will clients/properties/cases be seeded from an
   existing CRM/DB, or entered manually via admin? (Admin CRUD for users +
   clients exists now; a CRM import script can be added when the source is known.)
3. **Chat history** — confirm 24h localStorage is acceptable (per your brief).
4. **Deployment target** — keep shared-host EC2 (1GiB) model, or move to a
   bigger instance once admin dashboard + chat added?
5. **New-document default** — ingestion now inserts as `pending` (must be
   approved before searchable). Confirm that's the desired default for the
   production ingest path (`index_document` supports `approval_status="approved"`
   if a trusted backfill path ever needs to bypass review).
