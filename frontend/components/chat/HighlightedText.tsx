"use client";

import { Fragment } from "react";
import { cn } from "@/lib/utils";

interface HighlightedTextProps {
  text: string;
  terms?: string[];
  className?: string;
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Render ``text`` with each matched query term wrapped in a ``<mark>``.
 *
 * Safe by construction: text is split on the matched terms (case-insensitive
 * whole-word matches) and re-assembled as React nodes — never parsed as HTML,
 * so retrieved content cannot inject markup. Terms come verbatim from the
 * backend ``matched_terms`` (retrieved values, not generated text).
 */
export function HighlightedText({ text, terms, className }: HighlightedTextProps) {
  const activeTerms = (terms ?? []).filter((t) => t && t.trim().length > 0);
  if (activeTerms.length === 0) {
    return <span className={className}>{text}</span>;
  }

  const pattern = activeTerms.map(escapeRegex).join("|");
  const regex = new RegExp(`\\b(${pattern})\\b`, "gi");
  const parts = text.split(regex);

  return (
    <span className={className}>
      {parts.map((part, i) => {
        if (i % 2 === 1) {
          return (
            <mark
              key={i}
              className="bg-yellow-200 text-foreground rounded-sm px-0.5"
            >
              {part}
            </mark>
          );
        }
        return <Fragment key={i}>{part}</Fragment>;
      })}
    </span>
  );
}
