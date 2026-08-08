"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  AlertCircle,
  Home,
  LayoutDashboard,
  LogOut,
  MessageSquarePlus,
  ShieldCheck,
  Sparkles,
  Trash2,
} from "lucide-react";
import { searchKnowledgeBaseStream, SearchResponse, SearchStage } from "@/lib/api-client";
import { clearToken, decodeToken, getToken } from "@/lib/auth";
import { useChatHistory } from "@/hooks/use-chat-history";
import ChatMessage from "@/components/chat/ChatMessage";
import SearchBar from "@/components/search/SearchBar";
import RelatedQuestions from "@/components/search/RelatedQuestions";
import HeroSection from "@/components/home/HeroSection";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

export default function ChatPage() {
  const router = useRouter();
  const { turns, loaded, appendTurn, clearHistory, removeTurn } = useChatHistory();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [stage, setStage] = useState<SearchStage | null>(null);
  const [isAuthed, setIsAuthed] = useState(false);
  const [audience, setAudience] = useState<"staff" | "client" | null>(null);
  const [role, setRole] = useState<string | null>(null);
  const [showSignOutDialog, setShowSignOutDialog] = useState(false);
  const [showClearDialog, setShowClearDialog] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const token = getToken();
    setIsAuthed(Boolean(token));
    const claims = token ? decodeToken(token) : null;
    setAudience(claims?.audience ?? null);
    setRole(claims?.role ?? null);

    if (!token) {
      router.replace("/login");
      return;
    }
    // Auto-route each identity to its own interface.
    if (claims?.audience === "client") {
      router.replace("/client");
      return;
    }
    if (claims?.role === "admin") {
      router.replace("/admin");
      return;
    }
    // Staff (non-admin) stay on the staff chat.
  }, [router]);

  useEffect(() => {
    // Scroll to bottom whenever the conversation changes or loading starts.
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [turns.length, isLoading, pendingQuestion]);

  const handleLogout = useCallback(() => {
    clearToken();
    setIsAuthed(false);
    setAudience(null);
    setRole(null);
    setShowSignOutDialog(false);
    router.push("/login");
  }, [router]);

  const handleSearch = async (q: string) => {
    if (isLoading) return;
    setPendingQuestion(q);
    setStage(null);
    setIsLoading(true);
    setError(null);

    try {
      const token = getToken() ?? undefined;
      const result: SearchResponse = await searchKnowledgeBaseStream(
        q,
        token,
        (s) => setStage(s)
      );
      appendTurn(q, result);
      setPendingQuestion(null);
      setStage(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setPendingQuestion(null);
      setStage(null);
    } finally {
      setIsLoading(false);
    }
  };

  const handleAskRelated = (question: string) => {
    handleSearch(question);
  };

  const isAdmin = role === "admin";
  const isClient = audience === "client";

  const stageLabel =
    stage === "processing"
      ? "Understanding your question…"
      : stage === "searching"
        ? "Searching internal documents…"
        : stage === "ranking"
          ? "Ranking the best matches…"
          : stage === "packaging"
            ? "Preparing your answer…"
            : null;

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <header className="border-b border-border bg-card/50 backdrop-blur-sm sticky top-0 z-10 flex-shrink-0">
        <div className="max-w-4xl mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-primary text-primary-foreground">
              <Sparkles className="w-4 h-4" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-foreground">Asto</h1>
              <p className="text-xs text-muted-foreground -mt-0.5">
                {isClient ? "Client Portal" : "Knowledge Assistant"}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {isClient && (
              <Button asChild variant="outline" size="sm">
                <Link href="/portal">
                  <Home className="h-4 w-4 mr-2" />
                  My Dashboard
                </Link>
              </Button>
            )}
            {isAdmin && (
              <Button asChild variant="outline" size="sm">
                <Link href="/admin">
                  <LayoutDashboard className="h-4 w-4 mr-2" />
                  Admin
                </Link>
              </Button>
            )}
            {isAuthed ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setShowSignOutDialog(true)}
              >
                <LogOut className="h-4 w-4 mr-2" />
                Sign out
              </Button>
            ) : (
              <Button asChild size="sm">
                <Link href="/login">Sign in</Link>
              </Button>
            )}
          </div>
        </div>
      </header>

      <main
        ref={scrollRef}
        className="flex-1 min-h-0 overflow-y-auto"
      >
        <div className="max-w-4xl mx-auto px-4 py-6 pb-24">
          {turns.length === 0 && !isLoading && !error && (
            <HeroSection onSearch={handleSearch} />
          )}

          {error && (
            <Alert variant="destructive" className="mt-8 mx-auto max-w-2xl">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Search failed</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {turns.length > 0 && (
            <div className="space-y-8 mt-4">
              {turns.map((turn) => (
                <div key={turn.id} className="relative group">
                  <ChatMessage turn={turn} />
                  <div className="mt-2 flex items-center justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => removeTurn(turn.id)}
                      className="text-xs text-muted-foreground"
                    >
                      <Trash2 className="h-3 w-3 mr-1" />
                      Remove
                    </Button>
                  </div>
                  {turn.response.related_questions.length > 0 && (
                    <RelatedQuestions
                      questions={turn.response.related_questions}
                      onAskQuestion={handleAskRelated}
                    />
                  )}
                </div>
              ))}
            </div>
          )}

          {isLoading && pendingQuestion && (
            <div className="space-y-4 mt-8">
              <div className="flex justify-end">
                <div className="bg-muted text-foreground rounded-2xl rounded-br-sm px-4 py-2.5 text-sm leading-relaxed">
                  {pendingQuestion}
                </div>
              </div>
              <div className="flex gap-3">
                <div className="flex items-center justify-center w-8 h-8 rounded-full bg-muted border border-border">
                  <Sparkles className="w-4 h-4 animate-pulse" />
                </div>
                <div className="rounded-2xl rounded-tl-sm border border-border bg-card p-4 shadow-sm space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="h-3 w-3 rounded-full bg-primary animate-pulse" />
                    <span className="text-xs text-muted-foreground">
                      {stageLabel ?? "Working…"}
                    </span>
                  </div>
                  <div className="h-3 w-40 bg-muted rounded animate-pulse" />
                  <div className="h-3 w-64 bg-muted rounded animate-pulse" />
                  <div className="h-3 w-52 bg-muted rounded animate-pulse" />
                </div>
              </div>
            </div>
          )}
        </div>
      </main>

      <div className="border-t border-border flex-shrink-0 bg-background">
        <div className="max-w-4xl mx-auto px-4 py-4">
          <div className="flex items-center gap-2 mb-2">
            {turns.length > 0 && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setShowClearDialog(true)}
                className="text-xs text-muted-foreground"
              >
                <MessageSquarePlus className="h-3.5 w-3.5 mr-1.5" />
                New conversation
              </Button>
            )}
            <p className="text-xs text-muted-foreground ml-auto">
              Responses are sourced verbatim from internal documents.
            </p>
          </div>
          <SearchBar
            onSearch={handleSearch}
            isLoading={isLoading}
            placeholder="Ask about requirements, policies, or documents..."
          />
        </div>
      </div>

      <AlertDialog open={showSignOutDialog} onOpenChange={setShowSignOutDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Are you sure you want to sign out?</AlertDialogTitle>
            <AlertDialogDescription>
              You&apos;ll need to sign in again to search the knowledge base.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleLogout}>Sign out</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={showClearDialog} onOpenChange={setShowClearDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Start a new conversation?</AlertDialogTitle>
            <AlertDialogDescription>
              This clears the current chat history from this browser. The 24-hour
              history will be reset.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                clearHistory();
                setShowClearDialog(false);
              }}
            >
              Clear
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {!loaded && null}
      {audience === "client" && (
        <div className="fixed bottom-16 left-1/2 -translate-x-1/2 z-10">
          <div className="bg-primary text-primary-foreground text-xs px-3 py-1.5 rounded-full shadow-lg flex items-center gap-1.5">
            <ShieldCheck className="w-3.5 h-3.5" />
            You can only see your own approved documents
          </div>
        </div>
      )}
    </div>
  );
}
