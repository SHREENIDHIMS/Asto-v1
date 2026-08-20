"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  Building2,
  ChevronDown,
  ChevronRight,
  Clock,
  FileText,
  FolderOpen,
  HelpCircle,
  Home,
  Landmark,
  Loader2,
  LogOut,
  MessageSquare,
  MessageSquarePlus,
  PenLine,
  Settings,
  ShieldCheck,
  Trash2,
  Upload,
  X,
  XCircle,
} from "lucide-react";
import {
  clientUploadDocument,
  createClientConversation,
  getClientCaseDetail,
  getClientCaseChecklist,
  ChecklistItem,
  getClientCases,
  getClientConversationMessages,
  getClientConversations,
  getClientDocumentFile,
  getClientDocuments,
  getClientMe,
  getClientProperties,
  getClientPropertyDocuments,
  getClientRejectedDocuments,
  getClientSignatureRequests,
  signClientSignatureRequest,
  SignatureRequest,
  ClientRejectedDocument,
  logout,
  logoutAll,
  searchKnowledgeBaseStream,
  sendClientMessage,
  SearchResponse,
  SearchStage,
  StreamedSentence,
  StructuredFact,
  CaseDetail,
  ClientCase,
  ClientDocument,
  ClientProfile,
  ClientProperty,
  Conversation,
} from "@/lib/api-client";
import { clearToken, decodeToken, getToken, restoreSession } from "@/lib/auth";
import { useChatSessions, ChatSession } from "@/hooks/use-chat-sessions";
import { clearClientLocalState } from "@/lib/session-cleanup";
import AppShell from "@/components/layout/AppShell";
import { NAV_GROUPS } from "@/config/navigation";
import ChatMessage from "@/components/chat/ChatMessage";
import StreamingPreview from "@/components/chat/StreamingPreview";
import SettingsModal from "@/components/settings/SettingsModal";
import { FileDropzone } from "@/components/upload/FileDropzone";
import { DocumentPreviewDialog } from "@/components/documents/DocumentPreviewDialog";
import SearchBar from "@/components/search/SearchBar";
import RelatedQuestions from "@/components/search/RelatedQuestions";
import HeroSection from "@/components/home/HeroSection";
import ConversationThread from "@/components/messages/ConversationThread";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
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

type View = "home" | "chat" | "documents" | "properties" | "cases" | "messages" | "help" | "settings";

const VIEW_TO_NAV: Record<View, string> = {
  home: "home",
  chat: "assistant",
  documents: "documents",
  properties: "property",
  cases: "case",
  messages: "messages",
  help: "help",
  settings: "assistant",
};

const NAV_TO_VIEW: Record<string, View> = {
  home: "home",
  assistant: "chat",
  documents: "documents",
  property: "properties",
  case: "cases",
  messages: "messages",
  help: "help",
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
    streamFacts,
    streamSentences,
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
  streamFacts: StructuredFact[];
  streamSentences: StreamedSentence[];
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Scroll only when a new message/response begins.
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [session?.turns.length, isLoading, pendingQuestion, regeneratingTurnId]);

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
// E-sign (K5): documents awaiting the client's signature
// ---------------------------------------------------------------------------

function SignatureRequestsCard({
  token,
  onError,
}: {
  token: string;
  onError: (msg: string) => void;
}) {
  const [requests, setRequests] = useState<SignatureRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [signingId, setSigningId] = useState<number | null>(null);
  const [signName, setSignName] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getClientSignatureRequests(token);
      setRequests(res.signature_requests);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to load signatures");
    } finally {
      setLoading(false);
    }
  }, [token, onError]);

  useEffect(() => {
    load();
  }, [load]);

  const pending = requests.filter((r) => r.status === "pending");
  if (loading) {
    return (
      <Card>
        <CardContent className="p-4 flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading signature requests…
        </CardContent>
      </Card>
    );
  }
  if (pending.length === 0) {
    return null;
  }

  const handleSign = async (r: SignatureRequest) => {
    if (!signName.trim()) {
      setError("Please enter your full name to sign");
      return;
    }
    if (!consent) {
      setError("Please consent before signing");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await signClientSignatureRequest(token, r.id, signName.trim(), consent);
      setSigningId(null);
      setSignName("");
      setConsent(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to sign");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="border-primary/40">
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <PenLine className="h-4 w-4 text-primary" />
          Documents awaiting your signature
        </CardTitle>
        <CardContent className="p-0 space-y-4">
          {error && <p className="text-xs text-destructive">{error}</p>}
          {pending.map((r) => (
            <div key={r.id} className="space-y-2">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium">{r.document_title || `Document #${r.document_id ?? "—"}`}</p>
                  <p className="text-xs text-muted-foreground">
                    Case #{r.case_id} · requested{" "}
                    {r.created_at ? formatDate(r.created_at) : ""}
                  </p>
                </div>
                <Badge variant="warning">Pending</Badge>
              </div>
              {signingId === r.id ? (
                <div className="space-y-2">
                  <Input
                    value={signName}
                    onChange={(e) => setSignName(e.target.value)}
                    placeholder="Sign as (full legal name)"
                    disabled={busy}
                  />
                  <label className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={consent}
                      onCheckedChange={(c) => setConsent(!!c)}
                    />
                    I agree this is my signature and consent to the document.
                  </label>
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      size="sm"
                      onClick={() => handleSign(r)}
                      disabled={busy}
                    >
                      {busy ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <PenLine className="h-3.5 w-3.5 mr-1.5" />
                      )}
                      Sign document
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setSigningId(null);
                        setSignName("");
                        setConsent(false);
                        setError(null);
                      }}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setSigningId(r.id)}
                >
                  <PenLine className="h-3.5 w-3.5 mr-1.5" />
                  Sign
                </Button>
              )}
            </div>
          ))}
        </CardContent>
      </CardHeader>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Documents view
// ---------------------------------------------------------------------------

function DocumentsView({
  token,
  documents,
  rejectedDocuments,
  properties,
  onUploaded,
  onError,
}: {
  token: string;
  documents: ClientDocument[];
  rejectedDocuments: ClientRejectedDocument[];
  properties: ClientProperty[];
  onUploaded: () => void;
  onError: (msg: string) => void;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [propertyId, setPropertyId] = useState<string>("");
  const [docType, setDocType] = useState<string>("");
  const [docTitle, setDocTitle] = useState<string>("");
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [uploadHint, setUploadHint] = useState<string | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number; name: string } | null>(null);
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [activeTag, setActiveTag] = useState<string | null>(null);

  useEffect(() => {
    setActiveTag(null);
  }, [documents]);

  const tagCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const d of documents) {
      for (const tag of d.tags ?? []) {
        counts.set(tag, (counts.get(tag) ?? 0) + 1);
      }
    }
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
  }, [documents]);

  const visibleDocuments = activeTag
    ? documents.filter((d) => (d.tags ?? []).includes(activeTag))
    : documents;

  const handleUpload = async () => {
    if (files.length === 0) return;
    if (!docType.trim()) {
      onError("Please select a document type");
      return;
    }
    if (!docTitle.trim()) {
      onError("Please enter a document title");
      return;
    }
    setUploading(true);
    setMessage(null);
    setProgress(null);
    try {
      let uploadedCount = 0;
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        setProgress({ done: i, total: files.length, name: file.name });
        await clientUploadDocument(
          file,
          token,
          docType.trim(),
          docTitle.trim(),
          propertyId ? Number(propertyId) : null
        );
        uploadedCount += 1;
      }
      setProgress({ done: files.length, total: files.length, name: "" });
      setMessage(
        `${uploadedCount} document${uploadedCount === 1 ? "" : "s"} uploaded. They are queued for indexing and will appear after an admin approves them.`
      );
      setFiles([]);
      setPropertyId("");
      setDocType("");
      setDocTitle("");
      setUploadHint(null);
      setShowUpload(false);
      onUploaded();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      setProgress(null);
    }
  };

  const handleView = (doc: ClientDocument) => {
    setPreviewId(doc.id);
  };

  return (
    <div className="space-y-6 max-w-3xl">
      <SignatureRequestsCard token={token} onError={onError} />

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
            <Upload className="h-4 w-4" />
            Upload a document
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {showUpload && uploadHint && (
            <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
              {uploadHint}
            </p>
          )}
          <FileDropzone
            files={files}
            onFilesChange={setFiles}
            disabled={uploading}
            accept=".pdf,.docx,.txt,.doc"
            label="Drag & drop documents here, or click to browse"
            hint="Multiple files are uploaded one at a time."
          />
          {progress && (
            <p className="text-sm text-muted-foreground">
              {progress.name
                ? `Uploading "${progress.name}" (${progress.done + 1} of ${progress.total})…`
                : `Uploading ${progress.total} file${progress.total === 1 ? "" : "s"}…`}
            </p>
          )}
          <div className="flex items-end gap-3 flex-wrap">
            <div className="w-56">
              <Label className="mb-1 block text-xs text-muted-foreground">
                Document type
              </Label>
              <Select value={docType} onValueChange={setDocType}>
                <SelectTrigger>
                  <SelectValue placeholder="Select type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="policy">Policy</SelectItem>
                  <SelectItem value="statement">Statement</SelectItem>
                  <SelectItem value="appraisal">Appraisal</SelectItem>
                  <SelectItem value="title">Title report</SelectItem>
                  <SelectItem value="tax">Tax document</SelectItem>
                  <SelectItem value="income">Income verification</SelectItem>
                  <SelectItem value="id">Identification</SelectItem>
                  <SelectItem value="other">Other</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="w-72 flex-1">
              <Label className="mb-1 block text-xs text-muted-foreground">
                Title
              </Label>
              <Input
                value={docTitle}
                onChange={(e) => setDocTitle(e.target.value)}
                placeholder="e.g. 2025 tax return"
                disabled={uploading}
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
              disabled={files.length === 0 || uploading}
            >
              {uploading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Upload className="h-4 w-4 mr-1.5" />
              )}
              Upload {files.length > 0 ? `${files.length} file${files.length === 1 ? "" : "s"}` : ""}
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
          {visibleDocuments.length} approved document
          {visibleDocuments.length === 1 ? "" : "s"}
          {activeTag ? ` tagged "${activeTag}"` : ""}
        </h3>
      </div>

      {tagCounts.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant={activeTag == null ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setActiveTag(null)}
          >
            All
          </Button>
          {tagCounts.map(([tag, count]) => (
            <Button
              key={tag}
              type="button"
              variant={activeTag === tag ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setActiveTag(activeTag === tag ? null : tag)}
              className="gap-1.5"
            >
              {tag}
              <span className="text-xs text-muted-foreground">({count})</span>
            </Button>
          ))}
        </div>
      )}

      {visibleDocuments.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center text-sm text-muted-foreground">
            {activeTag
              ? "No approved documents carry this tag yet."
              : "No approved documents yet."}
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="divide-y divide-border">
            {visibleDocuments.map((d) => (
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
                  {d.tags && d.tags.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {d.tags.map((tag) => (
                        <Badge key={tag} variant="secondary" className="text-xs font-normal">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                  )}
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

      {rejectedDocuments.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-muted-foreground">
            {rejectedDocuments.length}{" "}
            {rejectedDocuments.length === 1 ? "document needs" : "documents need"} your
            attention
          </h3>
          <p className="text-xs text-muted-foreground mt-1 mb-3">
            A corrected upload for the same document becomes a new version and
            re-enters the review queue.
          </p>
          <Card>
            <CardContent className="divide-y divide-border">
              {rejectedDocuments.map((d) => (
                <div key={d.id} className="py-3 flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="font-medium truncate flex items-center gap-2">
                      <XCircle className="w-4 h-4 text-red-600 flex-shrink-0" />
                      {d.title}
                    </p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      v{d.version} · rejected{" "}
                      {d.rejected_at ? formatDate(d.rejected_at) : ""}
                    </p>
                    {d.rejection_reason && (
                      <p className="text-xs mt-1.5 text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2">
                        Reason: {d.rejection_reason}
                      </p>
                    )}
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    onClick={() => {
                      setPropertyId(String(d.property_id ?? ""));
                      setUploadHint(
                        `Uploading a corrected version of "${d.title}" — the previous version was rejected: ${d.rejection_reason ?? "no reason given"}`
                      );
                      setShowUpload(true);
                    }}
                  >
                    <Upload className="h-3.5 w-3.5 mr-1.5" />
                    Upload corrected version
                  </Button>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      )}

      <DocumentPreviewDialog
        open={previewId != null}
        onOpenChange={(open) => !open && setPreviewId(null)}
        items={visibleDocuments.map((d) => ({ id: d.id, title: d.title }))}
        initialId={previewId ?? visibleDocuments[0]?.id ?? 0}
        fetchBlob={(id) => getClientDocumentFile(id, token)}
        loadingLabel="Loading approved document…"
      />
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
  const [previewId, setPreviewId] = useState<number | null>(null);

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

  const handleView = (doc: ClientDocument) => {
    setPreviewId(doc.id);
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

      <DocumentPreviewDialog
        open={previewId != null}
        onOpenChange={(open) => !open && setPreviewId(null)}
        items={Object.values(docs)
          .flat()
          .map((d) => ({ id: d.id, title: d.title }))}
        initialId={previewId ?? 0}
        fetchBlob={(id) => getClientDocumentFile(id, token)}
        loadingLabel="Loading approved document…"
      />
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
  const [checklists, setChecklists] = useState<Record<number, ChecklistItem[]>>({});
  const [loadingId, setLoadingId] = useState<number | null>(null);

  const toggleCase = async (c: ClientCase) => {
    if (expandedId === c.id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(c.id);
    if (!details[c.id] || !checklists[c.id]) {
      setLoadingId(c.id);
      try {
        const [detail, checklist] = await Promise.all([
          getClientCaseDetail(token, c.id),
          getClientCaseChecklist(token, c.id),
        ]);
        setDetails((prev) => ({ ...prev, [c.id]: detail }));
        setChecklists((prev) => ({ ...prev, [c.id]: checklist.checklist }));
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
                  <div className="mt-4 border-t border-border pt-4 space-y-6">
                    {loadingId === c.id ? (
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Loading case details…
                      </div>
                    ) : (
                      <>
                        <Checklist items={checklists[c.id]} />
                        <Timeline detail={details[c.id]} />
                      </>
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

function Checklist({ items }: { items: ChecklistItem[] | undefined }) {
  if (!items || items.length === 0 || (items.length === 1 && !items[0].item)) {
    return null;
  }
  const doneCount = items.filter((i) => i.satisfied).length;
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-sm font-medium">Document checklist</h4>
        <span className="text-xs text-muted-foreground">
          {doneCount} of {items.length} complete
        </span>
      </div>
      <ul className="space-y-1.5">
        {items.map((item, i) => (
          <li key={i} className="flex items-center gap-2 text-sm">
            <span
              className={cn(
                "flex h-4 w-4 items-center justify-center rounded-full border text-[10px]",
                item.satisfied
                  ? "bg-green-100 border-green-500 text-green-700"
                  : "border-muted-foreground/40 text-transparent"
              )}
            >
              ✓
            </span>
            <span
              className={cn(
                item.satisfied
                  ? "text-muted-foreground line-through"
                  : "text-foreground"
              )}
            >
              {item.item}
            </span>
          </li>
        ))}
      </ul>
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
// Home view (Phase F5 — overview cards)
// ---------------------------------------------------------------------------

function HomeView({
  profile,
  properties,
  documents,
  cases,
  onNavigate,
}: {
  profile: ClientProfile | null;
  properties: ClientProperty[];
  documents: ClientDocument[];
  cases: ClientCase[];
  onNavigate: (view: View) => void;
}) {
  const activeCase = cases[0] ?? null;

  const cards = [
    {
      label: "Active case",
      value: activeCase ? activeCase.case_number : "No case",
      hint: activeCase ? statusLabel(activeCase.status) : "No case on file yet",
      icon: <Landmark className="h-5 w-5" />,
      onClick: () => onNavigate("cases"),
    },
    {
      label: "Properties",
      value: properties.length.toLocaleString(),
      hint: properties[0] ? `${properties[0].city}, ${properties[0].state}` : "No properties",
      icon: <Building2 className="h-5 w-5" />,
      onClick: () => onNavigate("properties"),
    },
    {
      label: "Documents",
      value: documents.length.toLocaleString(),
      hint: "Your approved documents",
      icon: <FolderOpen className="h-5 w-5" />,
      onClick: () => onNavigate("documents"),
    },
  ];

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-2xl font-bold">
          Welcome{profile?.full_name ? `, ${profile.full_name.split(" ")[0]}` : ""}!
        </h2>
        <p className="text-sm text-muted-foreground">
          Everything about your mortgage in one place.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        {cards.map((card) => (
          <button
            key={card.label}
            type="button"
            onClick={card.onClick}
            className="text-left rounded-xl border border-border bg-card p-4 hover:border-primary/50 transition-colors"
          >
            <div className="flex items-center gap-2 text-muted-foreground mb-2">
              {card.icon}
              <span className="text-sm font-medium">{card.label}</span>
            </div>
            <p className="text-lg font-bold truncate">{card.value}</p>
            <p className="text-xs text-muted-foreground truncate mt-0.5">{card.hint}</p>
          </button>
        ))}
      </div>

      {activeCase?.latest_event && (
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-sm flex items-center gap-2">
              <Clock className="h-4 w-4 text-muted-foreground" />
              Latest update
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-medium">
                {statusLabel(activeCase.latest_event.status)}
              </span>
              <Badge variant={statusTone(activeCase.latest_event.status)}>
                {activeCase.latest_event.status}
              </Badge>
              {activeCase.latest_event.created_at && (
                <span className="text-xs text-muted-foreground">
                  {formatDate(activeCase.latest_event.created_at)}
                </span>
              )}
            </div>
            {activeCase.latest_event.note && (
              <p className="text-sm text-muted-foreground mt-1">
                {activeCase.latest_event.note}
              </p>
            )}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="mt-2"
              onClick={() => onNavigate("cases")}
            >
              View timeline
              <ChevronRight className="h-3.5 w-3.5 ml-1" />
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Help view (Phase F5 — static content)
// ---------------------------------------------------------------------------

const HELP_SECTIONS = [
  {
    title: "Ask Asto for answers",
    body: "Use the AI Assistant to ask questions about your loan, policy, or the documents we've shared. Answers come with sources you can verify.",
  },
  {
    title: "Your documents",
    body: "Approved documents live under Documents. Select one to view or download it. Uploads from you enter a review queue before they're shown here.",
  },
  {
    title: "Your property",
    body: "The Property tab shows the address and type on file. Contact us if any details are wrong.",
  },
  {
    title: "Your case timeline",
    body: "The Case tab shows your case number, loan amount, and a timeline of status events as your application moves through review.",
  },
  {
    title: "Privacy & security",
    body: "Every search and action is recorded in an audit trail. We never share your information outside your authorized team.",
  },
  {
    title: "Need human help?",
    body: "Reach your loan team directly from this portal — your assigned staff can see your case and notes.",
  },
];

function HelpView() {
  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-2xl font-bold flex items-center gap-2">
          <HelpCircle className="w-6 h-6 text-primary" />
          Help
        </h2>
        <p className="text-sm text-muted-foreground">
          How to get the most out of your Asto portal.
        </p>
      </div>

      <div className="space-y-3">
        {HELP_SECTIONS.map((section) => (
          <Card key={section.title}>
            <CardHeader className="pb-1">
              <CardTitle className="text-sm">{section.title}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">{section.body}</p>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Messages view (Phase F6 — client <-> staff conversations)
// ---------------------------------------------------------------------------

function MessagesView({
  token,
  cases,
  onError,
}: {
  token: string;
  cases: ClientCase[];
  onError: (msg: string) => void;
}) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [subject, setSubject] = useState("");
  const [caseId, setCaseId] = useState("");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await getClientConversations(token);
      setConversations(res.conversations);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to load conversations");
    } finally {
      setLoading(false);
    }
  }, [token, onError]);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async () => {
    if (!subject.trim() || creating) return;
    setCreating(true);
    try {
      await createClientConversation(token, {
        subject: subject.trim(),
        case_id: caseId ? Number(caseId) : null,
      });
      setSubject("");
      setCaseId("");
      setShowCreate(false);
      await load();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to create conversation");
    } finally {
      setCreating(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Message your loan team. They can see your case and documents.
        </p>
        <Button type="button" size="sm" onClick={() => setShowCreate((v) => !v)}>
          <MessageSquarePlus className="h-4 w-4 mr-1.5" />
          New conversation
        </Button>
      </div>

      {showCreate && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">New conversation</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="msg-subject">Subject</Label>
              <Input
                id="msg-subject"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder="e.g. Question about my application"
              />
            </div>
            {cases.length > 0 && (
              <div className="space-y-1">
                <Label htmlFor="msg-case">Related case (optional)</Label>
                <Select value={caseId} onValueChange={setCaseId}>
                  <SelectTrigger id="msg-case">
                    <SelectValue placeholder="No case" />
                  </SelectTrigger>
                  <SelectContent>
                    {cases.map((c) => (
                      <SelectItem key={c.id} value={String(c.id)}>
                        {c.case_number}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <Button
              type="button"
              onClick={handleCreate}
              disabled={!subject.trim() || creating}
            >
              {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : "Start conversation"}
            </Button>
          </CardContent>
        </Card>
      )}

      <ConversationThread
        conversations={conversations}
        selfSenderType="client"
        loadMessages={async (id) => (await getClientConversationMessages(token, id)).messages}
        sendMessage={async (id, body) => {
          await sendClientMessage(token, id, body);
        }}
        emptyLabel="No conversations yet — start one above."
      />
    </div>
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
  const [rejectedDocuments, setRejectedDocuments] = useState<ClientRejectedDocument[]>([]);
  const [cases, setCases] = useState<ClientCase[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>("home");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [chatStage, setChatStage] = useState<SearchStage | null>(null);
  const [chatPending, setChatPending] = useState<string | null>(null);
  const [chatStreamFacts, setChatStreamFacts] = useState<StructuredFact[]>([]);
  const [chatStreamSentences, setChatStreamSentences] = useState<StreamedSentence[]>([]);
  const [pendingUrgency, setPendingUrgency] = useState(false);
  const [regeneratingTurnId, setRegeneratingTurnId] = useState<string | null>(null);
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
  const [settingsOpen, setSettingsOpen] = useState(false);

  const clientKey = token
    ? (decodeToken(token)?.client_id ?? "unknown")
    : "unknown";
  const sessions = useChatSessions(`client:${clientKey}`);

  useEffect(() => {
    let mounted = true;
    restoreSession().then((t) => {
      if (!mounted) return;
      const claims = t ? decodeToken(t) : null;
      if (!t || claims?.audience !== "client") {
        router.replace("/login");
        return;
      }
      setToken(t);
    });
    return () => {
      mounted = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  const loadData = useCallback(async () => {
    const t = getToken();
    if (!t) return;
    try {
      const [me, props, docsRes, casesRes, rejectedRes] = await Promise.all([
        getClientMe(t),
        getClientProperties(t),
        getClientDocuments(t),
        getClientCases(t),
        getClientRejectedDocuments(t),
      ]);
      setProfile(me.client);
      setProperties(props.properties);
      setDocuments(docsRes.documents);
      setCases(casesRes.cases);
      setRejectedDocuments(rejectedRes.documents);
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
    logout();
    clearToken();
    clearClientLocalState();
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
      setChatStreamFacts([]);
      setChatStreamSentences([]);
      setChatLoading(true);
      setChatError(null);
      try {
        let sid = sessions.activeId;
        if (!sid) sid = sessions.createSession();
        const result: SearchResponse = await searchKnowledgeBaseStream(
          q,
          t,
          {
            onStage: (s) => setChatStage(s),
            onFact: (f) => setChatStreamFacts((prev) => [...prev, f]),
            onSentence: (s) => setChatStreamSentences((prev) => [...prev, s]),
          }
        );
        sessions.appendTurn(sid, q, result, urgency);
        setChatPending(null);
        setChatStage(null);
        setChatStreamFacts([]);
        setChatStreamSentences([]);
      } catch (err) {
        setChatError(
          err instanceof Error ? err.message : "Something went wrong"
        );
        setChatPending(null);
        setChatStage(null);
        setChatStreamFacts([]);
        setChatStreamSentences([]);
      } finally {
        setPendingUrgency(false);
        setChatLoading(false);
        setRegeneratingTurnId(null);
      }
    },
    [chatLoading, sessions]
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
      setChatStreamFacts([]);
      setChatStreamSentences([]);
      try {
        const result: SearchResponse = await searchKnowledgeBaseStream(
          query,
          t,
          {
            onStage: (s) => setChatStage(s),
            onFact: (f) => setChatStreamFacts((prev) => [...prev, f]),
            onSentence: (s) => setChatStreamSentences((prev) => [...prev, s]),
          }
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
        setChatStreamFacts([]);
        setChatStreamSentences([]);
      }
    },
    [chatLoading, sessions]
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
    view === "home"
      ? "Home"
      : view === "chat"
        ? "AI Assistant"
        : view === "documents"
          ? "Documents"
          : view === "cases"
            ? "My Case"
            : view === "messages"
              ? "Messages"
              : view === "help"
                ? "Help"
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

      {view === "home" && (
        <div className="h-full overflow-y-auto p-6">
          <HomeView
            profile={profile}
            properties={properties}
            documents={documents}
            cases={cases}
            onNavigate={setView}
          />
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
          streamFacts={chatStreamFacts}
          streamSentences={chatStreamSentences}
        />
      )}

      {view === "documents" && token && (
        <div className="h-full overflow-y-auto p-6">
          <DocumentsView
            token={token}
            documents={documents}
            rejectedDocuments={rejectedDocuments}
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

      {view === "messages" && token && (
        <div className="h-full overflow-y-auto p-6">
          <MessagesView token={token} cases={cases} onError={setError} />
        </div>
      )}

      {view === "help" && (
        <div className="h-full overflow-y-auto p-6">
          <HelpView />
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
      clientProfile={profile}
      onProfileChange={setProfile}
      onSignOut={handleLogout}
      onSignOutAll={handleLogoutAll}
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
