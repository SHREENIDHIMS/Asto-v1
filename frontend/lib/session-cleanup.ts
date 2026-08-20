// Clears every query-derived piece of local state when a session ends.
// Chat transcripts (asto_chat_history, asto_chat_sessions:*) and past-query
// suggestions (asto_smart_suggestions) can contain personal information, so
// they must never survive logout. Keys are the same ones the chat history /
// session hooks persist under.

import { HISTORY_KEY } from "@/hooks/use-chat-history";
import { SESSIONS_PREFIX } from "@/hooks/use-chat-sessions";

const SUGGESTIONS_KEY = "asto_smart_suggestions";

/**
 * Remove all chat history, client chat sessions, and query-suggestion data
 * from localStorage. Safe to call on every logout path (normal, all-devices,
 * and idle-timeout); unrelated stored keys are left untouched.
 */
export function clearClientLocalState(): void {
  try {
    localStorage.removeItem(HISTORY_KEY);
    localStorage.removeItem(SUGGESTIONS_KEY);
    const sessionKeys: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith(SESSIONS_PREFIX)) sessionKeys.push(key);
    }
    for (const key of sessionKeys) localStorage.removeItem(key);
  } catch {
    // localStorage may be unavailable (SSR / private browsing) — nothing to clear.
  }
}