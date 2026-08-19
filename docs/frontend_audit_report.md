# Asto Frontend — Read-Only Audit Report

Scope: `frontend/` (Next.js + TypeScript + Tailwind + shadcn/ui) audited against the
FastAPI backend contract (`backend/app/api/v1/`) and the design constraints in
`CLAUDE.md` / `docs/`. All findings below cite exact `file:line` references.
No files were modified during the audit.

---

## 1. Architecture overview (as-built)

| Aspect | Detail | Ref |
|---|---|---|
| Rendering | Next static export (`output: 'export'`, `trailingSlash: true`, images unoptimized) — zero SSR | `frontend/next.config.js:3-7` |
| Data access | Direct FastAPI calls, no BFF; `API_BASE_URL = NEXT_PUBLIC_API_URL \|\| http://localhost:8011/api/v1` | `frontend/lib/api-client.ts:6` |
| Fetch wrapper | `apiFetch` adds `credentials: 'include'` only (no timeout, no 401 handling) | `frontend/lib/api-client.ts:9-11` |
| Access token | JWT kept in JS memory only; per-request `Authorization: Bearer` | `frontend/lib/auth.ts:2,42` |
| Refresh session | HttpOnly `asto_refresh` cookie exchanged via `POST /auth/refresh` with `X-Asto-CSRF` header | `frontend/lib/api-client.ts:339-351` |
| Framework version | `next ^14.2.15` in package.json; README claims Next.js 15 | `frontend/package.json:31`, `frontend/README.md:3` |
| AuthZ model | Client-side role/audience claims (unverified decode) used only for UI routing; enforcement is server-side | `frontend/lib/auth.ts:44-51` |

Backend facts that shape the frontend:

- Access JWT lifetime is **480 minutes (8h)**; refresh cookie TTL 30 days.
  `backend/app/config.py:47,51`
- Refresh cookie: HttpOnly, `samesite=lax`, `secure=False` by default (must set
  `ASTO_AUTH_COOKIE_SECURE=true` behind TLS). `backend/app/config.py:53-54`,
  `backend/app/api/v1/auth.py:203-212`
- `POST /api/v1/health` serves DB/storage/ingest status. `backend/app/main.py:88-122`
- There is **no** `/health` route in the v1 routers; the frontend's `getSystemHealth`
  correctly hits the app-level endpoint. `frontend/lib/api-client.ts:2325-2334`

---

## 2. API contract (frontend ↔ backend)

Every endpoint called by the frontend resolves to an existing backend route.
No path, method, or payload mismatches were found. Verified endpoint map:

| Frontend (api-client.ts) | Backend route |
|---|---|
| `getSearchSuggestions` `:24` | `GET /search/suggest` `search.py:428` |
| `searchKnowledgeBase` `:166` | `POST /search/` `search.py:419` |
| `searchKnowledgeBaseStream` `:221` (SSE) | `POST /search/stream` `search.py:448` |
| `login` `:316` / `twoFactorLogin` `:357` | `POST /auth/login` / `POST /auth/2fa` `auth.py:266,374` |
| `refreshSession` `:339` | `POST /auth/refresh` `auth.py:514` |
| `logout` `:444` / `logoutAll` `:456` | `POST /auth/logout` / `logout-all` `auth.py:581,598` |
| `verifyToken` `:468` | `POST /auth/verify` `auth.py:750` |
| `changePassword` `:519` / `forgotPassword` `:549` / `resetPassword` `:567` | `auth.py:780,635,692` |
| `twoFaStatus/Setup/Verify/Disable` `:385-431` | `GET /admin/2fa/status`, `POST /admin/2fa/{setup,verify,disable}` `admin.py:75-177` |
| `submitFeedback` `:489` | `POST /feedback/` `feedback.py:20` |
| `updateClientProfile` `:598` | `PATCH /client/me` `client.py:771` |
| `getClientMe` `:672` … `clientUploadDocument` `:888` | `/client/me`, `/properties`, `/cases`, `/cases/{id}`, `/cases/{id}/checklist`, `/documents`, `/documents/rejected`, `/documents/{id}/rejections`, `/properties/{id}/documents`, `/signature-requests`, `/documents/upload` — `client.py:74-465` |
| `listPendingDocuments` `:959` … `getAdminTags` `:1107` | `/admin/documents/*` (pending/approve/reject/bulk/history/versions/tags) — `approvals.py:119-585` |
| `listAllDocuments` `:1139`, `uploadDocument` `:1154`, `getDocumentFile` `:1173` | `GET /documents/`, `POST /documents/upload`, `GET /documents/{id}/file` — `documents.py:20,58`, `upload.py:23` |
| `getStaffDashboard` `:1291` … `advanceWorkflow` `:1662` | `/staff/dashboard`, `/tasks`, `/clients/{id}/360`, `/workflow-definitions`, `/message-templates`, `/appointments`, `/documents/{id}/file`, `/cases/{id}/notes`, `/workflows/{id}/advance` — `staff.py:224-1588` |
| `createSop/updateSop` `:1683,1699`, `getMySopRequests` `:1716`, `createSopAccessRequest` `:1727` | `POST/PUT /staff/sops`, `GET/POST /staff/sop-access-requests` — `staff.py:568-687` |
| `listSopAccessRequests` `:1743`, `reviewSopAccessRequest` `:1758` | `GET /admin/sop-access-requests`, `POST .../{id}/review` — `admin.py:551,577` |
| Client/staff conversations `:1815-1909` | `/client/conversations*`, `/staff/conversations*` — `client.py:565-613`, `staff.py:824-867` |
| `getAdminAudit` `:1947`, `exportAuditLogCsv` `:1970` | `GET /admin/audit`, `GET /admin/audit/export?format=csv` — `admin.py:1028,1155` |
| `onboardClient` `:2018`, `getStaffClients` `:2539`, `staffUploadDocument` `:2552` | `POST /staff/clients`, `GET /staff/clients`, `POST /staff/documents/upload` — `staff.py:754,898,1188` |
| Users/clients/sessions/assignments `:2053-2200` | `/admin/users`, `/admin/clients`, `/admin/users|clients/{id}/sessions[/revoke]`, `/admin/assignments` — `admin.py:213-486` |
| Analytics `:2214-2277` | `/analytics/knowledge-gaps`, `/summary`, `/document-popularity` — `analytics.py:14,159,178` |
| `getAdminSummary` `:2294` | `GET /admin/summary` — `admin.py:229` |
| `getFeatureFlags`/`setFeatureFlag` `:2346,2358` | `GET/POST /admin/flags` — `admin.py:992,1005` |
| `getDocumentChunks` `:2393`, `listAllSops` `:2419` | `GET /admin/documents/{id}/chunks`, `GET /admin/sops` — `admin.py:717,745` |
| `getGovernance`/`updateGovernance` `:2452,2472` | `GET/PUT /admin/governance` — `admin.py:761,846` |
| `getNotifications` `:2589`, `mark*Read` `:2602,2617`, `openNotificationStream` `:2645` | `GET /staff/notifications`, `POST .../{id}/read`, `POST /read-all`, `GET /staff/notifications/stream` — `notifications.py:107-269` |
| `updateDocumentMetadata` `:2736` | `PATCH /admin/documents/{id}` — `approvals.py:395` |
| Saved searches `:56,68,88` | `GET/POST/DELETE /staff/saved-searches*` — `saved_searches.py:54-110` |

### Backend endpoints present but unused by the UI
- `POST /auth/client-login` (unified `/auth/login` is used instead) — `auth.py:464`
- `GET /client/me/export`, `GET /admin/clients/{id}/export` — `client.py:95`, `admin.py:513`
- `GET/POST/DELETE /admin/synonyms*` — `admin.py:624-689`
- `GET /admin/case-requirements/*` — `admin.py:1245-1273`
- `POST/GET /admin/signature-requests` — `admin.py:1302-1346`
- `GET /client/cases/{id}/timeline` — the UI uses `/client/cases/{id}` (which embeds
  `events`) instead — `client.py:735`, `frontend/lib/api-client.ts:709-721`
- `GET /staff/sops` (staff read access to SOPs) — `staff.py:568`

These are not bugs, but represent either planned features (case requirements,
synonyms) or contract surface that will drift without frontend consumers.

---

## 3. Auth & session handling

- **Access token is memory-only; sessions survive reloads via the HttpOnly cookie.**
  `restoreSession()` is called in the page-gate effect of every shell page.
  `frontend/lib/auth.ts:76-85`, `frontend/app/page.tsx:97-141`,
  `frontend/app/client/page.tsx:1542-1557`
- **No 401→refresh interceptor.** `apiFetch` never inspects responses; if the 8h
  access JWT expires while a page is open, every subsequent API call 401s and the
  only recovery is a manual reload (the refresh cookie would still work).
  `frontend/lib/api-client.ts:9-11`, `backend/app/config.py:47`
- **`rememberMe` is decorative.** `storeToken(token, remember)` ignores the second
  argument; cookie persistence (and its expiry) is entirely server-side, yet the
  login screen presents the checkbox as a user decision.
  `frontend/lib/auth.ts:54-56`, `frontend/app/login/page.tsx:31,81,102`
- **Reset-password token is stripped from the URL** immediately after read
  (`history.replaceState`), so it can't linger in history/bookmarks.
  `frontend/app/login/page.tsx:38-48`
- **Role routing relies on an unverified JWT decode.** `decodeToken` is
  `atob`+`JSON.parse` with no signature check. Used only for UI routing / display
  (`/login`, `/client`, `/admin`), so it is not an authorization boundary — but the
  client portal also derives the localStorage chat-session scope from
  `decodeToken(token)?.client_id`. `frontend/lib/auth.ts:44-51`,
  `frontend/app/client/page.tsx:1537-1540`
- Client-side idle auto-timeout (15/30/60 min or off) is a **UI-only timer**; it
  uses blocking `window.confirm` and does not revoke the server session.
  `frontend/app/page.tsx:176-208`, `frontend/app/client/page.tsx:1694-1727`,
  `frontend/components/settings/SettingsModal.tsx:77-82`

---

## 4. Security

- **CSP relies on `'unsafe-inline'` and `'unsafe-eval'`.** Required for Next's static-export
  RSC bootstrap, but it materially weakens XSS defense-in-depth. No HSTS/CSP-report or
  other security headers are set in nginx.
  `frontend/nginx.conf:11`
- **Only one `dangerouslySetInnerHTML` in the entire app**: the constant theme
  no-flash bootstrap (no user data interpolated).
  `frontend/app/layout.tsx:29,39`
- **Chat rendering is XSS-safe**: answers/excerpts render as React text nodes
  (`ChatMessage`, `HighlightedText`, `SourceCitation`); no HTML parsing was found.
- **Document preview uses blob URLs + `<iframe>`** (`DocumentPreviewDialog`). Uploaded
  files are backend-validated, but an HTML/scriptable file served as a blob in the app
  origin would execute scripts. Verify the upload validator's allow-list covers
  MIME-by-content, not just extension.
- **Sensitive chat history persists in `localStorage` after sign-out.** Chat turns
  (queries + retrieved excerpts) live in `asto_chat_history` and
  `asto_chat_sessions:<scope>` with a 24h TTL; `handleLogout` clears the token but not
  these keys. On a shared/browser-restored device this leaves mortgage-related content
  readable after logout.
  `frontend/hooks/use-chat-history.ts:14-15`, `frontend/hooks/use-chat-sessions.ts:22-26`,
  `frontend/app/client/page.tsx:1586-1603`, `frontend/app/page.tsx:149-168`
- **No secrets in the frontend bundle.** Only `NEXT_PUBLIC_*` build-time URLs
  (`frontend/lib/api-client.ts:6`, `frontend/hooks/use-mobile-app.ts:30`,
  `frontend/hooks/use-browser-extension.ts:26`); no API keys were found.
- **Refresh-cookie `secure` defaults to `False`**; must be enabled via
  `ASTO_AUTH_COOKIE_SECURE=true` in production or the 30-day credential rides plain
  HTTP. `backend/app/config.py:53`, `backend/app/api/v1/auth.py:208-210`
- 2FA TOTP secret and `otpauth_uri` are rendered and clipboard-copyable during
  enrollment (expected), with a cancel path that discards state.
  `frontend/components/settings/SettingsModal.tsx:226-297`

---

## 5. PWA & offline

- Service worker caches the shell (`/`, `/login/`, `/offline.html`) on install and
  registers only in production builds.
  `frontend/public/sw.js:1-2`, `frontend/components/pwa/ServiceWorkerRegister.tsx`
- `/api/` requests are **network-only with cached fallback** (serves a 503 JSON when
  offline); navigations are network-first with cache fallback to `/`.
  `frontend/public/sw.js:26-29,31-44,61-77`
- Manifest points `start_url` to `/login/`; PWA opens at the auth gate.
- Offline page (`offline.html`) is present and dark-theme-styled.
- `manifest.webmanifest` sets `display: standalone`, `orientation: portrait`.

---

## 6. Infrastructure & deployment

- Docker build bakes `NEXT_PUBLIC_API_URL=/api/v1` and ships the export to
  `nginx:1.27-alpine`; nginx proxies `/api/` → `http://asto-backend:8011` with
  15s/30s timeouts. `frontend/Dockerfile:13`, `frontend/nginx.conf:13-21`
- The local `npm run start` (`next start`) is incompatible with `output: 'export'` —
  only the `dev`/`build`/nginx path actually works. `frontend/package.json:8`,
  `frontend/next.config.js:3`
- `cors_origins` defaults to `http://localhost:3011` only; production must list the
  real frontend origin or credentialed cookie requests will be rejected.
  `backend/app/config.py:89`

---

## 7. UX & robustness

- **No request timeouts or aborts.** A hung backend leaves the chat/spinner state
  stuck indefinitely (SSE readers only reject when the socket closes).
  `frontend/lib/api-client.ts:9-11,251-314`
- **Notification SSE stream requires manual reconnect** — the client exposes an
  abort function and `onClose` but performs no backoff/reconnect itself.
  `frontend/lib/api-client.ts:2645-2734`
- Saved-search list is capped client-side at 50. `frontend/app/page.tsx:308`
- Idle-timeout + suggestions logic is copy-pasted between `app/page.tsx` and
  `app/client/page.tsx` (single source-of-truth opportunity).
- `use-toast`/`<Toaster>` infra is mounted but **no call site uses `toast()`**; pages
  use inline `<Alert>` instead — dead weight.
  `frontend/app/layout.tsx:44`, `frontend/hooks/use-toast.ts:145`
- `isTokenExpired` is exported but never used. `frontend/lib/auth.ts:109-118`

---

## 8. Accessibility

- File dropzone is keyboard-operable (`role="button"`, `tabIndex=0`, Enter/Space)
  with labelled inputs and per-file remove buttons.
  `frontend/components/upload/FileDropzone.tsx:60-123`
- Login and settings flows use labelled inputs, `autoComplete`, and aria-labelled
  show/hide-password toggles. `frontend/app/login/page.tsx:299-310`,
  `frontend/components/settings/SettingsModal.tsx:638-647`
- **The automated axe audit only covers `/`, `/login/`, `/admin/`** — the client and
  staff portals (the most-used surfaces) are never scanned.
  `frontend/scripts/axe-audit.mjs:16`
- **The audit skips silently (exit 0) when Chromium isn't installed**, so a CI gate
  built on it can pass vacuously. `frontend/scripts/axe-audit.mjs:81-87`

---

## 9. Testing & quality gates

| Gate | Present? | Notes |
|---|---|---|
| Unit/component tests | No | No test framework or `test` script |
| Test files | None | `**/*.{test,spec}.{ts,tsx,js,jsx}` = 0 matches |
| Typecheck | No | No `tsc --noEmit` script (only `tsc` at build) |
| Lint | Yes | `eslint . --ext .ts,.tsx` (`package.json:9`) |
| A11y | Partial | `axe-audit.mjs`; 3 of 6 routes, vacuous skip |
| CI integration | None found | No workflow files checked |

`frontend/package.json:5-11`

---

## 10. Top-10 prioritized findings

1. **No automated tests, no typecheck, and the a11y gate can pass vacuously.**
   `frontend/package.json:5-11`, `frontend/scripts/axe-audit.mjs:16,81-87`
   Regression risk on every phase change; add a test runner + `tsc --noEmit`, and make
   the axe audit fail when Chromium is missing.

2. **8-hour access token can expire mid-session with no 401→refresh interceptor.**
   `frontend/lib/api-client.ts:9-11`, `frontend/app/page.tsx:97-141`,
   `backend/app/config.py:47`. A single failed-401 retry with `refreshSession()`
   would close the gap.

3. **Chat history (queries + retrieved excerpts) persists in `localStorage` after
   sign-out.** `frontend/hooks/use-chat-history.ts:14-15`,
   `frontend/hooks/use-chat-sessions.ts:22-26`, `frontend/app/client/page.tsx:1586-1603`.
   Clear these keys on logout or gate the client portal history behind the session.

4. **`rememberMe` checkbox is decorative** — the flag is dropped in `storeToken`.
   `frontend/lib/auth.ts:54-56`, `frontend/app/login/page.tsx:31`. Either wire it to a
   server "persistent session" flag or remove it.

5. **Refresh-cookie `secure=False` by default** and CSP requires `unsafe-inline`/
   `unsafe-eval`. `backend/app/config.py:53`, `frontend/nginx.conf:11`. Add HSTS and
   document/require `ASTO_AUTH_COOKIE_SECURE=true` for TLS deployments.

6. **Blob-iframe document preview runs uploads in the app origin.**
   `frontend/components/documents/DocumentPreviewDialog.tsx`; confirm the backend
   upload validator rejects scriptable content by file magic, not extension.

7. **A11y audit covers 3 of 6 routes and skips client/staff portals.**
   `frontend/scripts/axe-audit.mjs:16`. Add `/client/` and `/staff/` to `ROUTES`.

8. **No timeout/abort handling on any API call; notification SSE has no reconnect.**
   `frontend/lib/api-client.ts:9-11,2645-2734`. Add timeouts and retry-with-backoff.

9. **Unused surface + dead code**: `use-toast`/`<Toaster>` never invoked,
   `isTokenExpired` never called, `npm run start` broken for static export.
   `frontend/app/layout.tsx:44`, `frontend/lib/auth.ts:109-118`,
   `frontend/package.json:8`.

10. **Idle-timeout/suggestions logic is duplicated across staff and client pages**
    and the client-only session-scope key is derived from an unverified JWT claim.
    `frontend/app/page.tsx:77-85,176-208`, `frontend/app/client/page.tsx:1526-1534,1694-1727,1537-1540`.
    Extract a shared hook; scope by authenticated identity from `getSession()`.