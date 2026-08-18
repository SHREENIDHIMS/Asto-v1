"use client";

import { Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  SearchStage,
  StreamedSentence,
  StructuredFact,
} from "@/lib/api-client";
import { HighlightedText } from "@/components/chat/HighlightedText";

interface StreamingPreviewProps {
  stage: SearchStage | null;
  facts: StructuredFact[];
  sentences: StreamedSentence[];
  className?: string;
}

const STAGE_LABEL: Record<SearchStage, string> = {
  processing: "Understanding your question…",
  searching: "Searching internal documents…",
  ranking: "Ranking the best matches…",
  packaging: "Preparing your answer…",
  done: "Done",
};

/**
 * Rendered while a streaming search is in flight. Shows pipeline stage,
 * then streams facts / summary sentences verbatim as they arrive from the
 * SSE stream — nothing here is client-generated text.
 */
export default function StreamingPreview({
  stage,
  facts,
  sentences,
  className,
}: StreamingPreviewProps) {
  const hasContent = facts.length > 0 || sentences.length > 0;
  const streamedTerms = Array.from(
    new Set(
      sentences.flatMap((s) => s.matched_terms ?? [])
    )
  );

  return (
    <div className="flex gap-3">
      <div className="flex items-center justify-center w-8 h-8 rounded-full bg-muted border border-border">
        <Sparkles className="w-4 h-4 animate-pulse" />
      </div>
      <div
        className={cn(
          "rounded-2xl rounded-tl-sm border border-border bg-card p-4 shadow-sm space-y-2 min-w-0 flex-1",
          className
        )}
      >
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "h-3 w-3 rounded-full animate-pulse",
              hasContent ? "bg-primary" : "bg-muted-foreground/50"
            )}
          />
          <span className="text-xs text-muted-foreground">
            {stage ? STAGE_LABEL[stage] : "Working…"}
          </span>
        </div>

        {sentences.length > 0 && (
          <p className="text-sm leading-relaxed text-foreground">
            <HighlightedText
              text={sentences.map((s) => s.text).filter(Boolean).join(" ")}
              terms={streamedTerms}
            />
          </p>
        )}

        {facts.length > 0 && (
          <div className="space-y-1 border-t border-border pt-2">
            {facts.map((f, i) => (
              <div
                key={`${f.label}-${i}`}
                className="flex items-baseline justify-between gap-4 text-sm"
              >
                <span className="text-muted-foreground">{f.label}</span>
                <span className="text-right font-medium">
                  {f.value ?? "—"}
                </span>
              </div>
            ))}
          </div>
        )}

        {!hasContent && (
          <>
            <div className="h-3 w-40 bg-muted rounded animate-pulse" />
            <div className="h-3 w-64 bg-muted rounded animate-pulse" />
            {stage === "processing" && (
              <div className="h-3 w-52 bg-muted rounded animate-pulse" />
            )}
          </>
        )}
      </div>
    </div>
  );
}
