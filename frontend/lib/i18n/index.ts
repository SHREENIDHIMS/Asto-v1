"use client";

import { en, type TranslationKey } from "./en";

export type Locale = "en";

/** Resolve a dot-notation key against the English dictionary. */
export function translate(key: TranslationKey): string {
  const value = key.split(".").reduce<unknown>((acc, part) => {
    if (acc && typeof acc === "object") return (acc as Record<string, unknown>)[part];
    return undefined;
  }, en);
  return typeof value === "string" ? value : key;
}

/**
 * N2 — i18n hook. Ship English first; to add a language, provide a
 * dictionary with the same shape as `en` and return it here.
 */
export function useI18n() {
  return { t: translate, locale: "en" as Locale };
}