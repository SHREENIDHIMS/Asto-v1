"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  Building2,
  ChevronDown,
  Clock,
  FileText,
  FolderOpen,
  Landmark,
  Loader2,
  LogOut,
  MessageSquare,
  MessageSquarePlus,
  Settings,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import {
  clientUploadDocument,
  getClientCaseDetail,
  getClientCases,
  getClientDocumentFile,
  getClientDocuments,
  getClientMe,
  getClientProperties,
  getClientPropertyDocuments,
  openBlobInNewTab,
  searchKnowledgeBaseStream,
  SearchResponse,
  SearchStage,
  CaseDetail,
  ClientCase,
  ClientDocument,
  ClientProfile,
  ClientProperty,
} from "@/lib/api-client";
import { clearToken, decodeToken, getToken } from "@/lib/auth";
import { useChatSessions, ChatSession } from "@/hooks/use-chat-sessions";
import AppShell from "@/components/layout/AppShell";
import { NAV_GROUPS } from "@/config/navigation";
import ChatMessage from "@/components/chat/ChatMessage";
import SettingsModal from "@/components/settings/SettingsModal";
import SearchBar from "@/components/search/SearchBar";
import RelatedQuestions from "@/components/search/RelatedQuestions";
import HeroSection from "@/components/home/HeroSection";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

type View = "chat" | "documents" | "properties" | "cases" | "settings";

const VIEW_TO_NAV: Record<View, string> = {
  chat: "assistant",
  documents: "documents",
  properties: "property",
  cases: "case",
  settings: "assistant",
};

const NAV_TO_VIEW: Record<string, View> = {
  assistant: "chat",
  documents: "documents",
  property: "properties",
  case: "cases",
};

function statusTone(status: string): "default" | "success" | "warning" | "destructive" | "secondary" {
  switch (status.toLowerCase()) {
    case "submitted":
      return "secondary";
    case "under_review":
      return "warning";
    case "active":
    case "approved":
    case "done":
      return "success";
    case "rejected":
    case "closed":
      return "destructive";
    default:
      return "default";
  }
}

function statusLabel(status: string): string {
  switch (status.toLowerCase()) {
    case "under_review":
      return "Under review";
    case "in_progress":
      return "In progress";
    default:
      return status.charAt(0).toUpperCase() + status.slice(1);
  }
}

function formatMoney(value: number | null): string {
  if (value == null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

function initials(name: string | null, email: string): string {
  const src = (name ?? email).trim();
  if (!src) return "?";
  const parts = src.split(/\s+/).filter(Boolean);
  const first = parts[0]?.[0] ?? "";
  const last = parts.length > 1 ? parts[parts.length - 1][0] : "";
  return (first + last).toUpperCase();
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString();
}

// ---------------------------------------------------------------------------
// Chat view
// ---------------------------------------------------------------------------

function ChatView({
  session,
  isLoading,
  error,
  stage,
    pendingQuestion,
    pendingUrgency,
    isClient,
    onSearch,
    onAskRelated,
    onNewChat,
    regeneratingTurnId,
    onRegenerateTurn,
    showSuggestions,
}: {
  session: ChatSession | null;
  isLoading: boolean;
  error: string | null;
  stage: SearchStage | null;
  pendingQuestion: string | null;
  pendingUrgency: boolean;
  isClient: boolean;
  onSearch: (q: string, urgency?: boolean) => void;
  onAskRelated: (q: string) => void;
  onNewChat: () => void;
  regeneratingTurnId: string | null;
  onRegenerateTurn: (turnId: string, query: string) => void;
  showSuggestions: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Scroll only when a new message/response begins.
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [session?.turns.length, isLoading, pendingQuestion, regeneratingTurnId]);

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
    <div className="flex h-full flex-col">
      <main ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-6 pb-24">
          {(!session || session.turns.length === 0) && !isLoading && !error && (
            <HeroSection onSearch={onSearch} />
          )}

          {error && (
            <Alert variant="destructive" className="mt-8 mx-auto max-w-2xl">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Search failed</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {session && session.turns.length > 0 && (
            <div className="space-y-8 mt-4">
              {session.turns.map((turn) => (
                <div key={turn.id} className="relative group">
                  <ChatMessage
                    turn={turn}
                    onRegenerate={() => onRegenerateTurn(turn.id, turn.query)}
                    isRegenerating={regeneratingTurnId === turn.id}
                  />
                  {showSuggestions &&
                    turn.response.related_questions.length > 0 && (
                      <RelatedQuestions
                        questions={turn.response.related_questions}
                        onAskQuestion={onAskRelated}
                      />
                    )}
                </div>
              ))}
            </div>
          )}

          {isLoading && pendingQuestion && (
            <div className="space-y-4 mt-8">
              <div className="flex justify-end">
                <div
                  className={cn(
                    "rounded-2xl rounded-br-sm bg-muted text-foreground px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap",
                    pendingUrgency && "border-2 border-destructive"
                  )}
                >
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
                </div>
              </div>
            </div>
          )}
        </div>
      </main>

      <div className="border-t border-border flex-shrink-0 bg-background">
        <div className="max-w-3xl mx-auto px-4 py-4">
          <div className="flex items-center gap-2 mb-2">
            {session && session.turns.length > 0 && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={onNewChat}
                className="text-xs text-muted-foreground"
              >
                <MessageSquarePlus className="h-3.5 w-3.5 mr-1.5" />
                New chat
              </Button>
            )}
            {isClient && (
              <p className="text-xs text-muted-foreground ml-auto flex items-center gap-1">
                <ShieldCheck className="w-3.5 h-3.5" />
                Answers come only from your own approved documents
              </p>
            )}
          </div>
          <SearchBar
            onSearch={onSearch}
            isLoading={isLoading}
            showUrgency={true}
            placeholder="Ask about your loans, policies, or documents..."
          />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Documents view
// ---------------------------------------------------------------------------

function DocumentsView({
  token,
  documents,
  properties,
  onUploaded,
  onError,
}: {
  token: string;
  documents: ClientDocument[];
  properties: ClientProperty[];
  onUploaded: () => void;
  onError: (msg: string) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [propertyId, setPropertyId] = useState<string>("");
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setMessage(null);
    try {
      const res = await clientUploadDocument(
        file,
        token,
        propertyId ? Number(propertyId) : null
      );
      setMessage(
        `"${res.filename}" uploaded. It is queued for indexing and will appear after an admin approves it.`
      );
      setFile(null);
      setPropertyId("");
      onUploaded();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const handleView = async (doc: ClientDocument) => {
    try {
      const blob = await getClientDocumentFile(doc.id, token);
      openBlobInNewTab(blob, doc.title || `document-${doc.id}`);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to load document");
    }
  };

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-2xl font-bold flex items-center gap-2">
          <Upload className="w-6 h-6 text-primary" />
          Documents
        </h2>
        <p className="text-sm text-muted-foreground">
          Upload and view your own documents. Uploads are reviewed before they
          become searchable.
        </p>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Upload className="w-4 h-4" />
            Upload a document
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-end gap-3 flex-wrap">
            <div className="flex-1 min-w-[200px]">
              <Label className="mb-1 block text-xs text-muted-foreground">
                File (PDF, DOCX, TXT…)
              </Label>
              <Input
                type="file"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="cursor-pointer"
              />
            </div>
            {properties.length > 0 && (
              <div className="w-56">
                <Label className="mb-1 block text-xs text-muted-foreground">
                  Link to property (optional)
                </Label>
                <Select value={propertyId} onValueChange={setPropertyId}>
                  <SelectTrigger>
                    <SelectValue placeholder="No property" />
                  </SelectTrigger>
                  <SelectContent>
                    {properties.map((p) => (
                      <SelectItem key={p.id} value={String(p.id)}>
                        {p.address}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <Button
              type="button"
              onClick={handleUpload}
              disabled={!file || uploading}
            >
              {uploading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Upload className="h-4 w-4 mr-1.5" />
              )}
              Upload
            </Button>
          </div>
          {message && (
            <p className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-md px-3 py-2">
              {message}
            </p>
          )}
        </CardContent>
      </Card>

      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-muted-foreground">
          {documents.length} approved documents
        </h3>
      </div>

      {documents.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center text-sm text-muted-foreground">
            No approved documents yet.
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="divide-y divide-border">
            {documents.map((d) => (
              <div
                key={d.id}
                className="py-3 flex items-center justify-between gap-4"
              >
                <div className="min-w-0">
                  <p className="font-medium truncate flex items-center gap-2">
                    <FileText className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                    {d.title}
                  </p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {d.doc_type} · {d.department} · v{d.version}
                    {d.property_id != null && ` · property #${d.property_id}`} ·{" "}
                    {formatDate(d.created_at)}
                  </p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => handleView(d)}
                >
                  <FileText className="h-3.5 w-3.5 mr-1.5" />
                  View
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Properties view
// ---------------------------------------------------------------------------

function PropertiesView({
  token,
  properties,
  onError,
}: {
  token: string;
  properties: ClientProperty[];
  onError: (msg: string) => void;
}) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const [docs, setDocs] = useState<Record<number, ClientDocument[]>>({});
  const [loadingDocs, setLoadingDocs] = useState<number | null>(null);

  const toggle = async (propertyId: number) => {
    if (expanded === propertyId) {
      setExpanded(null);
      return;
    }
    setExpanded(propertyId);
    if (docs[propertyId] == null) {
      setLoadingDocs(propertyId);
      try {
        const res = await getClientPropertyDocuments(propertyId, token);
        setDocs((prev) => ({ ...prev, [propertyId]: res.documents }));
      } catch (err) {
        onError(
          err instanceof Error ? err.message : "Failed to load property documents"
        );
      } finally {
        setLoadingDocs(null);
      }
    }
  };

  const handleView = async (doc: ClientDocument) => {
    try {
      const blob = await getClientDocumentFile(doc.id, token);
      openBlobInNewTab(blob, doc.title || `document-${doc.id}`);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to load document");
    }
  };

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-2xl font-bold flex items-center gap-2">
          <Building2 className="w-6 h-6 text-primary" />
          My Properties
        </h2>
        <p className="text-sm text-muted-foreground">
          Your properties and their related documents.
        </p>
      </div>

      {properties.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center text-sm text-muted-foreground">
            No properties on file.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {properties.map((p) => (
            <Card key={p.id}>
              <CardHeader className="pb-2">
                <button
                  type="button"
                  onClick={() => toggle(p.id)}
                  className="w-full flex items-center justify-between gap-3 text-left"
                >
                  <CardTitle className="text-base flex items-center gap-2">
                    <Building2 className="w-4 h-4 text-muted-foreground" />
                    {p.address}
                  </CardTitle>
                  <ChevronDown
                    className={cn(
                      "w-4 h-4 text-muted-foreground transition-transform flex-shrink-0",
                      expanded === p.id && "rotate-180"
                    )}
                  />
                </button>
              </CardHeader>
              <CardContent className="text-sm space-y-2">
                <p className="text-muted-foreground">
                  {p.city}, {p.state} {p.postal_code}
                  {p.property_type && (
                    <Badge variant="outline" className="ml-2">
                      {p.property_type}
                    </Badge>
                  )}
                </p>

                {expanded === p.id && (
                  <div className="pt-2 border-t border-border">
                    {loadingDocs === p.id ? (
                      <div className="flex items-center gap-2 py-3 text-xs text-muted-foreground">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Loading documents…
                      </div>
                    ) : (docs[p.id] ?? []).length === 0 ? (
                      <p className="py-3 text-xs text-muted-foreground">
                        No approved documents linked to this property yet.
                      </p>
                    ) : (
                      <div className="divide-y divide-border">
                        {docs[p.id].map((d) => (
                          <div
                            key={d.id}
                            className="py-2 flex items-center justify-between gap-3"
                          >
                            <div className="min-w-0">
                              <p className="font-medium truncate text-sm">
                                {d.title}
                              </p>
                              <p className="text-xs text-muted-foreground">
                                {d.doc_type} · {formatDate(d.created_at)}
                              </p>
                            </div>
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              onClick={() => handleView(d)}
                            >
                              <FileText className="h-3.5 w-3.5 mr-1" />
                              View
                            </Button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cases view
// ---------------------------------------------------------------------------

function CasesView({
  token,
  cases,
  onError,
}: {
  token: string;
  cases: ClientCase[];
  onError: (msg: string) => void;
}) {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [details, setDetails] = useState<Record<number, CaseDetail>>({});
  const [loadingId, setLoadingId] = useState<number | null>(null);

  const toggleCase = async (c: ClientCase) => {
    if (expandedId === c.id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(c.id);
    if (!details[c.id]) {
      setLoadingId(c.id);
      try {
        const detail = await getClientCaseDetail(token, c.id);
        setDetails((prev) => ({ ...prev, [c.id]: detail }));
      } catch (err) {
        onError(err instanceof Error ? err.message : "Failed to load case");
      } finally {
        setLoadingId(null);
      }
    }
  };

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-2xl font-bold flex items-center gap-2">
          <Landmark className="w-6 h-6 text-primary" />
          Cases
        </h2>
        <p className="text-sm text-muted-foreground">
          Track your mortgage and application statuses in real time.
        </p>
      </div>

      {cases.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center text-sm text-muted-foreground">
            No cases on file yet.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {cases.map((c) => (
            <Card key={c.id}>
              <CardContent className="p-5">
                <button
                  type="button"
                  onClick={() => toggleCase(c)}
                  className="w-full text-left"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="font-semibold">{c.case_number}</p>
                        <Badge variant={statusTone(c.status)}>
                          {statusLabel(c.status)}
                        </Badge>
                        {c.latest_event?.created_at && (
                          <span className="text-xs text-muted-foreground">
                            Updated {formatDate(c.latest_event.created_at)}
                          </span>
                        )}
                      </div>
                      {c.property_address && (
                        <p className="text-sm text-muted-foreground mt-1 flex items-center gap-1.5">
                          <Building2 className="w-3.5 h-3.5" />
                          {c.property_address}
                          {c.property_type ? ` · ${c.property_type}` : ""}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-3 flex-shrink-0">
                      <div className="text-right">
                        <p className="text-sm text-muted-foreground">Loan amount</p>
                        <p className="font-semibold">{formatMoney(c.loan_amount)}</p>
                      </div>
                      <ChevronDown
                        className={cn(
                          "h-4 w-4 text-muted-foreground transition-transform",
                          expandedId === c.id && "rotate-180"
                        )}
                      />
                    </div>
                  </div>
                </button>

                {expandedId === c.id && (
                  <div className="mt-4 border-t border-border pt-4">
                    {loadingId === c.id ? (
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Loading timeline…
                      </div>
                    ) : (
                      <Timeline detail={details[c.id]} />
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function Timeline({ detail }: { detail: CaseDetail | undefined }) {
  if (!detail || detail.events.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No status history recorded yet.
      </p>
    );
  }
  return (
    <ol className="space-y-0">
      {detail.events.map((ev, i) => {
        const isLast = i === detail.events.length - 1;
        return (
          <li key={ev.id} className="relative pl-6 pb-4">
            {!isLast && (
              <span className="absolute left-2 top-2 bottom-0 w-px bg-border" />
            )}
            <span
              className={cn(
                "absolute left-0 top-1.5 h-3 w-3 rounded-full border-2 bg-background",
                isLast ? "border-primary" : "border-muted-foreground/40"
              )}
            />
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-medium">{statusLabel(ev.status)}</span>
                <Badge variant={statusTone(ev.status)}>{ev.status}</Badge>
                {ev.created_at && (
                  <span className="text-xs text-muted-foreground flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {formatDate(ev.created_at)}
                  </span>
                )}
              </div>
              {ev.note && (
                <p className="text-sm text-muted-foreground mt-0.5">{ev.note}</p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

// ---------------------------------------------------------------------------
// Client shell
// ---------------------------------------------------------------------------

export default function ClientPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [profile, setProfile] = useState<ClientProfile | null>(null);
  const [properties, setProperties] = useState<ClientProperty[]>([]);
  const [documents, setDocuments] = useState<ClientDocument[]>([]);
  const [cases, setCases] = useState<ClientCase[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>("chat");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [chatStage, setChatStage] = useState<SearchStage | null>(null);
  const [chatPending, setChatPending] = useState<string | null>(null);
  const [pendingUrgency, setPendingUrgency] = useState(false);
  const [regeneratingTurnId, setRegeneratingTurnId] = useState<string | null>(null);
  const [showSuggestions, setShowSuggestions] = useState<boolean>(() => {
    if (typeof window === "undefined") return true;
    return localStorage.getItem("asto_smart_suggestions") !== "0";
  });
  const [sessionTimeout, setSessionTimeout] = useState<number>(() => {
    if (typeof window === "undefined") return 0;
    const raw = localStorage.getItem("asto_session_timeout");
    return raw ? Number(raw) : 0;
  });
  const [settingsOpen, setSettingsOpen] = useState(false);

  const clientKey = token
    ? (decodeToken(token)?.client_id ?? "unknown")
    : "unknown";
  const sessions = useChatSessions(`client:${clientKey}`);

  useEffect(() => {
    const t = getToken();
    const claims = t ? decodeToken(t) : null;
    if (!t || claims?.audience !== "client") {
      router.replace("/login");
      return;
    }
    setToken(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  const loadData = useCallback(async () => {
    const t = getToken();
    if (!t) return;
    try {
      const [me, props, docsRes, casesRes] = await Promise.all([
        getClientMe(t),
        getClientProperties(t),
        getClientDocuments(t),
        getClientCases(t),
      ]);
      setProfile(me.client);
      setProperties(props.properties);
      setDocuments(docsRes.documents);
      setCases(casesRes.cases);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load portal data");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (token) loadData();
  }, [token, loadData]);

  const handleLogout = useCallback(() => {
    clearToken();
    router.push("/login");
  }, [router]);

  const handleNewChat = useCallback(() => {
    sessions.createSession();
    setView("chat");
    setChatError(null);
  }, [sessions]);

  const handleSearch = useCallback(
    async (q: string, urgency: boolean = false) => {
      if (chatLoading) return;
      const t = getToken();
      if (!t) return;
      setChatPending(q);
      setPendingUrgency(urgency);
      setChatStage(null);
      setChatLoading(true);
      setChatError(null);
      try {
        let sid = sessions.activeId;
        if (!sid) sid = sessions.createSession();
        const result: SearchResponse = await searchKnowledgeBaseStream(
          q,
          t,
          (s) => setChatStage(s),
          cases[0]?.id ?? null
        );
        sessions.appendTurn(sid, q, result, urgency);
        setChatPending(null);
        setChatStage(null);
      } catch (err) {
        setChatError(
          err instanceof Error ? err.message : "Something went wrong"
        );
        setChatPending(null);
        setChatStage(null);
      } finally {
        setPendingUrgency(false);
        setChatLoading(false);
        setRegeneratingTurnId(null);
      }
    },
    [chatLoading, sessions, cases]
  );

  const handleRegenerateTurn = useCallback(
    async (turnId: string, query: string) => {
      if (chatLoading) return;
      const t = getToken();
      if (!t) return;
      const sid = sessions.activeId;
      if (!sid) return;
      setRegeneratingTurnId(turnId);
      setChatStage(null);
      try {
        const result: SearchResponse = await searchKnowledgeBaseStream(
          query,
          t,
          (s) => setChatStage(s),
          cases[0]?.id ?? null
        );
        // Replace the assistant response in place — do not append.
        sessions.replaceTurnResponse(sid, turnId, result);
      } catch (err) {
        setChatError(
          err instanceof Error ? err.message : "Something went wrong"
        );
      } finally {
        setRegeneratingTurnId(null);
        setChatStage(null);
      }
    },
    [chatLoading, sessions, cases]
  );

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

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const headerTitle =
    view === "chat"
      ? "AI Assistant"
      : view === "documents"
        ? "Documents"
        : view === "cases"
          ? "My Case"
          : "Property";

  return (
    <>
      <AppShell
        navGroups={NAV_GROUPS.client}
        activeNavId={VIEW_TO_NAV[view]}
        onNavigate={(id) => setView(NAV_TO_VIEW[id] ?? "chat")}
      brandTitle="Asto"
      brandSubtitle="Client Portal"
      mobile="bottom-tabs"
      headerTitle={headerTitle}
      headerSubtitle="Everything about your case in one place"
      sidebarTop={
        <div className="space-y-4">
          <Button
            type="button"
            className="w-full justify-start gap-3"
            onClick={handleNewChat}
          >
            <MessageSquarePlus className="h-4 w-4" />
            New chat
          </Button>

          <div className="space-y-1">
            <div className="flex items-center justify-between px-1">
              <p className="text-xs font-medium text-muted-foreground">
                Recent chats
              </p>
              {sessions.sessions.length > 0 && (
                <button
                  type="button"
                  onClick={sessions.clearAllSessions}
                  className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
                >
                  <Trash2 className="h-3 w-3" />
                  Clear
                </button>
              )}
            </div>
            <div className="max-h-56 overflow-y-auto space-y-1 pr-1">
              {sessions.sessions.length === 0 ? (
                <p className="text-xs text-muted-foreground px-1 py-1">
                  No recent chats
                </p>
              ) : (
                sessions.sessions.map((s) => (
                  <div key={s.id} className="group flex items-center gap-1">
                    <Button
                      type="button"
                      variant={
                        sessions.activeId === s.id ? "secondary" : "ghost"
                      }
                      onClick={() => {
                        sessions.activateSession(s.id);
                        setView("chat");
                      }}
                      className="flex-1 justify-start gap-2 font-normal text-sm h-8 px-2"
                    >
                      <MessageSquare className="h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" />
                      <span className="truncate">{s.title}</span>
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 flex-shrink-0 opacity-0 group-hover:opacity-100"
                      onClick={() => sessions.deleteSession(s.id)}
                      aria-label={`Delete ${s.title}`}
                    >
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      }
      user={{
        name: profile?.full_name || profile?.email || "Client",
        email: profile?.email,
        role: "Client",
      }}
      onSettings={() => setSettingsOpen(true)}
      onSignOut={handleLogout}
    >
      {error && (
        <div className="max-w-3xl mx-auto px-4 py-4">
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Something went wrong</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        </div>
      )}

      {view === "chat" && (
        <ChatView
          session={sessions.activeSession}
          isLoading={chatLoading}
          error={chatError}
          stage={chatStage}
          pendingQuestion={chatPending}
          isClient
          onSearch={handleSearch}
          onAskRelated={handleSearch}
          onNewChat={handleNewChat}
          regeneratingTurnId={regeneratingTurnId}
          onRegenerateTurn={handleRegenerateTurn}
          pendingUrgency={pendingUrgency}
          showSuggestions={showSuggestions}
        />
      )}

      {view === "documents" && token && (
        <div className="h-full overflow-y-auto p-6">
          <DocumentsView
            token={token}
            documents={documents}
            properties={properties}
            onUploaded={loadData}
            onError={setError}
          />
        </div>
      )}

      {view === "properties" && token && (
        <div className="h-full overflow-y-auto p-6">
          <PropertiesView token={token} properties={properties} onError={setError} />
        </div>
      )}

      {view === "cases" && token && (
        <div className="h-full overflow-y-auto p-6">
          <CasesView token={token} cases={cases} onError={setError} />
        </div>
      )}
    </AppShell>

    <SettingsModal
      open={settingsOpen}
      onOpenChange={setSettingsOpen}
      user={{
        name: profile?.full_name || profile?.email,
        email: profile?.email,
        role: "Client",
      }}
      onSignOut={handleLogout}
      onSignOutAll={handleLogout}
      onNewChat={handleNewChat}
      onClearHistory={() => {
        sessions.clearAllSessions();
        setSettingsOpen(false);
      }}
      suggestionsEnabled={showSuggestions}
      onToggleSuggestions={(next) => {
        setShowSuggestions(next);
        try {
          localStorage.setItem("asto_smart_suggestions", next ? "1" : "0");
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
