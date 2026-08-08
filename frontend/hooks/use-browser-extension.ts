"use client";

import { useCallback } from "react";
import { detectPlatform } from "./use-platform";

interface ChromeRuntime {
  sendMessage: (message: unknown) => Promise<unknown>;
  id: string;
}

declare global {
  var chrome: { runtime: ChromeRuntime };
}

export interface ExtensionRequest<T = unknown> {
  type: string;
  payload?: T;
}

export interface ExtensionResponse<T = unknown> {
  ok: boolean;
  data?: T;
  error?: string;
}

const EXTENSION_API_BASE = process.env.NEXT_PUBLIC_EXTENSION_API_URL || "";

export function useBrowserExtension() {
  const sendMessage = useCallback(
    async <TResponse = unknown>(
      message: ExtensionRequest
    ): Promise<ExtensionResponse<TResponse> | null> => {
      if (detectPlatform() !== "browser_extension") return null;

      try {
        const response = await chrome.runtime.sendMessage(message);
        return response as ExtensionResponse<TResponse>;
      } catch {
        return { ok: false, error: "Extension runtime unavailable" };
      }
    },
    []
  );

  const search = useCallback(
    async (query: string) => {
      const apiBase = EXTENSION_API_BASE;
      if (apiBase) {
        const response = await fetch(`${apiBase}/search/`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query }),
        });
        if (!response.ok) {
          throw new Error((await response.json()).detail || "Search failed");
        }
        return response.json();
      }

      return sendMessage({ type: "ASTO_SEARCH", payload: { query } });
    },
    [sendMessage]
  );

  return { sendMessage, search };
}
