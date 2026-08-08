"use client";

export type Platform =
  | "web"
  | "browser_extension"
  | "mobile_app"
  | "unknown";

export function detectPlatform(): Platform {
  if (typeof window === "undefined") return "unknown";

  if (
    typeof chrome !== "undefined" &&
    typeof chrome.runtime !== "undefined" &&
    chrome.runtime.id
  ) {
    return "browser_extension";
  }

  const ua = navigator.userAgent || navigator.vendor || "";
  const mobile =
    /android|iphone|ipad|ipod/i.test(ua) ||
    (typeof navigator.maxTouchPoints === "number" &&
      navigator.maxTouchPoints > 1);

  if (mobile) return "mobile_app";

  return "web";
}

export function isBrowserExtension(): boolean {
  return detectPlatform() === "browser_extension";
}

export function isMobileApp(): boolean {
  return detectPlatform() === "mobile_app";
}

export function isWeb(): boolean {
  return detectPlatform() === "web";
}
