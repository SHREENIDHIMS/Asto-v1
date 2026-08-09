// Client-side JWT auth management
// No server-side sessions — token lives in browser localStorage.

import { verifyToken } from './api-client';

export interface UserSession {
  token: string;
  userId: number;
  email: string;
}

export interface TokenClaims {
  sub: string;
  role: string;
  department: string;
  allowed_departments: string[];
  audience: 'staff' | 'client';
  client_id?: number;
  iat: number;
  exp: number;
}

const TOKEN_KEY = 'asto_auth_token';

export function decodeToken(token: string): TokenClaims | null {
  try {
    const payload = JSON.parse(atob(token.split('.')[1])) as TokenClaims;
    return payload;
  } catch {
    return null;
  }
}

export function storeToken(token: string, remember: boolean = true): void {
  if (typeof window === 'undefined') return;
  if (remember) {
    localStorage.setItem(TOKEN_KEY, token);
    sessionStorage.removeItem(TOKEN_KEY);
  } else {
    sessionStorage.setItem(TOKEN_KEY, token);
    localStorage.removeItem(TOKEN_KEY);
  }
}

export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY) ?? sessionStorage.getItem(TOKEN_KEY);
}

export function clearToken(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(TOKEN_KEY);
}

export async function getSession(): Promise<UserSession | null> {
  const token = getToken();
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
