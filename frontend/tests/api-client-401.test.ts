// Unit tests for the apiFetch 401 -> refresh -> retry behaviour.
// An authenticated request that hits a 401 (expired 8h access JWT) is
// transparently retried once with a fresh token obtained from the HttpOnly
// refresh cookie; unauthenticated requests and non-401 responses never
// trigger a refresh.

import { afterEach, describe, expect, it, vi } from 'vitest';

import { listSavedSearches } from '@/lib/api-client';

type FetchCall = { url: string; init?: RequestInit };

let calls: FetchCall[] = [];
let sequence: Array<() => Response> = [];

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function installFetch() {
  calls = [];
  sequence = [];
  vi.stubGlobal(
    'fetch',
    vi.fn((url: unknown, init?: RequestInit) => {
      calls.push({ url: String(url), init });
      const next = sequence.shift();
      if (!next) throw new Error('no fetch response queued');
      return Promise.resolve(next());
    })
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('apiFetch 401 handling', () => {
  it('refreshes once and retries an authenticated request with the new token', async () => {
    installFetch();
    sequence = [
      () => jsonResponse({ detail: 'Token expired' }, 401),
      () => jsonResponse({ access_token: 'fresh-token' }),
      () => jsonResponse({ saved_searches: [{ id: 1, query: 'apr' }] }),
    ];

    const result = await listSavedSearches('stale-token');

    expect(result).toEqual([{ id: 1, query: 'apr' }]);
    expect(calls).toHaveLength(3);
    expect(calls[1].url).toContain('/auth/refresh');
    const retriedHeaders = new Headers(calls[2].init?.headers);
    expect(retriedHeaders.get('Authorization')).toBe('Bearer fresh-token');
  });

  it('surfaces the 401 when the refresh itself fails', async () => {
    installFetch();
    sequence = [
      () => jsonResponse({ detail: 'Token expired' }, 401),
      () => jsonResponse({ detail: 'No session' }, 401),
    ];

    await expect(listSavedSearches('stale-token')).rejects.toThrow(
      'Token expired'
    );
    expect(calls).toHaveLength(2);
  });

  it('does not attempt a refresh on a non-401 response', async () => {
    installFetch();
    sequence = [() => jsonResponse({ saved_searches: [] })];

    await listSavedSearches('token');

    expect(calls).toHaveLength(1);
    expect(calls[0].url).not.toContain('/auth/refresh');
  });

  it('does not attempt a refresh on a 401 without an Authorization header', async () => {
    installFetch();
    sequence = [() => jsonResponse({ detail: 'Bad credentials' }, 401)];

    await expect(
      (await import('@/lib/api-client')).login('a@b.c', 'wrong')
    ).rejects.toThrow('Bad credentials');

    expect(calls).toHaveLength(1);
    expect(calls[0].url).not.toContain('/auth/refresh');
  });
});