"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { SearchResponse } from "@/lib/api-client";

export interface ChatTurn {
  id: string;
  query: string;
  response: SearchResponse;
  timestamp: number;
  urgency?: boolean;
}

export interface ChatSession {
  id: string;
  title: string;
  turns: ChatTurn[];
  createdAt: number;
  updatedAt: number;
}

const TTL_MS = 24 * 60 * 60 * 1000; // 24 hours

function storageKey(scope: string): string {
  return `asto_chat_sessions:${scope}`;
}

function loadSessions(scope: string): ChatSession[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(storageKey(scope));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ChatSession[];
    const cutoff = Date.now() - TTL_MS;
    // Drop sessions with no activity in the last 24h.
    return parsed
      .filter((s) => s.updatedAt >= cutoff)
      .sort((a, b) => b.updatedAt - a.updatedAt);
  } catch {
    return [];
  }
}

function persistSessions(scope: string, sessions: ChatSession[]): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(storageKey(scope), JSON.stringify(sessions));
  } catch {
    // Storage full or unavailable — degrade to session-only chat.
  }
}

function defaultTitle(query: string): string {
  const cleaned = query.replace(/\s+/g, " ").trim();
  return cleaned.length > 48 ? `${cleaned.slice(0, 48)}…` : cleaned || "New chat";
}

export function useChatSessions(scope: string) {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  // Ref keeps the latest sessions available to callbacks without
  // stale-closure issues (e.g. create-then-append in the same tick).
  const sessionsRef = useRef<ChatSession[]>([]);
  useEffect(() => {
    sessionsRef.current = sessions;
  }, [sessions]);

  useEffect(() => {
    const initial = loadSessions(scope);
    setSessions(initial);
    sessionsRef.current = initial;
    setLoaded(true);
  }, [scope]);

  const update = useCallback(
    (updater: (prev: ChatSession[]) => ChatSession[]) => {
      setSessions((prev) => {
        const next = updater(prev);
        sessionsRef.current = next;
        persistSessions(scope, next);
        return next;
      });
    },
    [scope]
  );

  const createSession = useCallback((): string => {
    const id = crypto.randomUUID();
    const now = Date.now();
    const session: ChatSession = {
      id,
      title: "New chat",
      turns: [],
      createdAt: now,
      updatedAt: now,
    };
    update((prev) => [session, ...prev]);
    setActiveId(id);
    return id;
  }, [update]);

  const activateSession = useCallback((id: string) => {
    setActiveId(id);
  }, []);

  const renameSession = useCallback(
    (id: string, title: string) => {
      update((prev) =>
        prev.map((s) =>
          s.id === id
            ? { ...s, title: title || defaultTitle(s.turns[0]?.query ?? "New chat") }
            : s
        )
      );
    },
    [update]
  );

  const appendTurn = useCallback(
    (sessionId: string, query: string, response: SearchResponse, urgency: boolean = false) => {
      const now = Date.now();
      update((prev) =>
        prev.map((s) => {
          if (s.id !== sessionId) return s;
          const title =
            s.turns.length === 0 && s.title === "New chat"
              ? defaultTitle(query)
              : s.title;
          return {
            ...s,
            title,
            turns: [
              ...s.turns,
              { id: crypto.randomUUID(), query, response, timestamp: now, urgency },
            ],
            updatedAt: now,
          };
        })
      );
    },
    [update]
  );

  const removeTurn = useCallback(
    (sessionId: string, turnId: string) => {
      update((prev) =>
        prev.map((s) =>
          s.id === sessionId
            ? { ...s, turns: s.turns.filter((t) => t.id !== turnId), updatedAt: Date.now() }
            : s
        )
      );
    },
    [update]
  );

  const replaceTurnResponse = useCallback(
    (sessionId: string, turnId: string, response: SearchResponse) => {
      update((prev) =>
        prev.map((s) =>
          s.id === sessionId
            ? {
                ...s,
                turns: s.turns.map((t) =>
                  t.id === turnId ? { ...t, response } : t
                ),
                updatedAt: Date.now(),
              }
            : s
        )
      );
    },
    [update]
  );

  const deleteSession = useCallback(
    (id: string) => {
      update((prev) => prev.filter((s) => s.id !== id));
      setActiveId((current) => (current === id ? null : current));
    },
    [update]
  );

  const clearAllSessions = useCallback(() => {
    update(() => []);
    setActiveId(null);
  }, [update]);

  const activeSession = sessions.find((s) => s.id === activeId) ?? null;

  return {
    sessions,
    activeId,
    activeSession,
    loaded,
    createSession,
    activateSession,
    renameSession,
    appendTurn,
    removeTurn,
    replaceTurnResponse,
    deleteSession,
    clearAllSessions,
  };
}
