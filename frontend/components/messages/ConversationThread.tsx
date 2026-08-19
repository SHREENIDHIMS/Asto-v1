"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, MessageSquare, RefreshCw, Send, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { cn } from "@/lib/utils";
import { Conversation, Message } from "@/lib/api-client";

function formatTime(value: string | null): string {
  if (!value) return "";
  const d = new Date(value);
  return d.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

interface ConversationThreadProps {
  conversations: Conversation[];
  /** sender_type value that counts as "me" for bubble alignment. */
  selfSenderType: "staff" | "client";
  loadMessages: (conversationId: number) => Promise<Message[]>;
  sendMessage: (conversationId: number, body: string) => Promise<void>;
  emptyLabel?: string;
}

export default function ConversationThread({
  conversations,
  selfSenderType,
  loadMessages,
  sendMessage,
  emptyLabel = "No conversations yet.",
}: ConversationThreadProps) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const selected = conversations.find((c) => c.id === selectedId) ?? null;

  useEffect(() => {
    if (selectedId == null && conversations.length > 0) {
      setSelectedId(conversations[0].id);
    } else if (conversations.length > 0 && !conversations.some((c) => c.id === selectedId)) {
      setSelectedId(conversations[0].id);
    }
  }, [conversations, selectedId]);

  const refresh = useCallback(
    async (id: number) => {
      setLoading(true);
      setError(null);
      try {
        setMessages(await loadMessages(id));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load messages");
      } finally {
        setLoading(false);
      }
    },
    [loadMessages]
  );

  useEffect(() => {
    if (selectedId != null) refresh(selectedId);
  }, [selectedId, refresh]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages.length, loading]);

  const handleSend = async () => {
    if (selectedId == null || !draft.trim() || sending) return;
    const body = draft.trim();
    setSending(true);
    setError(null);
    // Optimistic send (N7): append the message immediately, then reconcile
    // with the server. The temp id is negative so it can't collide.
    const tempId = -Date.now();
    const optimistic: Message = {
      id: tempId,
      conversation_id: selectedId,
      sender_type: selfSenderType,
      sender_user_id: null,
      sender_client_id: null,
      sender_name: null,
      body,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimistic]);
    setDraft("");
    try {
      await sendMessage(selectedId, body);
      await refresh(selectedId);
    } catch (err) {
      setMessages((prev) => prev.filter((m) => m.id !== tempId));
      setDraft(body);
      setError(err instanceof Error ? err.message : "Failed to send message");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
      <div className="space-y-2">
        {conversations.length === 0 ? (
          <Card>
            <CardContent className="p-4 text-sm text-muted-foreground">
              {emptyLabel}
            </CardContent>
          </Card>
        ) : (
          conversations.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => setSelectedId(c.id)}
              className={cn(
                "w-full text-left rounded-lg border border-border p-3 transition-colors",
                selectedId === c.id ? "bg-accent ring-1 ring-primary" : "hover:bg-accent/50"
              )}
            >
              <div className="flex items-center gap-2">
                <MessageSquare className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
                <p className="text-sm font-medium truncate">{c.subject}</p>
              </div>
              <p className="text-xs text-muted-foreground mt-1 truncate">
                {c.case_number ? `Case ${c.case_number} · ` : ""}
                {c.client_name ?? ""}
              </p>
            </button>
          ))
        )}
      </div>

      <Card>
        <CardContent className="p-0 flex flex-col min-h-[420px]">
          {selected == null ? (
            <div className="flex flex-1 items-center justify-center p-8 text-sm text-muted-foreground">
              Select a conversation to read and reply.
            </div>
          ) : (
            <>
              <div className="px-4 py-3 border-b border-border">
                <p className="text-sm font-medium">{selected.subject}</p>
                <p className="text-xs text-muted-foreground">
                  {selected.case_number ? `Case ${selected.case_number}` : "General"}
                  {selected.client_name ? ` · ${selected.client_name}` : ""}
                </p>
              </div>

              <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
                {error && (
                  <Alert variant="destructive">
                    <AlertCircle className="h-4 w-4" />
                    <AlertDescription>{error}</AlertDescription>
                    {selectedId != null && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="mt-2"
                        onClick={() => refresh(selectedId)}
                      >
                        <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
                        Retry
                      </Button>
                    )}
                  </Alert>
                )}
                {loading ? (
                  <div className="flex justify-center py-8">
                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                  </div>
                ) : messages.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-8">
                    No messages yet. Say hello to start.
                  </p>
                ) : (
                  messages.map((m) => {
                    const mine = m.sender_type === selfSenderType;
                    return (
                      <div key={m.id} className={cn("flex", mine ? "justify-end" : "justify-start")}>
                        <div
                          className={cn(
                            "max-w-[75%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
                            mine
                              ? "bg-primary text-primary-foreground rounded-br-sm"
                              : "bg-muted text-foreground rounded-bl-sm"
                          )}
                        >
                          {!mine && (
                            <p className="text-xs font-medium mb-1 opacity-80">
                              {m.sender_name ?? "Bank team"}
                            </p>
                          )}
                          <p className="whitespace-pre-wrap">{m.body}</p>
                          <p
                            className={cn(
                              "text-xs mt-1",
                              mine ? "text-primary-foreground/70" : "text-muted-foreground"
                            )}
                          >
                            {formatTime(m.created_at)}
                          </p>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>

              <div className="border-t border-border p-3 flex items-center gap-2">
                <Input
                  placeholder="Type a message…"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      handleSend();
                    }
                  }}
                />
                <Button
                  type="button"
                  size="icon"
                  onClick={handleSend}
                  disabled={!draft.trim() || sending || loading}
                  aria-label="Send message"
                >
                  {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
