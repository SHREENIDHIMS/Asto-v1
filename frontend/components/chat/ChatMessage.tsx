"use client";

import UserMessage from "@/components/chat/UserMessage";
import AssistantMessage from "@/components/chat/AssistantMessage";
import { ChatTurn } from "@/hooks/use-chat-history";

export interface ChatMessageProps {
  turn: ChatTurn;
  onRegenerate: () => void;
  isRegenerating?: boolean;
}

export default function ChatMessage({
  turn,
  onRegenerate,
  isRegenerating,
}: ChatMessageProps) {
  return (
    <div className="space-y-4">
      <UserMessage turn={turn} />
      <AssistantMessage
        turn={turn}
        onRegenerate={onRegenerate}
        isRegenerating={isRegenerating}
      />
    </div>
  );
}
