"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  Bookmark,
  History,
  MessageSquarePlus,
  Sparkles,
  Trash2,
} from "lucide-react";
import {
  getStaffDashboard,
  listSavedSearches,
  listRecentSearches,
  logout,
  logoutAll,
  saveSearch,
  deleteSavedSearch,
  RecentSearch,
  SavedSearch,
  searchKnowledgeBaseStream,
  SearchFilters,
  SearchResponse,
  SearchStage,
  StaffDashboardCase,
  StreamedSentence,
  StructuredFact,
} from "@/lib/api-client";
import { clearToken, decodeToken, getToken, isAdminRole, restoreSession } from "@/lib/auth";
import { clearClientLocalState } from "@/lib/session-cleanup";
import { useChatHistory } from "@/hooks/use-chat-history";
import ChatMessage from "@/components/chat/ChatMessage";
import StreamingPreview from "@/components/chat/StreamingPreview";
import SearchBar from "@/components/search/SearchBar";
import SearchFilterBar from "@/components/search/SearchFilterBar";
import RelatedQuestions from "@/components/search/RelatedQuestions";
import HeroSection from "@/components/home/HeroSection";
import SettingsModal from "@/components/settings/SettingsModal";
import AppShell from "@/components/layout/AppShell";
import { NAV_GROUPS } from "@/config/navigation";
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
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

export default function ChatPage() {
  const router = useRouter();
  const { turns, appendTurn, clearHistory, removeTurn, replaceTurnResponse } = useChatHistory();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [stage, setStage] = useState<SearchStage | null>(null);
  const [streamFacts, setStreamFacts] = useState<StructuredFact[]>([]);
  const [streamSentences, setStreamSentences] = useState<StreamedSentence[]>([]);
  const [role, setRole] = useState<string | null>(null);
  const [userName, setUserName] = useState<string | null>(null);
  const [showClearDialog, setShowClearDialog] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [regeneratingId, setRegeneratingId] = useState<string | null>(null);
  const [showSuggestions, setShowSuggestions] = useState<boolean>(true);
  const [sessionTimeout, setSessionTimeout] = useState<number>(0);

  useEffect(() => {
    try {
      setShowSuggestions(localStorage.getItem("asto_smart_suggestions") !== "0");
      const raw = localStorage.getItem("asto_session_timeout");
      if (raw) setSessionTimeout(Number(raw));
    } catch {
      // ignore storage errors
    }
  }, []);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [prefill, setPrefill] = useState<string | null>(null);
  const [cases, setCases] = useState<StaffDashboardCase[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(null);
  const [casesError, setCasesError] = useState<string | null>(null);
  const [filters, setFilters] = useState<SearchFilters>({});
  const [departments, setDepartments] = useState<string[]>([]);
  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([]);
  const [savedSearchesError, setSavedSearchesError] = useState<string | null>(null);
  const [savingSearch, setSavingSearch] = useState(false);
  const [recentSearches, setRecentSearches] = useState<RecentSearch[]>([]);

  const refreshRecentSearches = useCallback(() => {
    const token = getToken();
    if (!token) return;
    listRecentSearches(token)
      .then((searches) => setRecentSearches(searches))
      .catch(() => {
        // History is a convenience panel — stay silent on failure.
      });
  }, []);

  useEffect(() => {
    let mounted = true;
    restoreSession().then((token) => {
      if (!mounted) return;
      if (!token) {
        router.replace("/login");
        return;
      }
      const claims = decodeToken(token);
      setRole(claims?.role ?? null);
      setUserName(claims?.name ?? claims?.sub ?? null);
      setDepartments(
        claims?.allowed_departments?.length
          ? claims.allowed_departments
          : claims?.department
            ? [claims.department]
            : []
      );
      // Auto-route each identity to its own interface.
      if (claims?.audience === "client") {
        router.replace("/client");
        return;
      }
      if (isAdminRole(claims?.role)) {
        router.replace("/admin");
        return;
      }
      // Staff (non-admin) stay on the staff chat.
      getStaffDashboard(token)
        .then((dash) => setCases(dash.cases ?? []))
        .catch((err) =>
          setCasesError(err instanceof Error ? err.message : "Failed to load cases")
        );
      listSavedSearches(token)
        .then((searches) => setSavedSearches(searches))
        .catch((err) =>
          setSavedSearchesError(
            err instanceof Error ? err.message : "Failed to load saved searches"
          )
        );
      refreshRecentSearches();
    });
    return () => {
      mounted = false;
    };
  }, [router, refreshRecentSearches]);

  useEffect(() => {
    // Scroll to bottom only when a new message/response begins.
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [turns.length, isLoading, pendingQuestion, regeneratingId]);

  const handleLogout = useCallback(() => {
    logout();
    clearToken();
    clearClientLocalState();
    setRole(null);
    router.push("/login");
  }, [router]);

  const handleLogoutAll = useCallback(async () => {
    const t = getToken();
    if (t) {
      try {
        await logoutAll(t);
      } catch {
        // best-effort; local session is cleared regardless
      }
    }
    clearToken();
    clearClientLocalState();
    setRole(null);
    router.push("/login");
  }, [router]);

  const handleClearHistory = useCallback(() => {
    clearHistory();
    setShowClearDialog(false);
  }, [clearHistory]);

  // Session auto-timeout (client-side idle timer). 0 = disabled.
  useEffect(() => {
    if (!sessionTimeout || sessionTimeout <= 0) return;
    let timer: ReturnType<typeof setTimeout>;
    const reset = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        if (
          window.confirm(
            "Your session is about to time out due to inactivity. Stay signed in?"
          )
        ) {
          return;
        }
        handleLogout();
      }, sessionTimeout);
    };
    const events: Array<keyof DocumentEventMap> = [
      "mousemove",
      "keydown",
      "mousedown",
      "touchstart",
      "scroll",
    ];
    const onActivity = () => reset();
    reset();
    events.forEach((e) =>
      window.addEventListener(e, onActivity, { passive: true })
    );
    return () => {
      clearTimeout(timer);
      events.forEach((e) => window.removeEventListener(e, onActivity));
    };
  }, [sessionTimeout, handleLogout]);

  const handleSearch = async (q: string) => {
    if (isLoading) return;
    setPendingQuestion(q);
    setStage(null);
    setStreamFacts([]);
    setStreamSentences([]);
    setIsLoading(true);
    setError(null);
    setPrefill(null);

    try {
      const token = getToken() ?? undefined;
      const result: SearchResponse = await searchKnowledgeBaseStream(
        q,
        token,
        {
          onStage: (s) => setStage(s),
          onFact: (f) => setStreamFacts((prev) => [...prev, f]),
          onSentence: (s) => setStreamSentences((prev) => [...prev, s]),
        },
        selectedCaseId,
        filters
      );
      appendTurn(q, result);
      setPendingQuestion(null);
      setStage(null);
      setStreamFacts([]);
      setStreamSentences([]);
      refreshRecentSearches();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setPendingQuestion(null);
      setStage(null);
      setStreamFacts([]);
      setStreamSentences([]);
    } finally {
      setIsLoading(false);
      setRegeneratingId(null);
    }
  };

  const handleAskRelated = (question: string) => {
    handleSearch(question);
  };

  const handleRegenerateTurn = useCallback(
    async (turnId: string, query: string) => {
      if (isLoading) return;
      setRegeneratingId(turnId);
      setError(null);
      setStreamFacts([]);
      setStreamSentences([]);
      try {
        const token = getToken() ?? undefined;
        const result: SearchResponse = await searchKnowledgeBaseStream(
          query,
          token,
          {
            onStage: (s) => setStage(s),
            onFact: (f) => setStreamFacts((prev) => [...prev, f]),
            onSentence: (s) => setStreamSentences((prev) => [...prev, s]),
          },
          selectedCaseId,
          filters
        );
        // Replace the assistant response in place — do not append.
        replaceTurnResponse(turnId, result);
        setStage(null);
        setStreamFacts([]);
        setStreamSentences([]);
        refreshRecentSearches();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Something went wrong");
        setStage(null);
        setStreamFacts([]);
        setStreamSentences([]);
      } finally {
        setRegeneratingId(null);
      }
    },
    [isLoading, replaceTurnResponse, selectedCaseId, filters, refreshRecentSearches]
  );

  const handleOpenRecentChat = useCallback(
    (turnId: string, query: string) => {
      // Bring that turn into view and re-read it.
      const el = document.getElementById(`turn-${turnId}`);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
      setPrefill(query);
    },
    []
  );

  const handleSaveSearch = useCallback(async () => {
    const token = getToken();
    if (!token || turns.length === 0 || savingSearch) return;
    const lastTurn = turns[turns.length - 1];
    setSavingSearch(true);
    try {
      const saved = await saveSearch(token, lastTurn.query, filters);
      setSavedSearches((prev) => [saved, ...prev].slice(0, 50));
    } catch (err) {
      setSavedSearchesError(
        err instanceof Error ? err.message : "Failed to save search"
      );
    } finally {
      setSavingSearch(false);
    }
  }, [turns, filters, savingSearch]);

  const handleDeleteSavedSearch = useCallback(async (id: number) => {
    const token = getToken();
    if (!token) return;
    try {
      await deleteSavedSearch(token, id);
      setSavedSearches((prev) => prev.filter((s) => s.id !== id));
    } catch (err) {
      setSavedSearchesError(
        err instanceof Error ? err.message : "Failed to delete saved search"
      );
    }
  }, []);

  const handleRunSavedSearch = (saved: SavedSearch) => {
    if (saved.filters && Object.keys(saved.filters).length > 0) {
      setFilters(saved.filters);
    }
    handleSearch(saved.query);
  };

  return (
    <>
      <AppShell
        navGroups={NAV_GROUPS.staff}
      activeNavId="assistant"
      onNavigate={() => {}}
      brandTitle="Asto"
      brandSubtitle="Staff Workspace"
      headerTitle="AI Assistant"
      headerSubtitle="Ask about cases, requirements, or documents"
      sidebarTop={
        <div className="space-y-4">
          <Button
            type="button"
            className="w-full justify-start gap-3"
            onClick={() => setShowClearDialog(true)}
          >
            <MessageSquarePlus className="h-4 w-4" />
            New chat
          </Button>

          <div className="space-y-1">
            <div className="flex items-center justify-between px-1">
              <p className="text-xs font-medium text-muted-foreground">
                Recent chats
              </p>
              {turns.length > 0 && (
                <button
                  type="button"
                  onClick={handleClearHistory}
                  className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
                >
                  <Trash2 className="h-3 w-3" />
                  Clear
                </button>
              )}
            </div>
            <div className="max-h-56 overflow-y-auto space-y-1 pr-1">
              {turns.length === 0 ? (
                <p className="text-xs text-muted-foreground px-1 py-1">
                  No recent chats
                </p>
              ) : (
                [...turns]
                  .reverse()
                  .map((t) => (
                    <div key={t.id} className="group flex items-center gap-1">
                      <button
                        type="button"
                        className="flex-1 justify-start gap-2 font-normal text-sm h-8 px-2 text-left rounded-md hover:bg-muted"
                        onClick={() => handleOpenRecentChat(t.id, t.query)}
                        title={t.query}
                      >
                        <span className="truncate text-xs">
                          {t.query || "Untitled"}
                        </span>
                      </button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 flex-shrink-0 opacity-0 group-hover:opacity-100"
                        onClick={() => removeTurn(t.id)}
                        aria-label={`Remove "${t.query}"`}
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </div>
                  ))
              )}
            </div>
          </div>

          <div className="space-y-1">
            <div className="flex items-center justify-between px-1">
              <p className="text-xs font-medium text-muted-foreground">
                Recent searches
              </p>
            </div>
            <div className="max-h-44 overflow-y-auto space-y-1 pr-1">
              {recentSearches.length === 0 ? (
                <p className="text-xs text-muted-foreground px-1 py-1">
                  No recent searches
                </p>
              ) : (
                recentSearches.map((r) => (
                  <button
                    key={r.query}
                    type="button"
                    className="w-full flex items-center gap-2 font-normal text-sm h-8 px-2 text-left rounded-md hover:bg-muted"
                    onClick={() => handleSearch(r.query)}
                    title={`${r.times_run} run${r.times_run === 1 ? "" : "s"} — click to search again`}
                  >
                    <History className="h-3 w-3 flex-shrink-0 text-muted-foreground" />
                    <span className="truncate text-xs">{r.query}</span>
                  </button>
                ))
              )}
            </div>
          </div>

          <div className="space-y-1">
            <div className="flex items-center justify-between px-1">
              <p className="text-xs font-medium text-muted-foreground">
                Saved searches
              </p>
            </div>
            <div className="max-h-56 overflow-y-auto space-y-1 pr-1">
              {savedSearchesError && (
                <p className="text-xs text-destructive px-1 py-1">
                  {savedSearchesError}
                </p>
              )}
              {!savedSearchesError && savedSearches.length === 0 ? (
                <p className="text-xs text-muted-foreground px-1 py-1">
                  No saved searches
                </p>
              ) : (
                savedSearches.map((s) => (
                  <div
                    key={s.id}
                    className="group flex items-center gap-1"
                  >
                    <button
                      type="button"
                      className="flex-1 justify-start gap-2 font-normal text-sm h-8 px-2 text-left rounded-md hover:bg-muted"
                      onClick={() => handleRunSavedSearch(s)}
                      title={s.query}
                    >
                      <span className="truncate text-xs">{s.query}</span>
                    </button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6 flex-shrink-0 opacity-0 group-hover:opacity-100"
                      onClick={() => handleDeleteSavedSearch(s.id)}
                      aria-label={`Delete saved search "${s.query}"`}
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      }
      user={{ name: userName ?? "Staff", role: role ?? "Staff" }}
      onSettings={() => setSettingsOpen(true)}
      onSignOut={handleLogout}
      onAsk={handleSearch}
    >
      <div className="flex h-full flex-col">
        <main ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto">
          <div className="max-w-3xl mx-auto px-4 py-6 pb-24">
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
                <div key={turn.id} id={`turn-${turn.id}`} className="relative group">
                  <ChatMessage
                    turn={turn}
                    onRegenerate={() => handleRegenerateTurn(turn.id, turn.query)}
                    isRegenerating={regeneratingId === turn.id}
                  />
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
                  {showSuggestions &&
                    turn.response.related_questions.length > 0 && (
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
              <StreamingPreview
                stage={stage}
                facts={streamFacts}
                sentences={streamSentences}
              />
            </div>
          )}
        </div>
      </main>

      <div className="border-t border-border flex-shrink-0 bg-background">
        <div className="max-w-3xl mx-auto px-4 py-4">
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
            {!showSuggestions && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setShowSuggestions(true)}
                className="text-xs text-muted-foreground"
              >
                <Sparkles className="h-3.5 w-3.5 mr-1.5" />
                Show suggestions
              </Button>
            )}
            <p className="text-xs text-muted-foreground ml-auto">
              Responses are sourced verbatim from internal documents.
            </p>
          </div>
          <div className="max-w-3xl mx-auto mb-2 flex items-center gap-2">
            <span className="shrink-0 text-xs text-muted-foreground">
              Case context:
            </span>
            <Select
              value={selectedCaseId != null ? String(selectedCaseId) : "none"}
              onValueChange={(v) =>
                setSelectedCaseId(v && v !== "none" ? Number(v) : null)
              }
              disabled={cases.length === 0}
            >
              <SelectTrigger className="h-8 w-64 text-xs">
                <SelectValue
                  placeholder={
                    casesError
                      ? "Cases unavailable"
                      : "Select a case for fact answers…"
                  }
                />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">No case (document search)</SelectItem>
                {cases.map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>
                    {c.case_number} — {c.client_name ?? `Client ${c.client_id}`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="max-w-3xl mx-auto mb-2 flex items-center gap-2">
            {turns.length > 0 && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleSaveSearch}
                disabled={savingSearch}
                className="text-xs"
              >
                <Bookmark className="h-3.5 w-3.5 mr-1.5" />
                {savingSearch ? "Saving…" : "Save this search"}
              </Button>
            )}
          </div>
          <div className="max-w-3xl mx-auto mb-2">
            <SearchFilterBar
              departments={departments}
              cases={cases}
              active={filters}
              onChange={setFilters}
            />
          </div>
          <SearchBar
            onSearch={handleSearch}
            isLoading={isLoading}
            placeholder="Ask about requirements, policies, or documents..."
            prefill={prefill ?? undefined}
          />
        </div>
      </div>
      </div>
    </AppShell>

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

      <SettingsModal
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        user={{ name: userName ?? "Staff", role: role ?? "Staff" }}
        onSignOut={handleLogout}
        onSignOutAll={handleLogoutAll}
        onNewChat={() => setShowClearDialog(true)}
        onClearHistory={() => {
          clearHistory();
          setShowClearDialog(false);
          setSettingsOpen(false);
        }}
        suggestionsEnabled={showSuggestions}
        onToggleSuggestions={(next) => {
          setShowSuggestions(next);
          try {
            localStorage.setItem(
              "asto_smart_suggestions",
              next ? "1" : "0"
            );
          } catch {
            // ignore
          }
        }}
        timeoutSeconds={sessionTimeout}
        onTimeoutChange={(v) => {
          setSessionTimeout(v);
          try {
            localStorage.setItem("asto_session_timeout", String(v));
          } catch {
            // ignore
          }
        }}
      />
    </>
  );
}

