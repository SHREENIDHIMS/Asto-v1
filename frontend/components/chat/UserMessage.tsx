"use client";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";
import { ChatTurn } from "@/hooks/use-chat-history";

interface UserMessageProps {
  turn: ChatTurn;
  className?: string;
}

export default function UserMessage({ turn, className }: UserMessageProps) {
  const time = turn.timestamp
    ? new Date(turn.timestamp).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;

  return (
    <div
      className={cn(
        "flex items-end justify-end gap-2",
        className
      )}
    >
      <div className="max-w-[80%]">
        <div
          className={cn(
            "inline-block rounded-2xl rounded-br-sm bg-primary text-primary-foreground px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap",
            turn.urgency && "border-2 border-destructive"
          )}
        >
          {turn.query}
        </div>
        <div className="mt-1.5 flex items-center justify-end gap-2">
          {time && <span className="text-xs text-muted-foreground/60">· {time}</span>}
          {turn.urgency && (
            <span
              className="inline-flex items-center gap-1 text-xs font-medium text-destructive"
              aria-label="Time-sensitive"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-destructive" />
              Urgent
            </span>
          )}
        </div>
      </div>
      <Avatar className="h-8 w-8 border border-border">
        <AvatarFallback className="bg-primary/10 text-primary text-xs font-bold">
          U
        </AvatarFallback>
      </Avatar>
    </div>
  );
}
