// Client-side auth management (Phase H1)
// The access JWT is kept in JS memory only — never in localStorage, so an
// XSS payload cannot steal a persistent credential. Long-lived sessions are
// carried by the HttpOnly asto_refresh cookie (set/revoked by the backend);
// restoreSession() exchanges it for a fresh access JWT on page load and
// after any reload.

import { refreshSession, verifyToken } from './api-client';

const ADMIN_ROLES = ["super_admin", "admin"];

/** True for any role with admin-level access (mirrors backend rbac.ADMIN_ROLES). */
export function isAdminRole(role: string | null | undefined): boolean {
  return !!role && ADMIN_ROLES.includes(role);
}

/** True for any staff-audience role (mirrors backend rbac hierarchy). */
export function isStaffRole(role: string | null | undefined): boolean {
  return !!role && role !== "client";
}

export interface UserSession {
  token: string;
  userId: number;
  email: string;
}

export interface TokenClaims {
  sub: string;
  name?: string;
  role: string;
  department: string;
  allowed_departments: string[];
  audience: 'staff' | 'client';
  client_id?: number;
  iat: number;
  exp: number;
}

// In-memory access token. Starts null and is populated by storeToken()
// (right after login) or restoreSession() (on page load via the cookie).
let memoryToken: string | null = null;

export function decodeToken(token: string): TokenClaims | null {
  try {
    const payload = JSON.parse(atob(token.split('.')[1])) as TokenClaims;
    return payload;
  } catch {
    return null;
  }
}

/** Store the access JWT in memory (login success). Not persisted anywhere. */
export function storeToken(token: string, remember: boolean = true): void {
  memoryToken = token;
}

/** The in-memory access token, or null when not restored yet. */
export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return memoryToken;
}

/** Forget the in-memory token. Does NOT clear the server cookie — call
 *  logout() from api-client for that. */
export function clearToken(): void {
  memoryToken = null;
}

/**
 * Restore the session: reuse the in-memory token, else exchange the
 * HttpOnly refresh cookie for a fresh access JWT. Returns the token or null
 * when no (valid) session exists. Call from every page gate before reading
 * getToken() after a hard navigation.
 */
export async function restoreSession(): Promise<string | null> {
  if (memoryToken) return memoryToken;
  try {
    const result = await refreshSession();
    memoryToken = result.access_token;
    return memoryToken;
  } catch {
    return null;
  }
}

/** Resolve the current session, restoring it from the cookie if needed. */
export async function getSession(): Promise<UserSession | null> {
  const token = await restoreSession();
  if (!token) return null;

  try {
    const result = await verifyToken(token);
    if (!result.valid) {
      clearToken();
      return null;
    }
    return {
      token,
      userId: result.user_id ?? 0,
      email: result.email ?? '',
    };
  } catch {
    clearToken();
    return null;
  }
}

export function isTokenExpired(token: string): boolean {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    const exp = payload.exp;
    if (!exp) return false;
    return Date.now() >= exp * 1000 - 60000; // 1 min buffer
  } catch {
    return true;
  }
}