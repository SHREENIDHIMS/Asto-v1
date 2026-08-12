// API client — calls FastAPI directly, no BFF proxy.
// Access JWT is held in memory (lib/auth) and sent per-request as Bearer.
// Every request also sends `credentials: 'include'` so the HttpOnly
// asto_refresh cookie flows (Phase H1) and Set-Cookie is accepted.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8011/api/v1';

/** fetch wrapper that always sends cookies for the refresh session. */
function apiFetch(url: string, init?: RequestInit): Promise<Response> {
  return fetch(url, { ...init, credentials: 'include' });
}

export interface SearchRequest {
  query: string;
  case_id?: number | null;
}

export interface SearchExcerpt {
  text: string;
  source: {
    title: string;
    section: string | null;
    chunk_type: string;
  };
  confidence: number;
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
  caseId?: number | null
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
    body: JSON.stringify({ query, case_id: caseId ?? null }),
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
  caseId?: number | null
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
    body: JSON.stringify({ query, case_id: caseId ?? null }),
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

export async function getClientDocuments(
  token: string
): Promise<{ documents: ClientDocument[] }> {
  const response = await apiFetch(`${API_BASE_URL}/client/documents`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load documents');
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

export async function clientUploadDocument(
  file: File,
  token: string,
  propertyId?: number | null
): Promise<{ message: string; filename: string; stored_as: string; size_bytes: number; property_id: number | null }> {
  const form = new FormData();
  form.append('file', file);
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
  token: string
): Promise<{ message: string }> {
  const response = await apiFetch(
    `${API_BASE_URL}/admin/documents/${documentId}/approve`,
    { method: 'POST', headers: { Authorization: `Bearer ${token}` } }
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to approve document');
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
}

export async function listAllDocuments(
  token: string
): Promise<{ documents: AdminDocument[] }> {
  const response = await apiFetch(`${API_BASE_URL}/documents/`, {
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
  token: string
): Promise<Blob> {
  const response = await apiFetch(`${API_BASE_URL}/documents/${documentId}/file`, {
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
