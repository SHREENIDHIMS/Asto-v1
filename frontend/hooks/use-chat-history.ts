"use client";

import { useCallback, useEffect, useState } from "react";
import { SearchResponse } from "@/lib/api-client";

export interface ChatTurn {
  id: string;
  query: string;
  response: SearchResponse;
  timestamp: number;
}

const HISTORY_KEY = "asto_chat_history";
const TTL_MS = 24 * 60 * 60 * 1000; // 24 hours

function loadHistory(): ChatTurn[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ChatTurn[];
    const cutoff = Date.now() - TTL_MS;
    // Drop anything older than 24h.
    return parsed.filter((turn) => turn.timestamp >= cutoff);
  } catch {
    return [];
  }
}

function persistHistory(turns: ChatTurn[]): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(turns));
  } catch {
    // Storage full or unavailable — degrade to session-only chat.
  }
}

export function useChatHistory() {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setTurns(loadHistory());
    setLoaded(true);
  }, []);

  const appendTurn = useCallback((query: string, response: SearchResponse) => {
    setTurns((prev) => {
      const next = [
        ...prev,
        { id: crypto.randomUUID(), query, response, timestamp: Date.now() },
      ];
      persistHistory(next);
      return next;
    });
  }, []);

  const clearHistory = useCallback(() => {
    setTurns([]);
    persistHistory([]);
  }, []);

  const removeTurn = useCallback((id: string) => {
    setTurns((prev) => {
      const next = prev.filter((turn) => turn.id !== id);
      persistHistory(next);
      return next;
    });
  }, []);

  return { turns, loaded, appendTurn, clearHistory, removeTurn };
}
