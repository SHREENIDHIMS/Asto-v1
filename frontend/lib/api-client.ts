// API client — calls FastAPI directly, no BFF proxy.
// Access JWT is held in memory (lib/auth) and sent per-request as Bearer.
// Every request also sends `credentials: 'include'` so the HttpOnly
// asto_refresh cookie flows (Phase H1) and Set-Cookie is accepted.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8011/api/v1';

/** True when the request carries a Bearer token (i.e. it is authenticated). */
function hasAuthHeader(init?: RequestInit): boolean {
  if (!init?.headers) return false;
  try {
    return new Headers(init.headers).has('Authorization');
  } catch {
    return false;
  }
}

/**
 * Re-issue an authenticated request with a fresh access token after a 401.
 * The 8h access JWT can expire mid-session (it lives in memory only); the
 * HttpOnly refresh cookie lets us transparently re-authenticate instead of
 * dead-ending the UI until a manual reload.
 */
async function refreshAndRetry(url: string, init?: RequestInit): Promise<Response | null> {
  try {
    const session = await refreshSession();
    const headers = new Headers(init?.headers);
    if (headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${session.access_token}`);
    }
    return await fetch(url, { ...init, headers, credentials: 'include' });
  } catch {
    return null;
  }
}

/** fetch wrapper that always sends cookies for the refresh session. */
async function apiFetch(url: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(url, { ...init, credentials: 'include' });
  if (response.status === 401 && hasAuthHeader(init)) {
    const retried = await refreshAndRetry(url, init);
    if (retried) return retried;
  }
  return response;
}

export interface SearchRequest {
  query: string;
  case_id?: number | null;
  filters?: SearchFilters | null;
}

/** J4 — prefix-matched past-query suggestions (scoped to the caller). */
export interface SuggestResponse {
  suggestions: string[];
}

export async function getSearchSuggestions(
  prefix: string,
  token?: string
): Promise<string[]> {
  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  const response = await apiFetch(
    `${API_BASE_URL}/search/suggest?q=${encodeURIComponent(prefix)}`,
    { headers }
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || 'Failed to load suggestions');
  }
  const data = (await response.json()) as SuggestResponse;
  return data.suggestions ?? [];
}

/** J7 — saved searches (staff-only, per-user scoped server-side). */
export interface SavedSearch {
  id: number;
  query: string;
  filters: SearchFilters | null;
  created_at?: string | null;
}

export interface SavedSearchListResponse {
  saved_searches: SavedSearch[];
}

export async function listSavedSearches(token: string): Promise<SavedSearch[]> {
  const response = await apiFetch(`${API_BASE_URL}/staff/saved-searches`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || 'Failed to load saved searches');
  }
  const data = (await response.json()) as SavedSearchListResponse;
  return data.saved_searches ?? [];
}

export async function saveSearch(
  token: string,
  query: string,
  filters: SearchFilters | null
): Promise<SavedSearch> {
  const response = await apiFetch(`${API_BASE_URL}/staff/saved-searches`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ query, filters: filters ?? {} }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || 'Failed to save search');
  }
  return response.json();
}

export async function deleteSavedSearch(token: string, id: number): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/staff/saved-searches/${id}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok && response.status !== 204) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || 'Failed to delete saved search');
  }
}

/** Recent searches — the caller's own query history (read from audit_log). */
export interface RecentSearch {
  query: string;
  last_run_at?: string | null;
  times_run: number;
}

// ---------------------------------------------------------------------------
// Admin: pinned answers (curated verbatim response packages)
// ---------------------------------------------------------------------------

export interface PinnedAnswer {
  id: number;
  query: string;
  audience: 'staff' | 'client' | 'any';
  confidence: number;
  source_response_id: string | null;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
  excerpt_count: number;
}

export async function listPinnedAnswers(
  token: string
): Promise<{ pinned_answers: PinnedAnswer[] }> {
  const response = await apiFetch(`${API_BASE_URL}/admin/pinned-answers`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || 'Failed to load pinned answers');
  }
  return response.json();
}

export async function createPinnedAnswer(
  token: string,
  payload: {
    query: string;
    response_id: string;
    audience: 'staff' | 'client' | 'any';
    package: Record<string, unknown>;
  }
): Promise<PinnedAnswer> {
  const response = await apiFetch(`${API_BASE_URL}/admin/pinned-answers`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || 'Failed to pin answer');
  }
  return response.json();
}

export async function patchPinnedAnswer(
  token: string,
  id: number,
  payload: { is_active?: boolean; audience?: 'staff' | 'client' | 'any' }
): Promise<{ message: string; id: number }> {
  const response = await apiFetch(`${API_BASE_URL}/admin/pinned-answers/${id}`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || 'Failed to update pinned answer');
  }
  return response.json();
}

export async function deletePinnedAnswer(token: string, id: number): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/admin/pinned-answers/${id}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok && response.status !== 204) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || 'Failed to delete pinned answer');
  }
}

export async function listRecentSearches(
  token: string,
  limit = 10
): Promise<RecentSearch[]> {
  const response = await apiFetch(
    `${API_BASE_URL}/staff/recent-searches?limit=${limit}`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || 'Failed to load recent searches');
  }
  const data = (await response.json()) as { recent_searches?: RecentSearch[] };
  return data.recent_searches ?? [];
}

/** J2 faceted filters — folded into the search SQL WHERE server-side. */
export interface SearchFilters {
  departments?: string[];
  doc_types?: string[];
  date_from?: string; // ISO date
  date_to?: string; // ISO date (inclusive)
  client_id?: number | null;
}

export interface SearchExcerpt {
  text: string;
  source: {
    title: string;
    section: string | null;
    chunk_type: string;
  };
  confidence: number;
  matched_terms?: string[];
}

export interface StructuredFact {
  label: string;
  value: string | number | null;
  source: string;
  kind: string;
  retrieved_at?: string | null;
}

export interface SearchSummarySentence {
  text: string;
  source: {
    title: string;
    section: string | null;
    chunk_type: string;
  };
  matched_terms?: string[];
}

export interface SearchResponse {
  response_id: string;
  title: string;
  answer: string;
  excerpts: SearchExcerpt[];
  summary: SearchSummarySentence[];
  confidence: number;
  routing: 'answer' | 'partial' | 'no_answer';
  related_questions: string[];
  facts?: StructuredFact[];
  retrieval_path?: 'document' | 'structured_fact';
  no_answer_reason?: string | null;
  citations?: Citation[];
  /** True when served from an admin-curated pinned answer. */
  pinned?: boolean;
  pinned_from_query?: string | null;
}

export interface Citation {
  [key: string]: unknown;
}

export interface AuthLoginRequest {
  email: string;
  password: string;
}

export interface AuthLoginResponse {
  access_token: string | null;
  token_type: string;
  expires_in: number;
  /** H4: true when the account has TOTP enabled and /auth/2fa must be completed. */
  requires_2fa?: boolean;
  /** H4: short-lived, single-use token for the /auth/2fa step. */
  two_fa_token?: string | null;
}

export async function searchKnowledgeBase(
  query: string,
  token?: string,
  caseId?: number | null,
  filters?: SearchFilters | null
): Promise<SearchResponse> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await apiFetch(`${API_BASE_URL}/search/`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ query, case_id: caseId ?? null, filters: filters ?? null }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Search request failed');
  }

  return response.json();
}

export type SearchStage =
  | 'processing'
  | 'searching'
  | 'ranking'
  | 'packaging'
  | 'done';

/** A summary sentence pushed mid-stream (verbatim retrieved text). */
export interface StreamedSentence {
  text: string;
  source: SearchSummarySentence['source'];
  matched_terms?: string[];
}

export interface SearchStreamHandlers {
  onStage?: (stage: SearchStage) => void;
  onFact?: (fact: StructuredFact) => void;
  onSentence?: (sentence: StreamedSentence) => void;
}

/**
 * True streaming search: reads the SSE stream from /search/stream,
 * invoking handlers progressively as content is produced:
 * - onStage for each pipeline stage,
 * - onFact per structured fact (fact path),
 * - onSentence per extractive summary sentence (document path),
 * resolving with the final SearchResponse from the result event.
 */
export async function searchKnowledgeBaseStream(
  query: string,
  token: string | undefined,
  handlers?: SearchStreamHandlers,
  caseId?: number | null,
  filters?: SearchFilters | null
): Promise<SearchResponse> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await apiFetch(`${API_BASE_URL}/search/stream`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ query, case_id: caseId ?? null, filters: filters ?? null }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || 'Search request failed');
  }

  if (!response.body) {
    throw new Error('Streaming not supported by this browser');
  }

  return new Promise<SearchResponse>((resolve, reject) => {
    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    const handleEvent = (event: string, data: string) => {
      if (event === 'status') {
        const parsed = JSON.parse(data) as { stage?: SearchStage };
        if (parsed.stage && handlers?.onStage) {
          handlers.onStage(parsed.stage);
        }
      } else if (event === 'fact') {
        const fact = JSON.parse(data) as StructuredFact;
        if (handlers?.onFact) {
          handlers.onFact(fact);
        }
      } else if (event === 'sentence') {
        const sentence = JSON.parse(data) as StreamedSentence;
        if (handlers?.onSentence) {
          handlers.onSentence(sentence);
        }
      } else if (event === 'result') {
        resolve(JSON.parse(data) as SearchResponse);
      } else if (event === 'error') {
        const parsed = JSON.parse(data) as { detail?: string };
        reject(new Error(parsed.detail || 'Search failed'));
      }
    };

    const pump = (): void => {
      reader.read().then(
        ({ done, value }) => {
          if (done) {
            // Stream closed without a result event.
            reject(new Error('Search stream ended without a result'));
            return;
          }
          buffer += decoder.decode(value, { stream: true });
          // SSE frames are separated by a blank line.
          const frames = buffer.split('\n\n');
          buffer = frames.pop() ?? '';
          for (const frame of frames) {
            let event = 'message';
            const dataLines: string[] = [];
            for (const line of frame.split('\n')) {
              if (line.startsWith('event:')) {
                event = line.slice(6).trim();
              } else if (line.startsWith('data:')) {
                dataLines.push(line.slice(5).trim());
              }
            }
            if (dataLines.length > 0) {
              handleEvent(event, dataLines.join('\n'));
            }
          }
          pump();
        },
        (err) => reject(err)
      );
    };

    pump();
  });
}

export async function login(
  email: string,
  password: string
): Promise<AuthLoginResponse> {
  const response = await apiFetch(`${API_BASE_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Login failed');
  }

  return response.json();
}

/**
 * Exchange the HttpOnly asto_refresh cookie for a fresh access JWT.
 * Called on page load to restore a session (the access token is kept in
 * memory only, so a reload loses it). Requires the CSRF header.
 */
export async function refreshSession(): Promise<AuthLoginResponse> {
  const response = await apiFetch(`${API_BASE_URL}/auth/refresh`, {
    method: 'POST',
    headers: { 'X-Asto-CSRF': '1' },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(error?.detail || 'Session refresh failed');
  }

  return response.json();
}

/**
 * Complete an H4 2FA login: swap the short-lived token + TOTP code for the
 * real access JWT. The refresh cookie is set by the backend on success.
 */
export async function twoFactorLogin(
  twoFaToken: string,
  code: string
): Promise<AuthLoginResponse> {
  const response = await apiFetch(`${API_BASE_URL}/auth/2fa`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ two_fa_token: twoFaToken, code }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Two-factor verification failed');
  }

  return response.json();
}

// ---------------------------------------------------------------------------
// H4: admin 2FA enrollment (TOTP)
// ---------------------------------------------------------------------------

export interface TwoFaSetupResult {
  otpauth_uri: string;
  secret: string;
}

/** Whether the authenticated admin has 2FA enabled. */
export async function twoFaStatus(token: string): Promise<{ enabled: boolean }> {
  const response = await apiFetch(`${API_BASE_URL}/admin/2fa/status`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load 2FA status');
  }
  return response.json();
}

/** Start enrollment: returns a fresh secret + otpauth URI (2FA still off). */
export async function twoFaSetup(token: string): Promise<TwoFaSetupResult> {
  const response = await apiFetch(`${API_BASE_URL}/admin/2fa/setup`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to start 2FA setup');
  }
  return response.json();
}

/** Confirm enrollment with the code shown by the authenticator app. */
export async function twoFaVerify(
  token: string,
  code: string
): Promise<{ enabled: boolean }> {
  const response = await apiFetch(`${API_BASE_URL}/admin/2fa/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ code }),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || '2FA verification failed');
  }
  return response.json();
}

/** Disable 2FA. Requires the account's current password. */
export async function twoFaDisable(
  token: string,
  currentPassword: string
): Promise<{ enabled: boolean }> {
  const response = await apiFetch(`${API_BASE_URL}/admin/2fa/disable`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ current_password: currentPassword }),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to disable 2FA');
  }
  return response.json();
}

/** Revoke the HttpOnly refresh cookie server-side (best-effort). */
export async function logout(): Promise<void> {
  try {
    await apiFetch(`${API_BASE_URL}/auth/logout`, {
      method: 'POST',
      headers: { 'X-Asto-CSRF': '1' },
    });
  } catch {
    // The local session is cleared regardless; cookie revocation is best-effort.
  }
}

/** Revoke every refresh token for the current identity (uses Bearer auth). */
export async function logoutAll(token: string): Promise<{ revoked: boolean }> {
  const response = await apiFetch(`${API_BASE_URL}/auth/logout-all`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to revoke sessions');
  }
return response.json();
}

export async function verifyToken(
  token: string
): Promise<{ valid: boolean; user_id?: number; email?: string }> {
  const response = await apiFetch(`${API_BASE_URL}/auth/verify`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) {
    return { valid: false };
  }

  return response.json();
}

export interface FeedbackRequest {
  response_id: string;
  rating: 1 | -1;
  comment?: string;
}

export async function submitFeedback(
  request: FeedbackRequest,
  token?: string
): Promise<{ message: string; feedback_id: number }> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await apiFetch(`${API_BASE_URL}/feedback/`, {
    method: 'POST',
    headers,
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Feedback submission failed');
  }

   return response.json();
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export async function changePassword(
  request: ChangePasswordRequest,
  token?: string
): Promise<{ updated: boolean }> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await apiFetch(`${API_BASE_URL}/auth/change-password`, {
    method: 'POST',
    headers,
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Password change failed');
  }

  return response.json();
}

/**
 * Request a password-reset link for a staff or client email. The API
 * always returns the same generic success response (no account
 * enumeration), so no UI-side existence checks should be made either.
 */
export async function forgotPassword(email: string): Promise<{ ok: boolean }> {
  const response = await apiFetch(`${API_BASE_URL}/auth/forgot-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(error?.detail || 'Request failed');
  }

  return response.json();
}

/**
 * Set a new password with the one-time token from the emailed reset link.
 */
export async function resetPassword(
  token: string,
  newPassword: string
): Promise<{ ok: boolean }> {
  const response = await apiFetch(`${API_BASE_URL}/auth/reset-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, new_password: newPassword }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(error?.detail || 'Reset failed');
  }

  return response.json();
}

// ---------------------------------------------------------------------------
// Client (external) auth + portal
// ---------------------------------------------------------------------------

export interface ClientProfile {
  id: number;
  email: string;
  full_name: string | null;
  is_active: boolean;
  created_at: string | null;
  notification_prefs?: string[] | null;
}

export async function updateClientProfile(
  token: string,
  body: { full_name?: string; notification_prefs?: string[] }
): Promise<{ client: ClientProfile }> {
  const response = await apiFetch(`${API_BASE_URL}/client/me`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to update profile');
  }
  return response.json();
}

export interface ClientProperty {
  id: number;
  client_id: number;
  address: string;
  city: string;
  state: string;
  postal_code: string | null;
  property_type: string;
  is_active: boolean;
  created_at: string | null;
}

export interface ClientCase {
  id: number;
  case_number: string;
  client_id: number;
  property_id: number | null;
  loan_amount: number | null;
  status: string;
  is_active: boolean;
  created_at: string | null;
  property_address?: string | null;
  property_type?: string | null;
  latest_event?: {
    status: string;
    note: string | null;
    created_at: string | null;
  } | null;
}

export interface CaseEvent {
  id: number;
  case_id: number;
  status: string;
  note: string | null;
  created_at: string | null;
}

export interface CaseDetail {
  case: ClientCase;
  events: CaseEvent[];
}

export interface ClientDocument {
  id: number;
  title: string;
  source_path: string;
  doc_type: string;
  department: string;
  version: number;
  property_id: number | null;
  created_at: string | null;
  tags?: string[];
}

export async function getClientMe(token: string): Promise<{ client: ClientProfile }> {
  const response = await apiFetch(`${API_BASE_URL}/client/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load profile');
  }
  return response.json();
}

export async function getClientProperties(
  token: string
): Promise<{ properties: ClientProperty[] }> {
  const response = await apiFetch(`${API_BASE_URL}/client/properties`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load properties');
  }
  return response.json();
}

export async function getClientCases(
  token: string
): Promise<{ cases: ClientCase[] }> {
  const response = await apiFetch(`${API_BASE_URL}/client/cases`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load cases');
  }
  return response.json();
}

export async function getClientCaseDetail(
  token: string,
  caseId: number
): Promise<CaseDetail> {
  const response = await apiFetch(`${API_BASE_URL}/client/cases/${caseId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load case');
  }
  return response.json();
}

export interface ChecklistItem {
  item: string;
  satisfied: boolean;
}

export async function getClientCaseChecklist(
  token: string,
  caseId: number
): Promise<{ case_id: number; checklist: ChecklistItem[] }> {
  const response = await apiFetch(
    `${API_BASE_URL}/client/cases/${caseId}/checklist`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load checklist');
  }
  return response.json();
}

export async function getClientDocuments(
  token: string,
  tag?: string
): Promise<{ documents: ClientDocument[] }> {
  const query = tag ? `?tag=${encodeURIComponent(tag)}` : '';
  const response = await apiFetch(`${API_BASE_URL}/client/documents${query}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load documents');
  }
  return response.json();
}

export interface ClientRejectedDocument {
  id: number;
  title: string;
  source_path: string;
  doc_type: string;
  department: string;
  version: number;
  property_id: number | null;
  created_at: string | null;
  rejection_reason: string | null;
  rejected_at: string | null;
}

export interface RejectionEntry {
  id: number;
  reason: string | null;
  created_at: string | null;
  reviewed_by_email: string | null;
}

export async function getClientRejectedDocuments(
  token: string
): Promise<{ documents: ClientRejectedDocument[] }> {
  const response = await apiFetch(`${API_BASE_URL}/client/documents/rejected`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load rejected documents');
  }
  return response.json();
}

export async function getClientDocumentRejections(
  documentId: number,
  token: string
): Promise<{ document_id: number; rejections: RejectionEntry[] }> {
  const response = await apiFetch(
    `${API_BASE_URL}/client/documents/${documentId}/rejections`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load rejection history');
  }
  return response.json();
}

export async function getStaffDocumentRejections(
  documentId: number,
  token: string
): Promise<{ document_id: number; rejections: RejectionEntry[] }> {
  const response = await apiFetch(
    `${API_BASE_URL}/staff/documents/${documentId}/rejections`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load rejection history');
  }
  return response.json();
}

export async function getClientPropertyDocuments(
  propertyId: number,
  token: string
): Promise<{ documents: ClientDocument[] }> {
  const response = await apiFetch(
    `${API_BASE_URL}/client/properties/${propertyId}/documents`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load property documents');
  }
  return response.json();
}

// ---------------------------------------------------------------------------
// Client e-sign (K5)
// ---------------------------------------------------------------------------

export interface SignatureRequest {
  id: number;
  case_id: number;
  document_id: number | null;
  status: 'pending' | 'signed' | 'cancelled';
  signed_name: string | null;
  signed_at: string | null;
  created_at: string | null;
  document_title: string | null;
}

export async function getClientSignatureRequests(
  token: string
): Promise<{ signature_requests: SignatureRequest[] }> {
  const response = await apiFetch(`${API_BASE_URL}/client/signature-requests`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load signature requests');
  }
  return response.json();
}

export async function signClientSignatureRequest(
  token: string,
  requestId: number,
  signedName: string,
  consent: boolean
): Promise<{ message: string; document_id: number | null; signed_at: string }> {
  const response = await apiFetch(
    `${API_BASE_URL}/client/signature-requests/${requestId}/sign`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ signed_name: signedName, consent }),
    }
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to sign document');
  }
  return response.json();
}

export async function clientUploadDocument(
  file: File,
  token: string,
  docType: string,
  title: string,
  propertyId?: number | null
): Promise<{ message: string; filename: string; stored_as: string; size_bytes: number; property_id: number | null }> {
  const form = new FormData();
  form.append('file', file);
  form.append('doc_type', docType);
  form.append('title', title);
  const query = propertyId != null ? `?property_id=${propertyId}` : '';
  const response = await apiFetch(`${API_BASE_URL}/client/documents/upload${query}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Upload failed');
  }
  return response.json();
}

// ---------------------------------------------------------------------------
// Admin: approvals (Phase B3)
// ---------------------------------------------------------------------------

export interface ApprovalDocument {
  id: number;
  title: string;
  doc_type: string;
  department: string;
  client_id: number | null;
  approval_status: 'pending' | 'approved' | 'rejected';
  source_path: string;
  version: number;
  created_at: string | null;
  uploaded_by?: number | null;
  uploaded_by_email?: string | null;
  pii_flagged?: boolean;
  tags?: string[];
}

export interface ApprovalHistoryEntry {
  id: number;
  document_id: number;
  from_status: string;
  to_status: string;
  reason: string | null;
  created_at: string | null;
  reviewed_by_email: string | null;
}

export interface DocumentVersion {
  id: number;
  title: string;
  source_path: string | null;
  doc_type: string;
  department: string;
  client_id: number | null;
  property_id: number | null;
  approval_status: string;
  is_active: boolean;
  is_approved: boolean;
  version: number;
  created_at: string | null;
  uploaded_by: number | null;
  uploaded_by_email: string | null;
}

export async function listPendingDocuments(
  token: string
): Promise<{ documents: ApprovalDocument[] }> {
  const response = await apiFetch(`${API_BASE_URL}/admin/documents/pending`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load pending documents');
  }
  return response.json();
}

export async function approveDocument(
  documentId: number,
  token: string,
  publishAnyway = false
): Promise<{ message: string }> {
  const response = await apiFetch(
    `${API_BASE_URL}/admin/documents/${documentId}/approve`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ publish_anyway: publishAnyway }),
    }
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to approve document');
  }
  return response.json();
}

export async function bulkApproveDocuments(
  documentIds: number[],
  token: string,
  publishAnyway = false
): Promise<{ message: string }> {
  const response = await apiFetch(
    `${API_BASE_URL}/admin/documents/bulk-approve`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ document_ids: documentIds, publish_anyway: publishAnyway }),
    }
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to bulk approve documents');
  }
  return response.json();
}

export async function bulkRejectDocuments(
  documentIds: number[],
  token: string,
  reason: string
): Promise<{ message: string }> {
  const response = await apiFetch(
    `${API_BASE_URL}/admin/documents/bulk-reject`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ document_ids: documentIds, reason }),
    }
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to bulk reject documents');
  }
  return response.json();
}

export async function rejectDocument(
  documentId: number,
  token: string,
  reason?: string
): Promise<{ message: string; reason?: string }> {
  const response = await apiFetch(
    `${API_BASE_URL}/admin/documents/${documentId}/reject`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ reason: reason ?? '' }),
    }
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to reject document');
  }
  return response.json();
}

export async function getDocumentHistory(
  documentId: number,
  token: string
): Promise<{ document_id: number; history: ApprovalHistoryEntry[] }> {
  const response = await apiFetch(
    `${API_BASE_URL}/admin/documents/${documentId}/history`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load approval history');
  }
  return response.json();
}

export async function getDocumentVersions(
  documentId: number,
  token: string
): Promise<{ document_id: number; versions: DocumentVersion[] }> {
  const response = await apiFetch(
    `${API_BASE_URL}/admin/documents/${documentId}/versions`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load document versions');
  }
  return response.json();
}

export interface AdminTag {
  tag: string;
  count: number;
}

export async function updateDocumentTags(
  documentId: number,
  tags: string[],
  token: string
): Promise<{ document_id: number; tags: string[] }> {
  const response = await apiFetch(
    `${API_BASE_URL}/admin/documents/${documentId}/tags`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ tags }),
    }
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to update document tags');
  }
  return response.json();
}

export async function getAdminTags(token: string): Promise<{ tags: AdminTag[] }> {
  const response = await apiFetch(`${API_BASE_URL}/admin/tags`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load document tags');
  }
  return response.json();
}

// ---------------------------------------------------------------------------
// Admin: documents + upload (Phase A)
// ---------------------------------------------------------------------------

export interface AdminDocument {
  id: number;
  title: string;
  source_path: string;
  doc_type: string;
  department: string;
  client_id: number | null;
  approval_status: 'pending' | 'approved' | 'rejected';
  approved_by: number | null;
  approved_at: string | null;
  is_active: boolean;
  is_approved: boolean;
  version: number;
  created_at: string | null;
  tags?: string[];
}

export async function listAllDocuments(
  token: string,
  tag?: string
): Promise<{ documents: AdminDocument[] }> {
  const query = tag ? `?tag=${encodeURIComponent(tag)}` : '';
  const response = await apiFetch(`${API_BASE_URL}/documents/${query}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load documents');
  }
  return response.json();
}

export async function uploadDocument(
  file: File,
  token: string
): Promise<{ message: string; filename: string; stored_as: string; size_bytes: number }> {
  const form = new FormData();
  form.append('file', file);
  const response = await apiFetch(`${API_BASE_URL}/documents/upload`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Upload failed');
  }
  return response.json();
}

/** Fetch a document file as a blob (admin endpoint). */
export async function getDocumentFile(
  documentId: number,
  token: string,
  version?: number
): Promise<Blob> {
  const query = version != null ? `?version=${version}` : '';
  const response = await apiFetch(`${API_BASE_URL}/documents/${documentId}/file${query}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || 'Failed to load document file');
  }
  return response.blob();
}

/** Fetch a client's own approved document file as a blob. */
export async function getClientDocumentFile(
  documentId: number,
  token: string
): Promise<Blob> {
  const response = await apiFetch(
    `${API_BASE_URL}/client/documents/${documentId}/file`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || 'Failed to load document file');
  }
  return response.blob();
}

/** Open a blob in a new tab (best-effort view). */
export function openBlobInNewTab(blob: Blob, fallbackName = 'document') {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  a.download = fallbackName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Revoke after a delay so the download/new-tab has time to open.
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

// ---------------------------------------------------------------------------
// Staff portal: dashboard, cases, workflows, SOPs, access requests (§1B)
// ---------------------------------------------------------------------------

export interface StaffDashboardCase {
  id: number;
  case_number: string;
  client_id: number;
  loan_amount: number | null;
  status: string;
  created_at: string | null;
  client_name: string | null;
  address: string | null;
  city: string | null;
  state: string | null;
}

export interface StaffWorkflow {
  id: number;
  title: string;
  department: string;
  case_id: number | null;
  status: 'in_progress' | 'review' | 'done';
  assigned_to: number | null;
  created_at: string | null;
  updated_at: string | null;
  case_number?: string | null;
}

export interface StaffSop {
  id: number;
  title: string;
  department: string;
  body: string;
  version: number;
  created_by: number | null;
  updated_at: string | null;
  is_active: boolean;
}

export interface StaffDashboardResponse {
  cases: StaffDashboardCase[];
  workflows: StaffWorkflow[];
  sops: StaffSop[];
  sop_access: boolean;
  overdue_workflows: number;
  overdue_tasks: number;
}

export interface CaseNote {
  id: number;
  case_id: number;
  user_id: number;
  author_name?: string | null;
  body: string;
  created_at: string | null;
}

export interface SopAccessRequest {
  id: number;
  user_id: number;
  action: 'create' | 'edit';
  department: string;
  reason: string | null;
  status: 'pending' | 'approved' | 'rejected';
  reviewed_by: number | null;
  reviewed_at: string | null;
  created_at: string | null;
  requester_email?: string;
}

export async function getStaffDashboard(token: string): Promise<StaffDashboardResponse> {
  const response = await apiFetch(`${API_BASE_URL}/staff/dashboard`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load dashboard');
  }
  return response.json();
}

// ---------------------------------------------------------------------------
// Phase L — Staff & Operations
// ---------------------------------------------------------------------------

export interface StaffTask {
  id: number;
  case_id: number | null;
  title: string;
  description: string | null;
  assignee_id: number | null;
  due_at: string | null;
  status: string;
  created_by: number;
  created_at: string | null;
  updated_at: string | null;
  assignee_email?: string | null;
  case_number?: string | null;
}

export async function getStaffTasks(token: string): Promise<{ tasks: StaffTask[] }> {
  const response = await apiFetch(`${API_BASE_URL}/staff/tasks`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load tasks');
  }
  return response.json();
}

export async function createStaffTask(
  token: string,
  payload: {
    case_id?: number | null;
    title: string;
    description?: string | null;
    assignee_id?: number | null;
    due_at?: string | null;
  }
): Promise<{ task: StaffTask }> {
  const response = await apiFetch(`${API_BASE_URL}/staff/tasks`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to create task');
  }
  return response.json();
}

export async function updateStaffTask(
  token: string,
  taskId: number,
  payload: {
    title?: string;
    description?: string | null;
    assignee_id?: number | null;
    due_at?: string | null;
    status?: string;
  }
): Promise<{ task: StaffTask }> {
  const response = await apiFetch(`${API_BASE_URL}/staff/tasks/${taskId}`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to update task');
  }
  return response.json();
}

export interface Client360 {
  client: {
    id: number;
    email: string;
    full_name: string | null;
    is_active: boolean;
    created_at: string | null;
  };
  properties: {
    id: number;
    address: string | null;
    city: string | null;
    state: string | null;
    postal_code: string | null;
    property_type: string | null;
  }[];
  cases: {
    id: number;
    case_number: string;
    client_id: number;
    property_id: number | null;
    loan_amount: number | null;
    status: string;
    is_active: boolean;
    created_at: string | null;
    timeline: { case_id: number; status: string; note: string | null; created_at: string | null }[];
  }[];
  documents: {
    id: number;
    title: string;
    doc_type: string | null;
    department: string | null;
    version: number;
    approval_status: string;
    property_id: number | null;
    created_at: string | null;
  }[];
  conversations: {
    id: number;
    case_id: number | null;
    subject: string;
    created_at: string | null;
    updated_at: string | null;
  }[];
}

export async function getStaffClient360(
  token: string,
  clientId: number
): Promise<Client360> {
  const response = await apiFetch(`${API_BASE_URL}/staff/clients/${clientId}/360`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load client 360 view');
  }
  return response.json();
}

export interface WorkflowDefinition {
  id: number;
  name: string;
  description: string | null;
  stages: string[];
  transitions: Record<string, unknown>[];
  is_active: boolean;
  created_at: string | null;
}

export async function getWorkflowDefinitions(
  token: string
): Promise<{ workflow_definitions: WorkflowDefinition[] }> {
  const response = await apiFetch(`${API_BASE_URL}/staff/workflow-definitions`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load workflow definitions');
  }
  return response.json();
}

export async function createWorkflowDefinition(
  token: string,
  payload: {
    name: string;
    description?: string | null;
    stages: string[];
    transitions?: Record<string, unknown>[];
  }
): Promise<{ workflow_definition: WorkflowDefinition }> {
  const response = await apiFetch(`${API_BASE_URL}/staff/workflow-definitions`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to create workflow definition');
  }
  return response.json();
}

export async function deleteWorkflowDefinition(
  token: string,
  definitionId: number
): Promise<{ message: string }> {
  const response = await apiFetch(
    `${API_BASE_URL}/staff/workflow-definitions/${definitionId}`,
    {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    }
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to delete workflow definition');
  }
  return response.json();
}

export interface MessageTemplate {
  id: number;
  name: string;
  body: string;
  department: string;
  created_at: string | null;
  updated_at: string | null;
}

export async function getMessageTemplates(
  token: string
): Promise<{ message_templates: MessageTemplate[] }> {
  const response = await apiFetch(`${API_BASE_URL}/staff/message-templates`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load message templates');
  }
  return response.json();
}

export async function createMessageTemplate(
  token: string,
  payload: { name: string; body: string; department: string }
): Promise<{ message_template: MessageTemplate }> {
  const response = await apiFetch(`${API_BASE_URL}/staff/message-templates`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to create message template');
  }
  return response.json();
}

export async function deleteMessageTemplate(
  token: string,
  templateId: number
): Promise<{ message: string }> {
  const response = await apiFetch(
    `${API_BASE_URL}/staff/message-templates/${templateId}`,
    {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    }
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to delete message template');
  }
  return response.json();
}

export interface StaffAppointment {
  id: number;
  title: string;
  description: string | null;
  start_at: string | null;
  end_at: string | null;
  department: string;
  staff_id: number | null;
  status: string;
  created_at: string | null;
}

export async function getStaffAppointments(
  token: string
): Promise<{ appointments: StaffAppointment[] }> {
  const response = await apiFetch(`${API_BASE_URL}/staff/appointments`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load appointments');
  }
  return response.json();
}

export async function createStaffAppointment(
  token: string,
  payload: {
    title: string;
    description?: string | null;
    start_at: string;
    end_at: string;
    department: string;
    staff_id?: number | null;
  }
): Promise<{ appointment: StaffAppointment }> {
  const response = await apiFetch(`${API_BASE_URL}/staff/appointments`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to create appointment');
  }
  return response.json();
}

/** Fetch a document file as a blob (staff endpoint, assigned-client scoped). */
export async function getStaffDocumentFile(
  documentId: number,
  token: string
): Promise<Blob> {
  const response = await apiFetch(
    `${API_BASE_URL}/staff/documents/${documentId}/file`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || 'Failed to load document file');
  }
  return response.blob();
}

export async function getCaseNotes(token: string, caseId: number): Promise<{ notes: CaseNote[] }> {
  const response = await apiFetch(`${API_BASE_URL}/staff/cases/${caseId}/notes`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load notes');
  }
  return response.json();
}

export async function addCaseNote(
  token: string,
  caseId: number,
  body: string
): Promise<{ note: CaseNote }> {
  const response = await apiFetch(`${API_BASE_URL}/staff/cases/${caseId}/notes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ body }),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to add note');
  }
  return response.json();
}

export async function advanceWorkflow(
  token: string,
  workflowId: number
): Promise<{ workflow_id: number; status: string }> {
  const response = await apiFetch(`${API_BASE_URL}/staff/workflows/${workflowId}/advance`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to advance workflow');
  }
  return response.json();
}

export interface SopInput {
  title: string;
  department: string;
  body: string;
}

export async function createSop(
  token: string,
  input: SopInput
): Promise<{ message: string; sop_id: number }> {
  const response = await apiFetch(`${API_BASE_URL}/staff/sops`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to create SOP');
  }
  return response.json();
}

export async function updateSop(
  token: string,
  sopId: number,
  input: SopInput
): Promise<{ message: string; sop_id: number }> {
  const response = await apiFetch(`${API_BASE_URL}/staff/sops/${sopId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to update SOP');
  }
  return response.json();
}

export async function getMySopRequests(token: string): Promise<{ requests: SopAccessRequest[] }> {
  const response = await apiFetch(`${API_BASE_URL}/staff/sop-access-requests`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load access requests');
  }
  return response.json();
}

export async function createSopAccessRequest(
  token: string,
  input: { action: 'create' | 'edit'; department: string; reason?: string }
): Promise<{ id: number; status: string }> {
  const response = await apiFetch(`${API_BASE_URL}/staff/sop-access-requests`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to submit access request');
  }
  return response.json();
}

export async function listSopAccessRequests(
  token: string,
  statusFilter?: string
): Promise<{ requests: SopAccessRequest[] }> {
  const query = statusFilter ? `?status_filter=${statusFilter}` : '';
  const response = await apiFetch(`${API_BASE_URL}/admin/sop-access-requests${query}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load access requests');
  }
  return response.json();
}

export async function reviewSopAccessRequest(
  token: string,
  requestId: number,
  decision: 'approved' | 'rejected'
): Promise<{ message: string; request_id: number }> {
  const response = await apiFetch(`${API_BASE_URL}/admin/sop-access-requests/${requestId}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ decision }),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to review access request');
  }
  return response.json();
}

// ---------------------------------------------------------------------------
// Messaging (client <-> staff conversations, Phase F6)
// ---------------------------------------------------------------------------

export interface Conversation {
  id: number;
  case_id: number | null;
  client_id: number | null;
  subject: string;
  case_number?: string | null;
  client_name?: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface Message {
  id: number;
  conversation_id: number;
  sender_type: 'staff' | 'client';
  sender_user_id: number | null;
  sender_client_id: number | null;
  sender_name: string | null;
  body: string;
  created_at: string | null;
}

async function jsonOrThrow(response: Response, fallback: string) {
  if (!response.ok) {
    let detail = fallback;
    try {
      const body = await response.json();
      if (body && body.detail) detail = body.detail;
    } catch {
      // non-JSON error body
    }
    throw new Error(detail);
  }
  return response.json();
}

export async function getClientConversations(
  token: string
): Promise<{ conversations: Conversation[] }> {
  const response = await apiFetch(`${API_BASE_URL}/client/conversations`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return jsonOrThrow(response, 'Failed to load conversations');
}

export async function createClientConversation(
  token: string,
  input: { subject: string; case_id?: number | null }
): Promise<{ conversation: Conversation }> {
  const response = await apiFetch(`${API_BASE_URL}/client/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(input),
  });
  return jsonOrThrow(response, 'Failed to create conversation');
}

export async function getClientConversationMessages(
  token: string,
  conversationId: number
): Promise<{ messages: Message[] }> {
  const response = await apiFetch(
    `${API_BASE_URL}/client/conversations/${conversationId}/messages`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  return jsonOrThrow(response, 'Failed to load messages');
}

export async function sendClientMessage(
  token: string,
  conversationId: number,
  body: string
): Promise<{ message: Message }> {
  const response = await apiFetch(
    `${API_BASE_URL}/client/conversations/${conversationId}/messages`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ body }),
    }
  );
  return jsonOrThrow(response, 'Failed to send message');
}

export async function getStaffConversations(
  token: string
): Promise<{ conversations: Conversation[] }> {
  const response = await apiFetch(`${API_BASE_URL}/staff/conversations`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return jsonOrThrow(response, 'Failed to load conversations');
}

export async function createStaffConversation(
  token: string,
  input: { subject: string; client_id: number; case_id?: number | null }
): Promise<{ conversation: Conversation }> {
  const response = await apiFetch(`${API_BASE_URL}/staff/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(input),
  });
  return jsonOrThrow(response, 'Failed to create conversation');
}

export async function getStaffConversationMessages(
  token: string,
  conversationId: number
): Promise<{ messages: Message[] }> {
  const response = await apiFetch(
    `${API_BASE_URL}/staff/conversations/${conversationId}/messages`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  return jsonOrThrow(response, 'Failed to load messages');
}

export async function sendStaffMessage(
  token: string,
  conversationId: number,
  body: string
): Promise<{ message: Message }> {
  const response = await apiFetch(
    `${API_BASE_URL}/staff/conversations/${conversationId}/messages`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ body }),
    }
  );
  return jsonOrThrow(response, 'Failed to send message');
}

// ---------------------------------------------------------------------------
// Admin audit log (Phase F7)
// ---------------------------------------------------------------------------

export interface AuditEntry {
  id: number;
  user_id: number | null;
  actor: string | null;
  actor_email: string | null;
  query: string;
  sub_queries: string[] | null;
  retrieved_ids: number[] | null;
  confidence: number | null;
  response_id: string | null;
  outcome: string | null;
  latency_ms: number | null;
  created_at: string | null;
}

export interface AuditLogResponse {
  total: number;
  limit: number;
  offset: number;
  entries: AuditEntry[];
}

export interface AuditFilters {
  q?: string;
  actor?: string;
  outcome?: string;
  from?: string;
  to?: string;
  limit?: number;
  offset?: number;
}

export async function getAdminAudit(
  token: string,
  filters: AuditFilters = {}
): Promise<AuditLogResponse> {
  const params = new URLSearchParams();
  if (filters.q) params.set('q', filters.q);
  if (filters.actor) params.set('actor', filters.actor);
  if (filters.outcome) params.set('outcome', filters.outcome);
  if (filters.from) params.set('from', filters.from);
  if (filters.to) params.set('to', filters.to);
  if (filters.limit != null) params.set('limit', String(filters.limit));
  if (filters.offset != null) params.set('offset', String(filters.offset));
  const qs = params.toString() ? `?${params.toString()}` : '';
  const response = await apiFetch(`${API_BASE_URL}/admin/audit${qs}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return jsonOrThrow(response, 'Failed to load audit log');
}

/**
 * M1 — Stream the filtered audit log to a CSV download. Reuses the same
 * filters as getAdminAudit (q/actor/outcome/from/to) but exports every match.
 */
export async function exportAuditLogCsv(
  token: string,
  filters: Omit<AuditFilters, 'limit' | 'offset'> = {}
): Promise<void> {
  const params = new URLSearchParams();
  if (filters.q) params.set('q', filters.q);
  if (filters.actor) params.set('actor', filters.actor);
  if (filters.outcome) params.set('outcome', filters.outcome);
  if (filters.from) params.set('from', filters.from);
  if (filters.to) params.set('to', filters.to);
  params.set('format', 'csv');
  const qs = params.toString() ? `?${params.toString()}` : '';
  const response = await apiFetch(`${API_BASE_URL}/admin/audit/export${qs}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new Error('Failed to export audit log');
  }
  const blob = await response.blob();
  openBlobInNewTab(blob, `audit_log_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.csv`);
}

// ---------------------------------------------------------------------------
// Staff client onboarding (Session 9, decision #2 — manual today, CRM hook later)
// ---------------------------------------------------------------------------

export interface OnboardClientInput {
  email: string;
  password: string;
  full_name?: string;
  address?: string;
  city?: string;
  state?: string;
  postal_code?: string;
  property_type?: string;
  case_number?: string;
  loan_amount?: number;
  case_status?: string;
}

export interface OnboardClientResult {
  message: string;
  client_id: number;
  property_id: number | null;
  case_id: number | null;
  case_number: string | null;
}

export async function onboardClient(
  token: string,
  input: OnboardClientInput
): Promise<OnboardClientResult> {
  const response = await apiFetch(`${API_BASE_URL}/staff/clients`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(input),
  });
  return jsonOrThrow(response, 'Failed to onboard client');
}

// ---------------------------------------------------------------------------
// Admin: users, clients, assignments (Phase C3)
// ---------------------------------------------------------------------------

export interface AdminUser {
  id: number;
  email: string;
  full_name: string | null;
  role: string;
  department: string;
  allowed_departments: string[] | null;
  is_active: boolean;
  created_at: string | null;
}

export interface AdminClient {
  id: number;
  email: string;
  full_name: string | null;
  is_active: boolean;
  created_at: string | null;
}

export async function listUsers(token: string): Promise<{ users: AdminUser[] }> {
  const response = await apiFetch(`${API_BASE_URL}/admin/users`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load users');
  }
  return response.json();
}

export async function createUser(
  data: {
    email: string;
    password: string;
    full_name?: string | null;
    role?: string;
    department?: string;
    allowed_departments?: string[];
  },
  token: string
): Promise<{ message: string; user_id: number }> {
  const response = await apiFetch(`${API_BASE_URL}/admin/users`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to create user');
  }
  return response.json();
}

export async function listClients(
  token: string
): Promise<{ clients: AdminClient[] }> {
  const response = await apiFetch(`${API_BASE_URL}/admin/clients`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load clients');
  }
  return response.json();
}

export async function createClient(
  data: { email: string; password: string; full_name?: string | null },
  token: string
): Promise<{ message: string; client_id: number }> {
  const response = await apiFetch(`${API_BASE_URL}/admin/clients`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to create client');
  }
  return response.json();
}

export interface ActiveSession {
  id: number;
  audience: string;
  expires_at: string;
  created_at: string;
}

/** H5: list a staff user's active refresh sessions (admin). */
export async function listUserSessions(
  userId: number,
  token: string
): Promise<{ user_id: number; active_sessions: number; sessions: ActiveSession[] }> {
  const response = await apiFetch(`${API_BASE_URL}/admin/users/${userId}/sessions`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load sessions');
  }
  return response.json();
}

/** H5: kill every refresh session for a staff user (admin). */
export async function revokeUserSessions(
  userId: number,
  token: string
): Promise<{ user_id: number; revoked_sessions: number }> {
  const response = await apiFetch(`${API_BASE_URL}/admin/users/${userId}/sessions/revoke`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to revoke sessions');
  }
  return response.json();
}

/** H5: list an external client's active refresh sessions (admin). */
export async function listClientSessions(
  clientId: number,
  token: string
): Promise<{ client_id: number; active_sessions: number; sessions: ActiveSession[] }> {
  const response = await apiFetch(`${API_BASE_URL}/admin/clients/${clientId}/sessions`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load sessions');
  }
  return response.json();
}

/** H5: kill every refresh session for a client account (admin). */
export async function revokeClientSessions(
  clientId: number,
  token: string
): Promise<{ client_id: number; revoked_sessions: number }> {
  const response = await apiFetch(`${API_BASE_URL}/admin/clients/${clientId}/sessions/revoke`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to revoke sessions');
  }
  return response.json();
}

export async function assignStaffToClient(
  clientId: number,
  userId: number,
  token: string
): Promise<{ message: string }> {
  const response = await apiFetch(`${API_BASE_URL}/admin/assignments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ client_id: clientId, user_id: userId }),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to assign staff');
  }
  return response.json();
}

// ---------------------------------------------------------------------------
// Admin: analytics
// ---------------------------------------------------------------------------

export interface KnowledgeGap {
  id: number;
  query: string;
  intent: string | null;
  confidence: number | null;
  created_at: string | null;
}

export async function getKnowledgeGaps(
  token: string
): Promise<{ knowledge_gaps: KnowledgeGap[] }> {
  const response = await apiFetch(`${API_BASE_URL}/analytics/knowledge-gaps`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load knowledge gaps');
  }
  return response.json();
}

export interface AnalyticsSummary {
  total_gaps: number;
  by_intent: { intent: string; count: number }[];
  by_day: { date: string; count: number }[];
  low_confidence_count: number;
}

export async function getAnalyticsSummary(
  token: string
): Promise<{ summary: AnalyticsSummary }> {
  const response = await apiFetch(`${API_BASE_URL}/analytics/summary`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load analytics summary');
  }
  return response.json();
}

export interface DocumentPopularityEntry {
  doc_id: number;
  title: string;
  department: string;
  answer_count: number;
  no_answer_count: number;
  distinct_users: number;
  positive_count: number;
  negative_count: number;
  positive_ratio: number;
}

export interface DocumentPopularityResponse {
  top_documents: DocumentPopularityEntry[];
  underperforming_documents: DocumentPopularityEntry[];
}

export async function getDocumentPopularity(
  token: string,
  limit: number = 20
): Promise<DocumentPopularityResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/analytics/document-popularity?limit=${limit}`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load document popularity');
  }
  return response.json();
}

// ---------------------------------------------------------------------------
// Admin: dashboard summary (Phase F2)
// ---------------------------------------------------------------------------

export interface AdminSummary {
  pending_approvals: number;
  stale_pending_approvals: number;
  total_documents: number;
  total_users: number;
  total_clients: number;
  active_cases: number;
  total_gaps: number;
  pending_sop_requests: number;
}

export async function getAdminSummary(
  token: string
): Promise<AdminSummary> {
  const response = await apiFetch(`${API_BASE_URL}/admin/summary`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load admin summary');
  }
  return response.json();
}

// ---------------------------------------------------------------------------
// Health / system status (Phase M7)
// ---------------------------------------------------------------------------

export interface StorageHealth {
  writable: boolean;
  error?: string;
}

export interface SystemHealth {
  status: string;
  database: string;
  storage: { pending: StorageHealth; processed: StorageHealth };
  last_ingest: string | null;
  version: string;
  timestamp: number;
}

export async function getSystemHealth(token: string): Promise<SystemHealth> {
  const response = await apiFetch(`${API_BASE_URL}/health`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load system health');
  }
  return response.json();
}

// ---------------------------------------------------------------------------
// Feature flags (Phase M8)
// ---------------------------------------------------------------------------

export interface FeatureFlag {
  name: string;
  enabled: boolean;
  source: string;
}

export async function getFeatureFlags(token: string): Promise<FeatureFlag[]> {
  const response = await apiFetch(`${API_BASE_URL}/admin/flags`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load feature flags');
  }
  const data = await response.json();
  return data.flags as FeatureFlag[];
}

export async function setFeatureFlag(
  token: string,
  name: string,
  enabled: boolean
): Promise<{ name: string; enabled: boolean }> {
  const response = await apiFetch(`${API_BASE_URL}/admin/flags`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ name, enabled }),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to update feature flag');
  }
  return response.json();
}

// ---------------------------------------------------------------------------
// Admin: knowledge base browse, SOP management, governance (Phase F3)
// ---------------------------------------------------------------------------

export interface DocumentChunk {
  id: number;
  section: string | null;
  chunk_type: string;
  department: string;
  content: string;
  approval_status: string;
  is_approved: boolean;
  created_at: string | null;
}

export async function getDocumentChunks(
  documentId: number,
  token: string
): Promise<{ document_id: number; chunks: DocumentChunk[] }> {
  const response = await apiFetch(
    `${API_BASE_URL}/admin/documents/${documentId}/chunks`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load document chunks');
  }
  return response.json();
}

export interface Sop {
  id: number;
  title: string;
  department: string;
  body: string;
  version: number;
  created_by: number | null;
  updated_at: string | null;
  is_active: boolean;
}

export async function listAllSops(
  token: string
): Promise<{ sops: Sop[] }> {
  const response = await apiFetch(`${API_BASE_URL}/admin/sops`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load SOPs');
  }
  return response.json();
}

export interface GovernanceRole {
  name: string;
  label: string;
  description: string;
  access: string[] | string;
  capabilities: string[];
}

export interface GovernanceDepartment {
  name: string;
  label: string;
  description: string;
}

export interface GovernanceData {
  roles: GovernanceRole[];
  departments: GovernanceDepartment[];
  role_hierarchy: string[];
}

export async function getGovernance(
  token: string
): Promise<GovernanceData> {
  const response = await apiFetch(`${API_BASE_URL}/admin/governance`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load governance data');
  }
  return response.json();
}

export interface GovernanceUpdateInput {
  roles: GovernanceRole[];
  departments: GovernanceDepartment[];
  role_hierarchy: string[];
}

/** H7: write back the roles/departments config (admin + super_admin only). */
export async function updateGovernance(
  token: string,
  input: GovernanceUpdateInput
): Promise<GovernanceData> {
  const response = await apiFetch(`${API_BASE_URL}/admin/governance`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(input),
  });
  return jsonOrThrow(response, 'Failed to update governance');
}

// ---------------------------------------------------------------------------
// Phase G: staff clients view, staff upload, notifications, admin review edits
// ---------------------------------------------------------------------------

export interface StaffClientDocument {
  id: number;
  title: string;
  doc_type: string;
  department: string;
  source_path: string | null;
  client_id: number | null;
  property_id: number | null;
  uploaded_by: number | null;
  approval_status: 'pending' | 'approved' | 'rejected';
  is_approved: boolean;
  version: number;
  created_at: string | null;
  rejection_reason: string | null;
  rejected_at: string | null;
}

export interface StaffClientCase {
  id: number;
  case_number: string;
  client_id: number;
  property_id: number | null;
  loan_amount: number | null;
  status: string;
  is_active: boolean;
  created_at: string | null;
}

export interface StaffClientProperty {
  id: number;
  client_id: number;
  address: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
  property_type: string | null;
  is_active: boolean;
  created_at: string | null;
}

export interface StaffClient {
  id: number;
  email: string;
  full_name: string | null;
  is_active: boolean;
  created_at: string | null;
  properties: StaffClientProperty[];
  cases: StaffClientCase[];
  documents: StaffClientDocument[];
}

export async function getStaffClients(
  token: string
): Promise<{ clients: StaffClient[] }> {
  const response = await apiFetch(`${API_BASE_URL}/staff/clients`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load clients');
  }
  return response.json();
}

export async function staffUploadDocument(
  file: File,
  token: string,
  clientId: number,
  propertyId?: number | null
): Promise<{ message: string; filename: string; size_bytes: number; client_id: number; property_id: number | null }> {
  const form = new FormData();
  form.append('file', file);
  const query = `?client_id=${clientId}${propertyId != null ? `&property_id=${propertyId}` : ''}`;
  const response = await apiFetch(`${API_BASE_URL}/staff/documents/upload${query}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Upload failed');
  }
  return response.json();
}

export interface StaffNotification {
  id: number;
  user_id: number;
  type: string;
  title: string;
  body: string | null;
  link: string | null;
  is_read: boolean;
  created_at: string | null;
}

export interface NotificationsResponse {
  notifications: StaffNotification[];
  unread_count: number;
}

export async function getNotifications(
  token: string
): Promise<NotificationsResponse> {
  const response = await apiFetch(`${API_BASE_URL}/staff/notifications`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load notifications');
  }
  return response.json();
}

export async function markNotificationRead(
  notificationId: number,
  token: string
): Promise<{ message: string }> {
  const response = await apiFetch(
    `${API_BASE_URL}/staff/notifications/${notificationId}/read`,
    { method: 'POST', headers: { Authorization: `Bearer ${token}` } }
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to update notification');
  }
  return response.json();
}

export async function markAllNotificationsRead(
  token: string
): Promise<{ message: string }> {
  const response = await apiFetch(`${API_BASE_URL}/staff/notifications/read-all`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to update notifications');
  }
  return response.json();
}

export interface NotificationStreamHandlers {
  /** Current unread count + server max id, sent once on connect. */
  onHello?: (unreadCount: number, latestId: number) => void;
  /** A new (or previously unseen) notification arrived. */
  onNotification?: (notification: StaffNotification) => void;
  /** The stream dropped (network/proxy). Reconnect as desired. */
  onClose?: (err?: unknown) => void;
}

/**
 * Live notification stream over SSE (Phase N6). Returns an abort function.
 * The stream resumes from `sinceId` (the highest notification id already
 * rendered) so reconnects never duplicate or skip rows.
 */
export function openNotificationStream(
  token: string,
  handlers: NotificationStreamHandlers,
  sinceId = 0
): () => void {
  const controller = new AbortController();
  const headers: Record<string, string> = {
    Accept: 'text/event-stream',
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const connect = () => {
    fetch(`${API_BASE_URL}/staff/notifications/stream?since_id=${sinceId}`, {
      headers,
      signal: controller.signal,
      cache: 'no-store',
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Notification stream failed (${response.status})`);
        }
        if (!response.body) {
          throw new Error('Streaming not supported by this browser');
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        const handleEvent = (event: string, data: string) => {
          if (event === 'hello') {
            const parsed = JSON.parse(data) as {
              unread_count?: number;
              latest_id?: number;
            };
            if (typeof parsed.unread_count === 'number') {
              handlers.onHello?.(parsed.unread_count, parsed.latest_id ?? 0);
            }
          } else if (event === 'notification') {
            const notification = JSON.parse(data) as StaffNotification;
            sinceId = Math.max(sinceId, notification.id);
            handlers.onNotification?.(notification);
          }
        };

        const pump = () => {
          reader.read().then(
            ({ done, value }) => {
              if (done) {
                handlers.onClose?.();
                return;
              }
              buffer += decoder.decode(value, { stream: true });
              const frames = buffer.split('\n\n');
              buffer = frames.pop() ?? '';
              for (const frame of frames) {
                let event = 'message';
                const dataLines: string[] = [];
                for (const line of frame.split('\n')) {
                  if (line.startsWith('event:')) {
                    event = line.slice(6).trim();
                  } else if (line.startsWith('data:')) {
                    dataLines.push(line.slice(5).trim());
                  }
                }
                if (dataLines.length > 0) {
                  handleEvent(event, dataLines.join('\n'));
                }
              }
              pump();
            },
            (err) => {
              if (err?.name === 'AbortError') return;
              handlers.onClose?.(err);
            }
          );
        };

        pump();
      })
      .catch((err) => {
        if (err?.name === 'AbortError') return;
        handlers.onClose?.(err);
      });
  };

  connect();
  return () => controller.abort();
}

export async function updateDocumentMetadata(
  documentId: number,
  updates: { title?: string; doc_type?: string; department?: string },
  token: string
): Promise<{ message: string; updated: string[] }> {
  const response = await apiFetch(`${API_BASE_URL}/admin/documents/${documentId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(updates),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to update document');
  }
  return response.json();
}
