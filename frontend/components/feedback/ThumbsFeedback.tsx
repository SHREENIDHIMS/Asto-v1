"use client";

import { useState } from "react";
import { ThumbsUp, ThumbsDown, Send, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { submitFeedback } from "@/lib/api-client";
import { getToken } from "@/lib/auth";

interface ThumbsFeedbackProps {
  responseId: string;
}

export default function ThumbsFeedback({ responseId }: ThumbsFeedbackProps) {
  const [rating, setRating] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleRate = (value: number) => {
    setRating(value);
    setError(null);
  };

  const handleSubmit = async () => {
    if (rating === null) return;

    setIsSubmitting(true);
    setError(null);

    try {
      await submitFeedback(
        {
          response_id: responseId,
          rating: rating === 1 ? 1 : -1,
          comment: comment.trim() || undefined,
        },
        getToken() ?? undefined
      );
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Feedback submission failed");
    } finally {
      setIsSubmitting(false);
    }
  };

  if (submitted) {
    return (
      <div className="mt-4 text-sm text-muted-foreground">
        Thank you for your feedback!
      </div>
    );
  }

  return (
    <div className="mt-6 pt-4 border-t border-border">
      <p className="text-sm font-medium text-foreground mb-2">
        Was this helpful?
      </p>
      <div className="flex items-center gap-3 mb-3">
        <Button
          type="button"
          variant="outline"
          onClick={() => handleRate(1)}
          className={cn(
            "flex items-center gap-1 text-sm rounded-lg",
            rating === 1 &&
              "bg-green-100 text-green-800 border-green-300 hover:bg-green-100"
          )}
        >
          <ThumbsUp className="w-3.5 h-3.5" />
          Helpful
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => handleRate(-1)}
          className={cn(
            "flex items-center gap-1 text-sm rounded-lg",
            rating === -1 &&
              "bg-red-100 text-red-800 border-red-300 hover:bg-red-100"
          )}
        >
          <ThumbsDown className="w-3.5 h-3.5" />
          Not helpful
        </Button>
      </div>

      {error && <p className="mb-3 text-sm text-destructive">{error}</p>}

      {rating !== null && (
        <div className="flex items-end gap-2">
          <Textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Add a comment (optional)"
            rows={2}
            maxLength={500}
            className="flex-1 resize-none"
          />
          <Button
            type="button"
            onClick={handleSubmit}
            disabled={isSubmitting}
            className="shrink-0"
            aria-label="Submit feedback"
          >
            {isSubmitting ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Send className="w-3.5 h-3.5" />
            )}
          </Button>
        </div>
      )}
    </div>
  );
}
