"use client";

import { useRef, useState } from "react";
import {
  Check,
  Copy,
  Speaker,
  StopCircle,
  RefreshCw,
  ThumbsUp,
  ThumbsDown,
  Send,
  Loader2,
  MoreVertical,
} from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipProvider, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { ChatTurn } from "@/hooks/use-chat-history";
import { submitFeedback } from "@/lib/api-client";
import { getToken } from "@/lib/auth";

interface AssistantMessageProps {
  turn: ChatTurn;
  onRegenerate: () => void;
  isRegenerating?: boolean;
  className?: string;
}

function confidenceLabel(routing: ChatTurn["response"]["routing"]): string {
  switch (routing) {
    case "answer":
      return "High";
    case "partial":
      return "Partial";
    case "no_answer":
      return "No match";
    default:
      return "Low";
  }
}

/** Structured facts (fact path) rendered as verbatim rows with a source line. */
function FactRows({ facts }: { facts: ChatTurn["response"]["facts"] }) {
  const rows = facts ?? [];
  return (
    <div className="mt-3 space-y-1 border-t border-border pt-3">
      {rows.map((f, i) => (
        <div key={`${f.label}-${i}`} className="flex items-baseline justify-between gap-4 text-sm">
          <span className="text-muted-foreground">{f.label}</span>
          <span className="text-right font-medium">{f.value ?? "—"}</span>
        </div>
      ))}
    </div>
  );
}

/** Answer text shown in the bubble.
 *
 * Prefers the backend-assembled `answer` (fact-path template bubble or
 * document-path extractive summary — both are verbatim-value only). Falls
 * back to joining summary sentences client-side for older cached turns,
 * then the first excerpt. */
function buildAnswerText(turn: ChatTurn): string {
  if (turn.response.answer && turn.response.answer.trim()) {
    return turn.response.answer.trim();
  }
  const parts: string[] = [];
  const seen = new Set<string>();
  for (const s of turn.response.summary ?? []) {
    const text = s.text.trim();
    if (text && !seen.has(text)) {
      seen.add(text);
      parts.push(text);
    }
  }
  let text = parts.join(" ");
  if (!text && turn.response.excerpts.length > 0) {
    text = turn.response.excerpts[0].text.trim();
  }
  return text;
}

export default function AssistantMessage({
  turn,
  onRegenerate,
  isRegenerating,
  className,
}: AssistantMessageProps) {
  const { response } = turn;
  const noAnswer = response.routing === "no_answer";
  const answerText = buildAnswerText(turn);
  const hasFacts = (response.facts ?? []).length > 0;

  const showFeedback = !noAnswer && (Boolean(answerText) || hasFacts);

  const time = turn.timestamp
    ? new Date(turn.timestamp).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;

  const [copied, setCopied] = useState(false);
  const [rating, setRating] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const [showComment, setShowComment] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [speaking, setSpeaking] = useState(false);

  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);

  const handleCopy = async () => {
    if (!answerText && noAnswer) {
      await navigator.clipboard.writeText(
        "I couldn't find enough information in the available documents to answer that confidently."
      );
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
      return;
    }
    if (!answerText && !hasFacts) return;
    const factLines = (response.facts ?? [])
      .map((f) => `${f.label}: ${f.value ?? "—"} (${f.source})`)
      .join("\n");
    try {
      await navigator.clipboard.writeText(
        [answerText, factLines].filter(Boolean).join("\n")
      );
    } catch {
      // ignore
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };

  const handleSpeak = () => {
    const text = answerText || "";
    if (!("speechSynthesis" in window) || !text) return;
    if (speaking) {
      window.speechSynthesis.cancel();
      setSpeaking(false);
      return;
    }
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1;
    u.onend = () => setSpeaking(false);
    utteranceRef.current = u;
    window.speechSynthesis.speak(u);
    setSpeaking(true);
  };

  const handleRate = (value: number) => {
    setRating(value);
    setShowComment(true);
    setSubmitError(null);
  };

  const doSubmitFeedback = async () => {
    if (rating === null) return;
    setIsSubmitting(true);
    setSubmitError(null);
    try {
      await submitFeedback(
        {
          response_id: response.response_id,
          rating: rating === 1 ? 1 : -1,
          comment: comment.trim() || undefined,
        },
        getToken() ?? undefined
      );
      setShowComment(false);
      setComment("");
      setRating(null);
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : "Feedback submission failed"
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const distinctSources: string[] = [];
  const seen = new Set<string>();
  for (const s of response.summary) {
    const key = `${s.source.title}::${s.source.section ?? ""}`;
    if (!seen.has(key)) {
      seen.add(key);
      distinctSources.push(s.source.title);
    }
  }
  for (const e of response.excerpts) {
    const key = `${e.source.title}::${e.source.section ?? ""}`;
    if (!seen.has(key)) {
      seen.add(key);
      distinctSources.push(e.source.title);
    }
  }
  for (const f of response.facts ?? []) {
    if (f.source && !seen.has(f.source)) {
      seen.add(f.source);
      distinctSources.push(f.source);
    }
  }

  const noAnswerText =
    "I couldn't find enough information in the available documents to answer that confidently.";

  return (
    <div
      className={cn("flex gap-3", className)}
      data-testid="assistant-message"
    >
      <div className="flex-shrink-0 mt-1">
        <Avatar className="h-8 w-8 border border-border">
          <AvatarFallback className="bg-primary text-primary-foreground text-xs font-bold">
            A
          </AvatarFallback>
        </Avatar>
      </div>

      <div className="min-w-0 flex-1 space-y-2.5">
        {/* Header: name + timestamp only (no confidence badge). */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-muted-foreground">
              Asto
            </span>
            {time && (
              <span className="text-xs text-muted-foreground/60">· {time}</span>
            )}
          </div>
        </div>

        {/* Answer bubble */}
        <div
          className={cn(
            "rounded-2xl rounded-tl-sm border border-border bg-card p-4 shadow-sm text-sm leading-relaxed whitespace-pre-wrap break-words",
            noAnswer && "text-muted-foreground"
          )}
        >
          {noAnswer ? (
            <p className="m-0">{noAnswerText}</p>
          ) : (
            <>
              {answerText && <p className="m-0">{answerText}</p>}
              {hasFacts && <FactRows facts={response.facts} />}
              {!answerText && !hasFacts && (
                <p className="m-0">{noAnswerText}</p>
              )}
            </>
          )}
        </div>

        {/* Action row */}
        <div className="flex items-center gap-1 -ml-1">
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-8 w-8 rounded-full p-0"
                  onClick={handleCopy}
                  aria-label="Copy answer"
                >
                  {copied ? (
                    <Check className="h-3.5 w-3.5 text-green-500" />
                  ) : (
                    <Copy className="h-3.5 w-3.5" />
                  )}
                </Button>
              </TooltipTrigger>
              <TooltipContent>Copy</TooltipContent>
            </Tooltip>

            {showFeedback && (
              <>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-8 w-8 rounded-full p-0"
                      onClick={() => handleRate(1)}
                      aria-label="This was helpful"
                    >
                      <ThumbsUp className="h-3.5 w-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Like</TooltipContent>
                </Tooltip>

                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-8 w-8 rounded-full p-0"
                      onClick={() => handleRate(-1)}
                      aria-label="This was not helpful"
                    >
                      <ThumbsDown className="h-3.5 w-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Dislike</TooltipContent>
                </Tooltip>
              </>
            )}

            {!noAnswer && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8 w-8 rounded-full p-0"
                    onClick={handleSpeak}
                    aria-label={speaking ? "Stop reading" : "Read aloud"}
                  >
                    {speaking ? (
                      <StopCircle className="h-3.5 w-3.5 text-primary" />
                    ) : (
                      <Speaker className="h-3.5 w-3.5" />
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{speaking ? "Stop" : "Read aloud"}</TooltipContent>
              </Tooltip>
            )}

            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-8 w-8 rounded-full p-0"
                  onClick={onRegenerate}
                  disabled={isRegenerating}
                  aria-label="Regenerate response"
                >
                  {isRegenerating ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <RefreshCw className="h-3.5 w-3.5" />
                  )}
                </Button>
              </TooltipTrigger>
              <TooltipContent>Regenerate</TooltipContent>
            </Tooltip>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-8 w-8 rounded-full p-0"
                  aria-label="More"
                >
                  <MoreVertical className="h-3.5 w-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-60">
                <div className="px-3 py-2 text-xs text-muted-foreground">
                  Sources
                </div>
                {distinctSources.length === 0 ? (
                  <DropdownMenuItem disabled className="text-xs py-1.5">
                    No source documents
                  </DropdownMenuItem>
                ) : (
                  distinctSources.map((title) => (
                    <DropdownMenuItem key={title} className="text-xs py-1.5">
                      {title}
                    </DropdownMenuItem>
                  ))
                )}
                <DropdownMenuSeparator />
                <div className="px-3 py-2 text-xs text-muted-foreground">
                  Confidence
                </div>
                <DropdownMenuItem className="text-xs py-1.5">
                  <span className="inline-flex items-center gap-1.5">
                    <span
                      className={cn(
                        "h-2 w-2 rounded-full",
                        response.routing === "answer"
                          ? "bg-green-500"
                          : response.routing === "partial"
                          ? "bg-yellow-500"
                          : "bg-gray-400"
                      )}
                    />
                    <span>{confidenceLabel(response.routing)}</span>
                    <span className="opacity-60">· {Math.round(response.confidence)}%</span>
                  </span>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </TooltipProvider>
        </div>

        {showComment && (
          <div className="mt-2 flex items-end gap-2">
            <Textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Add a comment (optional)"
              rows={2}
              maxLength={500}
              className="flex-1 resize-none text-sm"
            />
            <Button
              type="button"
              size="sm"
              className="shrink-0 h-8 w-8 rounded-full p-0"
              onClick={doSubmitFeedback}
              disabled={isSubmitting}
              aria-label="Submit feedback"
            >
              {isSubmitting ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Send className="h-3.5 w-3.5" />
              )}
            </Button>
          </div>
        )}
        {submitError && <p className="text-xs text-destructive">{submitError}</p>}
      </div>
    </div>
  );
}
