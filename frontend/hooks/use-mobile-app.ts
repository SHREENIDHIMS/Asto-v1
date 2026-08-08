"use client";

import { useCallback, useEffect, useState } from "react";
import { detectPlatform } from "./use-platform";

export interface MobileBridgeRequest<T = unknown> {
  type: string;
  payload?: T;
}

export interface MobileBridgeResponse<T = unknown> {
  ok: boolean;
  data?: T;
  error?: string;
}

interface MobileBridgeApi {
  postMessage?: (message: MobileBridgeRequest) => void;
}

declare global {
  interface Window {
    ReactNativeWebView?: MobileBridgeApi;
    webkit?: {
      messageHandlers?: Record<string, { postMessage: (message: string) => void }>;
    };
  }
}

const MOBILE_API_BASE = process.env.NEXT_PUBLIC_MOBILE_API_URL || "";

export function useMobileApp() {
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    setIsMobile(detectPlatform() === "mobile_app");
  }, []);

  const sendToBridge = useCallback(
    (message: MobileBridgeRequest) => {
      if (window.ReactNativeWebView?.postMessage) {
        window.ReactNativeWebView.postMessage(message);
      } else if (window.webkit?.messageHandlers?.asto) {
        window.webkit.messageHandlers.asto.postMessage(JSON.stringify(message));
      }
    },
    []
  );

  const search = useCallback(
    async (query: string): Promise<MobileBridgeResponse> => {
      const apiBase = MOBILE_API_BASE;
      if (apiBase) {
        const response = await fetch(`${apiBase}/search/`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query }),
        });
        if (!response.ok) {
          throw new Error((await response.json()).detail || "Search failed");
        }
        return { ok: true, data: await response.json() };
      }

      sendToBridge({ type: "ASTO_SEARCH", payload: { query } });
      return { ok: true };
    },
    [sendToBridge]
  );

  return { isMobile, search, sendToBridge };
}
