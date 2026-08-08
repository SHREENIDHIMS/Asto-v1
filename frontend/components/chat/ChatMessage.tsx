"use client";

import { User } from "lucide-react";
import { SearchResponse } from "@/lib/api-client";
import { ChatTurn } from "@/hooks/use-chat-history";
import ResponsePackageCard from "@/components/search/ResponsePackageCard";
import ConfidenceBadge from "@/components/search/ConfidenceBadge";
import ThumbsFeedback from "@/components/feedback/ThumbsFeedback";
import { cn } from "@/lib/utils";

interface ChatMessageProps {
  turn: ChatTurn;
}

export default function ChatMessage({ turn }: ChatMessageProps) {
  const noAnswer = turn.response.routing === "no_answer";

  return (
    <div className="space-y-4">
      {/* User bubble */}
      <div className="flex justify-end">
        <div className="flex items-end gap-2 max-w-[85%]">
          <div className="bg-primary text-primary-foreground rounded-2xl rounded-br-sm px-4 py-2.5 text-sm leading-relaxed">
            {turn.query}
          </div>
        </div>
      </div>

      {/* Assistant bubble */}
      <div className="flex gap-3">
        <div className="flex-shrink-0 mt-1">
          <div className="flex items-center justify-center w-8 h-8 rounded-full bg-muted border border-border">
            <User className="w-4 h-4" />
          </div>
        </div>
        <div className="min-w-0 flex-1 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-semibold text-muted-foreground">
              Asto
            </span>
            {!noAnswer && (
              <ConfidenceBadge
                confidence={turn.response.confidence}
                routing={turn.response.routing}
                size="sm"
              />
            )}
          </div>

          <div
            className={cn(
              "rounded-2xl rounded-tl-sm border border-border bg-card shadow-sm p-4"
            )}
          >
            <ResponsePackageCard
              title={turn.response.title}
              excerpts={turn.response.excerpts}
              summary={turn.response.summary}
              confidence={turn.response.confidence}
              routing={turn.response.routing}
            />
          </div>

          {!noAnswer && (
            <ThumbsFeedback responseId={turn.response.response_id} />
          )}
        </div>
      </div>
    </div>
  );
}
