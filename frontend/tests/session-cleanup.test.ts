// Unit tests for session cleanup on logout (privacy hardening).
// Chat transcripts and past-query suggestions must never survive logout;
// unrelated localStorage keys must be left untouched.

import { beforeEach, describe, expect, it } from 'vitest';

import { clearClientLocalState } from '@/lib/session-cleanup';

interface FakeStorage {
  length: number;
  key: (index: number) => string | null;
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
  removeItem: (key: string) => void;
  clear: () => void;
}

function makeFakeStorage(seed: Record<string, string>): FakeStorage {
  const store = new Map(Object.entries(seed));
  return {
    get length() {
      return store.size;
    },
    key: (i: number) => Array.from(store.keys())[i] ?? null,
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => {
      store.set(k, v);
    },
    removeItem: (k: string) => {
      store.delete(k);
    },
    clear: () => {
      store.clear();
    },
  };
}

beforeEach(() => {
  (globalThis as unknown as { localStorage: FakeStorage }).localStorage =
    makeFakeStorage({});
});

describe('clearClientLocalState', () => {
  it('removes chat history, suggestions, and every chat session scope', () => {
    const storage = makeFakeStorage({
      asto_chat_history: '[{"query":"what is apr?"}]',
      asto_smart_suggestions: '["apr","ltv"]',
      'asto_chat_sessions:client:7': '[{"id":"s1"}]',
      'asto_chat_sessions:staff:1': '[{"id":"s2"}]',
      asto_theme: 'dark',
    });
    (globalThis as unknown as { localStorage: FakeStorage }).localStorage = storage;

    clearClientLocalState();

    expect(storage.getItem('asto_chat_history')).toBeNull();
    expect(storage.getItem('asto_smart_suggestions')).toBeNull();
    expect(storage.getItem('asto_chat_sessions:client:7')).toBeNull();
    expect(storage.getItem('asto_chat_sessions:staff:1')).toBeNull();
    expect(storage.getItem('asto_theme')).toBe('dark');
  });

  it('leaves unrelated keys untouched', () => {
    const storage = makeFakeStorage({
      asto_theme: 'dark',
      asto_session_timeout: '1800000',
      asto_admin_settings: '{}',
    });
    (globalThis as unknown as { localStorage: FakeStorage }).localStorage = storage;

    clearClientLocalState();

    expect(storage.getItem('asto_theme')).toBe('dark');
    expect(storage.getItem('asto_session_timeout')).toBe('1800000');
    expect(storage.getItem('asto_admin_settings')).toBe('{}');
  });

  it('is a no-op on empty storage', () => {
    expect(() => clearClientLocalState()).not.toThrow();
  });
});