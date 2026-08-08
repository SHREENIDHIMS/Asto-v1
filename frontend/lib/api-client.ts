// API client — calls FastAPI directly, no BFF proxy.
// JWT is stored client-side and sent per-request.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8011/api/v1';

export interface SearchRequest {
  query: string;
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
  excerpts: SearchExcerpt[];
  summary: SearchSummarySentence[];
  confidence: number;
  routing: 'answer' | 'partial' | 'no_answer';
  related_questions: string[];
}

export interface AuthLoginRequest {
  email: string;
  password: string;
}

export interface AuthLoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export async function searchKnowledgeBase(
  query: string,
  token?: string
): Promise<SearchResponse> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE_URL}/search/`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ query }),
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

/**
 * Streaming-lite search: reads the SSE stream from /search/stream,
 * invoking onStage for each progress event and resolving with the final
 * SearchResponse from the result event.
 */
export async function searchKnowledgeBaseStream(
  query: string,
  token: string | undefined,
  onStage?: (stage: SearchStage) => void
): Promise<SearchResponse> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE_URL}/search/stream`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ query }),
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
        if (parsed.stage && onStage) {
          onStage(parsed.stage);
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
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
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

export async function verifyToken(
  token: string
): Promise<{ valid: boolean; user_id?: number; email?: string }> {
  const response = await fetch(`${API_BASE_URL}/auth/verify`, {
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

  const response = await fetch(`${API_BASE_URL}/feedback/`, {
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

// ---------------------------------------------------------------------------
// Client (external) auth + portal
// ---------------------------------------------------------------------------

export async function clientLogin(
  email: string,
  password: string
): Promise<AuthLoginResponse> {
  const response = await fetch(`${API_BASE_URL}/auth/client-login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Client login failed');
  }

  return response.json();
}

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
}

export interface ClientDocument {
  id: number;
  title: string;
  source_path: string;
  doc_type: string;
  department: string;
  version: number;
  created_at: string | null;
}

export async function getClientMe(token: string): Promise<{ client: ClientProfile }> {
  const response = await fetch(`${API_BASE_URL}/client/me`, {
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
  const response = await fetch(`${API_BASE_URL}/client/properties`, {
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
  const response = await fetch(`${API_BASE_URL}/client/cases`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load cases');
  }
  return response.json();
}

export async function getClientDocuments(
  token: string
): Promise<{ documents: ClientDocument[] }> {
  const response = await fetch(`${API_BASE_URL}/client/documents`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load documents');
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
  const response = await fetch(`${API_BASE_URL}/admin/documents/pending`, {
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
  const response = await fetch(
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
  token: string
): Promise<{ message: string }> {
  const response = await fetch(
    `${API_BASE_URL}/admin/documents/${documentId}/reject`,
    { method: 'POST', headers: { Authorization: `Bearer ${token}` } }
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
  const response = await fetch(
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
  const response = await fetch(`${API_BASE_URL}/documents/`, {
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
  const response = await fetch(`${API_BASE_URL}/documents/upload`, {
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
  const response = await fetch(`${API_BASE_URL}/documents/${documentId}/file`, {
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
  const response = await fetch(
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
  const response = await fetch(`${API_BASE_URL}/admin/users`, {
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
  const response = await fetch(`${API_BASE_URL}/admin/users`, {
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
  const response = await fetch(`${API_BASE_URL}/admin/clients`, {
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
  const response = await fetch(`${API_BASE_URL}/admin/clients`, {
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

export async function assignStaffToClient(
  clientId: number,
  userId: number,
  token: string
): Promise<{ message: string }> {
  const response = await fetch(`${API_BASE_URL}/admin/assignments`, {
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
  const response = await fetch(`${API_BASE_URL}/analytics/knowledge-gaps`, {
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
  const response = await fetch(`${API_BASE_URL}/analytics/summary`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to load analytics summary');
  }
  return response.json();
}
