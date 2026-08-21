"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Download,
  FileText,
  GitCompare,
  History,
  KeyRound,
  Layers,
  Loader2,
  MessageSquare,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  ShieldAlert,
   Sparkles,
   Trash2,
   Upload,
  UserPlus,
  Users,
  X,
  XCircle,
} from "lucide-react";
import {
  listPendingDocuments,
  approveDocument,
  bulkApproveDocuments,
  bulkRejectDocuments,
  logout,
  logoutAll,
  rejectDocument,
  getDocumentHistory,
  updateDocumentMetadata,
  listAllDocuments,
  uploadDocument,
  listUsers,
  createUser,
  listClients,
  createClient,
  assignStaffToClient,
  listUserSessions,
  revokeUserSessions,
  listClientSessions,
  revokeClientSessions,
  ActiveSession,
   getKnowledgeGaps,
   getAnalyticsSummary,
   getDocumentPopularity,
   DocumentPopularityEntry,
   getAdminSummary,
   getSystemHealth,
   SystemHealth,
   getFeatureFlags,
   setFeatureFlag,
   FeatureFlag,
   getDocumentChunks,
   listAllSops,
   getGovernance,
   updateGovernance,
   listSopAccessRequests,
   reviewSopAccessRequest,
   getAdminAudit,
   exportAuditLogCsv,
   AnalyticsSummary,
   AdminSummary,
   DocumentChunk,
   Sop,
   GovernanceData,
   GovernanceUpdateInput,
   SopAccessRequest,
   AuditEntry,
   getDocumentFile,
   getDocumentVersions,
   updateDocumentTags,
   getAdminTags,
   ApprovalDocument,
   ApprovalHistoryEntry,
   DocumentVersion,
   AdminDocument,
   AdminTag,
    AdminUser,
    AdminClient,
    KnowledgeGap,
    listPinnedAnswers,
    patchPinnedAnswer,
    deletePinnedAnswer,
    PinnedAnswer,
    listReviewOverdue,
    setDocumentReviewDue,
    ReviewOverdueDocument,
  } from "@/lib/api-client";
import { clearToken, decodeToken, getToken, isAdminRole, restoreSession } from "@/lib/auth";
import { clearClientLocalState } from "@/lib/session-cleanup";
import AppShell from "@/components/layout/AppShell";
import { NAV_GROUPS } from "@/config/navigation";
import SettingsModal from "@/components/settings/SettingsModal";
import { OnboardingTour } from "@/components/onboarding/OnboardingTour";
import { FileDropzone } from "@/components/upload/FileDropzone";
import { DocumentPreviewDialog } from "@/components/documents/DocumentPreviewDialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DashboardSkeleton } from "@/components/ui/dashboard-skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

function statusBadge(status: string) {
  switch (status) {
    case "approved":
      return <Badge className="bg-green-100 text-green-800 border-green-200">{status}</Badge>;
    case "pending":
      return <Badge className="bg-yellow-100 text-yellow-800 border-yellow-200">{status}</Badge>;
    case "rejected":
      return <Badge variant="destructive">{status}</Badge>;
    default:
      return <Badge variant="outline">{status}</Badge>;
  }
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

// ---------------------------------------------------------------------------
// Approvals queue tab
// ---------------------------------------------------------------------------

function ApprovalsTab({ token }: { token: string }) {
  const [documents, setDocuments] = useState<ApprovalDocument[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [historyDoc, setHistoryDoc] = useState<ApprovalDocument | null>(null);
  const [history, setHistory] = useState<ApprovalHistoryEntry[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [versionsDoc, setVersionsDoc] = useState<ApprovalDocument | null>(null);
  const [versions, setVersions] = useState<DocumentVersion[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [compareIds, setCompareIds] = useState<[number, number] | null>(null);
  const [editDoc, setEditDoc] = useState<ApprovalDocument | null>(null);
  const [rejectDoc, setRejectDoc] = useState<ApprovalDocument | null>(null);
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [bulkBusy, setBulkBusy] = useState<"approve" | "reject" | null>(null);
  const [bulkReject, setBulkReject] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await listPendingDocuments(token);
      setDocuments(res.documents);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load queue");
    } finally {
      setIsLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const handleApprove = async (doc: ApprovalDocument) => {
    setBusyId(doc.id);
    setError(null);
    let publishAnyway = false;
    if (doc.pii_flagged) {
      if (
        !window.confirm(
          `This document is flagged as containing PII. Approve and publish anyway?`
        )
      ) {
        setBusyId(null);
        return;
      }
      publishAnyway = true;
    }
    // Optimistic update (N7): remove the doc from the pending queue
    // immediately, then reconcile with the server.
    const previous = documents;
    setDocuments((prev) => prev.filter((d) => d.id !== doc.id));
    try {
      await approveDocument(doc.id, token, publishAnyway);
      await load();
    } catch (err) {
      setDocuments(previous);
      setError(err instanceof Error ? err.message : "Decision failed");
    } finally {
      setBusyId(null);
    }
  };

  const openHistory = async (doc: ApprovalDocument) => {
    setHistoryDoc(doc);
    setHistoryLoading(true);
    setHistory([]);
    try {
      const res = await getDocumentHistory(doc.id, token);
      setHistory(res.history);
    } catch {
      setHistory([]);
    } finally {
      setHistoryLoading(false);
    }
  };

  const openVersions = async (doc: ApprovalDocument) => {
    setVersionsDoc(doc);
    setVersionsLoading(true);
    setVersions([]);
    setCompareIds(null);
    try {
      const res = await getDocumentVersions(doc.id, token);
      setVersions(res.versions);
    } catch {
      setVersions([]);
    } finally {
      setVersionsLoading(false);
    }
  };

  const toggleSelected = (id: number) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const toggleAll = () => {
    setSelectedIds((prev) => (prev.length === documents.length ? [] : documents.map((d) => d.id)));
  };

  const handleBulkApprove = async () => {
    if (selectedIds.length === 0) return;
    const flagged = documents.filter(
      (d) => selectedIds.includes(d.id) && d.pii_flagged
    );
    let publishAnyway = false;
    if (flagged.length > 0) {
      if (
        !window.confirm(
          `${flagged.length} selected document(s) are flagged as containing PII. ` +
            "Approve and publish them anyway?"
        )
      ) {
        return;
      }
      publishAnyway = true;
    }
    setBulkBusy("approve");
    setError(null);
    try {
      await bulkApproveDocuments(selectedIds, token, publishAnyway);
      setSelectedIds([]);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bulk approval failed");
    } finally {
      setBulkBusy(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Documents uploaded via ingestion wait here until approved. Pending docs
          are not searchable. You can edit metadata before approving.
        </p>
        <Button type="button" variant="outline" size="sm" onClick={load}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
          Refresh
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Action failed</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
          <div className="mt-2 flex gap-2">
            <Button type="button" variant="outline" size="sm" onClick={load}>
              <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
              Retry
            </Button>
          </div>
        </Alert>
      )}

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : documents.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center">
            <CheckCircle2 className="h-8 w-8 mx-auto mb-2 text-green-600" />
            <p className="font-medium">All caught up</p>
            <p className="text-sm text-muted-foreground">
              No documents awaiting approval.
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="flex items-center justify-between gap-3 border border-border rounded-lg p-3">
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                className="h-4 w-4"
                checked={documents.length > 0 && selectedIds.length === documents.length}
                onChange={toggleAll}
              />
              Select all ({documents.length})
            </label>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">
                {selectedIds.length} selected
              </span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={selectedIds.length === 0 || bulkBusy != null}
                onClick={handleBulkApprove}
              >
                {bulkBusy === "approve" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <CheckCircle2 className="h-3.5 w-3.5 mr-1.5" />
                )}
                Approve selected
              </Button>
              <Button
                type="button"
                variant="destructive"
                size="sm"
                disabled={selectedIds.length === 0 || bulkBusy != null}
                onClick={() => setBulkReject(true)}
              >
                <XCircle className="h-3.5 w-3.5 mr-1.5" />
                Reject selected
              </Button>
            </div>
          </div>

          {documents.map((doc) => (
          <Card key={doc.id}>
            <CardContent className="p-5">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                  <input
                    type="checkbox"
                    className="h-4 w-4 flex-shrink-0"
                    checked={selectedIds.includes(doc.id)}
                    onChange={() => toggleSelected(doc.id)}
                  />
                  <Clock className="w-4 h-4 text-yellow-600" />
                  <p className="font-medium truncate">{doc.title}</p>
                  {doc.pii_flagged && (
                    <ShieldAlert className="w-4 h-4 text-amber-600" aria-label="Contains flagged PII" />
                  )}
                </div>
                  <p className="text-xs text-muted-foreground mb-2">
                    {doc.doc_type} · {doc.department}
                    {doc.client_id != null && ` · client #${doc.client_id}`} · v{doc.version}
                    {doc.uploaded_by_email && ` · by ${doc.uploaded_by_email}`}
                    {" · "}uploaded {formatDate(doc.created_at)}
                  </p>
                  <p className="text-xs text-muted-foreground truncate font-mono">
                    {doc.source_path}
                  </p>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setPreviewId(doc.id)}
                  >
                    <FileText className="h-3.5 w-3.5 mr-1.5" />
                    View
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setEditDoc(doc)}
                  >
                    <Pencil className="h-3.5 w-3.5 mr-1.5" />
                    Edit
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => openHistory(doc)}
                  >
                    <History className="h-3.5 w-3.5 mr-1.5" />
                    History
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => openVersions(doc)}
                  >
                    <Layers className="h-3.5 w-3.5 mr-1.5" />
                    Versions
                  </Button>
                  <Button
                    type="button"
                    variant="destructive"
                    size="sm"
                    disabled={busyId === doc.id}
                    onClick={() => setRejectDoc(doc)}
                  >
                    <XCircle className="h-3.5 w-3.5 mr-1.5" />
                    Reject
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    disabled={busyId === doc.id}
                    onClick={() => handleApprove(doc)}
                  >
                    {busyId === doc.id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <CheckCircle2 className="h-3.5 w-3.5 mr-1.5" />
                    )}
                    Approve
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
          ))}
        </>
      )}

      <Dialog open={historyDoc != null} onOpenChange={(open) => !open && setHistoryDoc(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Approval History</DialogTitle>
            <DialogDescription>
              {historyDoc?.title}
            </DialogDescription>
          </DialogHeader>
          {historyLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : history.length === 0 ? (
            <p className="text-sm text-muted-foreground">No history recorded.</p>
          ) : (
            <div className="space-y-3 max-h-80 overflow-y-auto">
              {history.map((entry) => (
                <div key={entry.id} className="border border-border rounded-lg p-3 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">
                      {entry.from_status} → {entry.to_status}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {formatDate(entry.created_at)}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    by {entry.reviewed_by_email ?? "unknown"}
                  </p>
                  {entry.reason && (
                    <p className="text-xs mt-1">{entry.reason}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={versionsDoc != null} onOpenChange={(open) => !open && setVersionsDoc(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Versions</DialogTitle>
            <DialogDescription>
              {versionsDoc?.title} — every version of this document family
            </DialogDescription>
          </DialogHeader>
          {versionsLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : versions.length === 0 ? (
            <p className="text-sm text-muted-foreground">No versions found.</p>
          ) : (
            <div className="space-y-2 max-h-96 overflow-y-auto">
              {versions.map((v) => (
                <div key={v.id} className="border border-border rounded-lg p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="font-mono text-xs text-muted-foreground">
                        v{v.version}
                      </span>
                      {statusBadge(v.approval_status)}
                      {v.is_active && (
                        <Badge variant="outline" className="text-xs">
                          active
                        </Badge>
                      )}
                    </div>
                    <span className="text-xs text-muted-foreground flex-shrink-0">
                      {formatDate(v.created_at)}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    by {v.uploaded_by_email ?? "unknown"} · {v.doc_type} ·{" "}
                    {v.department}
                  </p>
                  <div className="mt-2 flex items-center gap-2">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={async () => {
                        const blob = await getDocumentFile(v.id, token, v.version);
                        const url = URL.createObjectURL(blob);
                        window.open(url, "_blank");
                      }}
                    >
                      <FileText className="h-3.5 w-3.5 mr-1.5" />
                      View v{v.version}
                    </Button>
                    {versions.length > 1 && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          const other = versions.find(
                            (x) =>
                              x.version !== v.version &&
                              (x.version === v.version - 1 || x.version === v.version + 1)
                          );
                          const base = other ?? versions[0];
                          setCompareIds(v.version < base.version ? [v.id, base.id] : [base.id, v.id]);
                        }}
                      >
                        <GitCompare className="h-3.5 w-3.5 mr-1.5" />
                        Compare
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
          {compareIds && (
            <VersionDiff
              leftId={compareIds[0]}
              rightId={compareIds[1]}
              token={token}
              onClose={() => setCompareIds(null)}
            />
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={editDoc != null} onOpenChange={(open) => !open && setEditDoc(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit document metadata</DialogTitle>
            <DialogDescription>
              {editDoc?.title} — metadata only, the file is not replaced.
            </DialogDescription>
          </DialogHeader>
          {editDoc && <EditMetadataForm
            doc={editDoc}
            token={token}
            onDone={() => {
              setEditDoc(null);
              load();
            }}
            onError={setError}
          />}
        </DialogContent>
      </Dialog>

      <Dialog open={rejectDoc != null} onOpenChange={(open) => !open && setRejectDoc(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject document</DialogTitle>
            <DialogDescription>
              {rejectDoc?.title} — a reason is required and is shared with the uploader.
            </DialogDescription>
          </DialogHeader>
          {rejectDoc && <RejectForm
            doc={rejectDoc}
            token={token}
            onDone={() => {
              setRejectDoc(null);
              load();
            }}
            onError={setError}
          />}
        </DialogContent>
      </Dialog>

      <Dialog open={bulkReject} onOpenChange={(open) => !open && setBulkReject(false)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject {selectedIds.length} selected documents</DialogTitle>
            <DialogDescription>
              A reason is required and is shared with each uploader.
            </DialogDescription>
          </DialogHeader>
          <BulkRejectForm
            count={selectedIds.length}
            onCancel={() => setBulkReject(false)}
            onDone={async (reason) => {
              setBulkBusy("reject");
              setError(null);
              try {
                await bulkRejectDocuments(selectedIds, token, reason.trim());
                setSelectedIds([]);
                setBulkReject(false);
                await load();
              } catch (err) {
                setError(err instanceof Error ? err.message : "Bulk rejection failed");
              } finally {
                setBulkBusy(null);
              }
            }}
            onError={setError}
          />
        </DialogContent>
      </Dialog>

      <DocumentPreviewDialog
        open={previewId != null}
        onOpenChange={(open) => !open && setPreviewId(null)}
        items={documents.map((d) => ({ id: d.id, title: d.title }))}
        initialId={previewId ?? documents[0]?.id ?? 0}
        fetchBlob={(id) => getDocumentFile(id, token)}
        loadingLabel="Loading pending document…"
      />
    </div>
  );
}

function VersionDiff({
  leftId,
  rightId,
  token,
  onClose,
}: {
  leftId: number;
  rightId: number;
  token: string;
  onClose: () => void;
}) {
  const [leftLines, setLeftLines] = useState<string[] | null>(null);
  const [rightLines, setRightLines] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setError(null);
      try {
        const [a, b] = await Promise.all([
          getDocumentChunks(leftId, token),
          getDocumentChunks(rightId, token),
        ]);
        if (cancelled) return;
        setLeftLines(topChunkLines(a.chunks));
        setRightLines(topChunkLines(b.chunks));
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Compare failed");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [leftId, rightId, token]);

  if (error) {
    return (
      <div className="border border-border rounded-lg p-4 mt-4">
        <p className="text-sm text-destructive">{error}</p>
        <Button type="button" variant="ghost" size="sm" className="mt-2" onClick={onClose}>
          Close
        </Button>
      </div>
    );
  }

  if (leftLines == null || rightLines == null) {
    return (
      <div className="flex justify-center py-8 mt-4">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const rows = diffLines(leftLines, rightLines);

  return (
    <div className="mt-4 border border-border rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 bg-muted/50 border-b border-border">
        <div className="flex items-center gap-2">
          <GitCompare className="h-4 w-4 text-muted-foreground" />
          <span className="text-xs text-muted-foreground">Text diff (top chunks)</span>
        </div>
        <Button type="button" variant="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>
      <div className="grid grid-cols-2 divide-x divide-border max-h-96 overflow-auto text-xs font-mono">
        <div className="min-w-0">
          <div className="px-3 py-1.5 border-b border-border bg-muted/30 text-muted-foreground">
            v{leftId}
          </div>
          {rows.map((r, i) => (
            <div
              key={`l-${i}`}
              className={cn(
                "px-3 py-0.5 whitespace-pre-wrap break-words border-b border-border/40",
                r.status === "del" && "bg-red-50 text-red-800",
                r.status === "same" && "text-foreground"
              )}
            >
              {r.left ?? "\u00a0"}
            </div>
          ))}
        </div>
        <div className="min-w-0">
          <div className="px-3 py-1.5 border-b border-border bg-muted/30 text-muted-foreground">
            v{rightId}
          </div>
          {rows.map((r, i) => (
            <div
              key={`r-${i}`}
              className={cn(
                "px-3 py-0.5 whitespace-pre-wrap break-words border-b border-border/40",
                r.status === "ins" && "bg-green-50 text-green-800",
                r.status === "same" && "text-foreground"
              )}
            >
              {r.right ?? "\u00a0"}
            </div>
          ))}
        </div>
      </div>
      <div className="flex items-center gap-4 px-3 py-1.5 text-xs text-muted-foreground border-t border-border bg-muted/50">
        <span className="text-red-700">- {countStatus(rows, "del")} removed</span>
        <span className="text-green-700">+ {countStatus(rows, "ins")} added</span>
      </div>
    </div>
  );
}

function topChunkLines(chunks: DocumentChunk[]): string[] {
  const text = chunks
    .slice(0, 8)
    .map((c) => (c.section ? `[${c.section}] ` : "") + c.content)
    .join("\n");
  return text.split("\n").map((line) => line.trimEnd());
}

type DiffRow = { status: "same" | "ins" | "del"; left: string | null; right: string | null };

function diffLines(a: string[], b: string[]): DiffRow[] {
  const n = a.length;
  const m = b.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const rows: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      rows.push({ status: "same", left: a[i], right: b[j] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      rows.push({ status: "del", left: a[i], right: null });
      i++;
    } else {
      rows.push({ status: "ins", left: null, right: b[j] });
      j++;
    }
  }
  while (i < n) {
    rows.push({ status: "del", left: a[i], right: null });
    i++;
  }
  while (j < m) {
    rows.push({ status: "ins", left: null, right: b[j] });
    j++;
  }
  return rows;
}

function countStatus(rows: DiffRow[], status: DiffRow["status"]): number {
  return rows.filter((r) => r.status === status).length;
}

function EditMetadataForm({
  doc,
  token,
  onDone,
  onError,
}: {
  doc: ApprovalDocument;
  token: string;
  onDone: () => void;
  onError: (message: string) => void;
}) {
  const [title, setTitle] = useState(doc.title);
  const [docType, setDocType] = useState(doc.doc_type);
  const [department, setDepartment] = useState(doc.department);
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateDocumentMetadata(
        doc.id,
        {
          title: title !== doc.title ? title : undefined,
          doc_type: docType !== doc.doc_type ? docType : undefined,
          department: department !== doc.department ? department : undefined,
        },
        token
      );
      onDone();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to update document");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <Label htmlFor="em-title">Title</Label>
        <Input id="em-title" value={title} onChange={(e) => setTitle(e.target.value)} />
      </div>
      <div className="space-y-1">
        <Label htmlFor="em-type">Type</Label>
        <Input id="em-type" value={docType} onChange={(e) => setDocType(e.target.value)} />
      </div>
      <div className="space-y-1">
        <Label htmlFor="em-dept">Department</Label>
        <Input id="em-dept" value={department} onChange={(e) => setDepartment(e.target.value)} />
      </div>
      <div className="flex justify-end gap-2 pt-2">
        <Button type="button" variant="ghost" size="sm" onClick={onDone}>
          Cancel
        </Button>
        <Button
          type="button"
          size="sm"
          onClick={handleSave}
          disabled={
            saving ||
            (title === doc.title && docType === doc.doc_type && department === doc.department) ||
            !title.trim() ||
            !docType.trim() ||
            !department.trim()
          }
        >
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save changes"}
        </Button>
      </div>
    </div>
  );
}

function RejectForm({
  doc,
  token,
  onDone,
  onError,
}: {
  doc: ApprovalDocument;
  token: string;
  onDone: () => void;
  onError: (message: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [rejecting, setRejecting] = useState(false);

  const handleReject = async () => {
    setRejecting(true);
    try {
      await rejectDocument(doc.id, token, reason.trim());
      onDone();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to reject document");
    } finally {
      setRejecting(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <Label htmlFor="rj-reason">Reason *</Label>
        <Input
          id="rj-reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. Missing client signature"
        />
      </div>
      <div className="flex justify-end gap-2 pt-2">
        <Button type="button" variant="ghost" size="sm" onClick={onDone}>
          Cancel
        </Button>
        <Button
          type="button"
          variant="destructive"
          size="sm"
          onClick={handleReject}
          disabled={rejecting || !reason.trim()}
        >
          {rejecting ? <Loader2 className="h-4 w-4 animate-spin" /> : "Reject document"}
        </Button>
      </div>
    </div>
  );
}

function BulkRejectForm({
  count,
  onDone,
  onError,
  onCancel,
}: {
  count: number;
  onDone: (reason: string) => void;
  onError: (message: string) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  const [rejecting, setRejecting] = useState(false);

  const handleReject = async () => {
    if (rejecting || !reason.trim()) return;
    setRejecting(true);
    try {
      await onDone(reason);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to bulk reject documents");
    } finally {
      setRejecting(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <Label htmlFor="br-reason">Reason *</Label>
        <Input
          id="br-reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. Missing client signature"
        />
      </div>
      <div className="flex justify-end gap-2 pt-2">
        <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          type="button"
          variant="destructive"
          size="sm"
          onClick={handleReject}
          disabled={rejecting || !reason.trim()}
        >
          {rejecting ? <Loader2 className="h-4 w-4 animate-spin" /> : `Reject ${count} documents`}
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Documents tab
// ---------------------------------------------------------------------------

function TagEditorDialog({
  doc,
  token,
  onClose,
  onSaved,
}: {
  doc: AdminDocument | null;
  token: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [tags, setTags] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTags(doc?.tags ?? []);
    setInput("");
    setError(null);
  }, [doc]);

  const addTag = () => {
    const value = input.trim().toLowerCase();
    if (!value) return;
    if (tags.includes(value)) {
      setInput("");
      return;
    }
    setTags((prev) => [...prev, value]);
    setInput("");
  };

  const removeTag = (tag: string) => {
    setTags((prev) => prev.filter((t) => t !== tag));
  };

  const handleSave = async () => {
    if (!doc) return;
    setSaving(true);
    setError(null);
    try {
      await updateDocumentTags(doc.id, tags, token);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save tags");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={doc != null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit tags</DialogTitle>
          <DialogDescription>
            Tags help you filter and group documents. {doc ? `Editing "${doc.title}".` : ""}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addTag();
                }
              }}
              placeholder="Add a tag and press Enter"
              disabled={saving}
            />
            <Button type="button" variant="outline" size="sm" onClick={addTag} disabled={saving}>
              <Plus className="h-4 w-4" />
            </Button>
          </div>
          {tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {tags.map((tag) => (
                <Badge key={tag} variant="secondary" className="gap-1 pr-1">
                  {tag}
                  <button
                    type="button"
                    onClick={() => removeTag(tag)}
                    className="rounded-sm hover:bg-muted p-0.5"
                    aria-label={`Remove tag ${tag}`}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </Badge>
              ))}
            </div>
          )}
          {error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </div>
        <DialogFooter className="gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button type="button" size="sm" onClick={handleSave} disabled={saving}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save tags"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function DocumentsTab({ token }: { token: string }) {
  const [documents, setDocuments] = useState<AdminDocument[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);
  const [progress, setProgress] = useState<{ done: number; total: number; name: string } | null>(null);
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [tagOptions, setTagOptions] = useState<AdminTag[]>([]);
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [tagEditDoc, setTagEditDoc] = useState<AdminDocument | null>(null);

  const loadTags = useCallback(async () => {
    try {
      const res = await getAdminTags(token);
      setTagOptions(res.tags);
    } catch {
      // tag chips are non-critical; keep whatever we have
    }
  }, [token]);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await listAllDocuments(token, activeTag ?? undefined);
      setDocuments(res.documents);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load documents");
    } finally {
      setIsLoading(false);
    }
  }, [token, activeTag]);

  useEffect(() => {
    load();
    loadTags();
  }, [load, loadTags]);

  const handleUpload = async () => {
    if (files.length === 0) return;
    setUploading(true);
    setUploadMessage(null);
    setError(null);
    try {
      let uploadedCount = 0;
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        setProgress({ done: i, total: files.length, name: file.name });
        const res = await uploadDocument(file, token);
        uploadedCount += 1;
      }
      setProgress({ done: files.length, total: files.length, name: "" });
      setUploadMessage(
        `Uploaded ${uploadedCount} document${uploadedCount === 1 ? "" : "s"} (${(files
          .reduce((sum, f) => sum + f.size, 0) / 1024)
          .toFixed(1)} KB total). They are now pending approval and will be indexed by the batch ingestion job.`
      );
      setFiles([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      setProgress(null);
    }
  };

  const handleTagsSaved = async () => {
    setTagEditDoc(null);
    await load();
    await loadTags();
  };

  const [overdueReviews, setOverdueReviews] = useState<ReviewOverdueDocument[]>([]);
  const [overdueBusyId, setOverdueBusyId] = useState<number | null>(null);

  useEffect(() => {
    listReviewOverdue(token)
      .then((res) => setOverdueReviews(res.documents))
      .catch(() => {
        // Non-critical worklist; the summary card still shows the count.
      });
  }, [token]);

  const handleScheduleReview = async (doc: ReviewOverdueDocument) => {
    setOverdueBusyId(doc.id);
    try {
      const due = new Date();
      due.setMonth(due.getMonth() + 6);
      await setDocumentReviewDue(token, doc.id, due.toISOString().slice(0, 10));
      setOverdueReviews((prev) => prev.filter((d) => d.id !== doc.id));
    } catch {
      // keep the entry; the admin can retry
    } finally {
      setOverdueBusyId(null);
    }
  };

  return (
    <div className="space-y-6">
      {overdueReviews.length > 0 && (
        <Card className="border-amber-400 bg-amber-50 dark:bg-amber-950/30">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2 text-amber-600 dark:text-amber-400">
              <AlertCircle className="h-4 w-4" />
              {overdueReviews.length} document
              {overdueReviews.length === 1 ? "" : "s"} past their review date
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {overdueReviews.map((doc) => (
              <div key={doc.id} className="flex items-center justify-between gap-3 text-sm">
                <span className="truncate">
                  {doc.title}{" "}
                  <span className="text-xs text-muted-foreground">
                    ({doc.days_overdue} day{doc.days_overdue === 1 ? "" : "s"} overdue)
                  </span>
                </span>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={overdueBusyId === doc.id}
                  onClick={() => void handleScheduleReview(doc)}
                >
                  Schedule review (+6 mo)
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center gap-2">
            <Upload className="w-4 h-4" />
            Upload document
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground">
            Uploads are validated and written to storage/pending/. The batch
            ingestion job indexes them later; they enter the approval queue as
            pending.
          </p>
          <FileDropzone
            files={files}
            onFilesChange={setFiles}
            disabled={uploading}
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
          <div className="flex items-end gap-3">
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
          {uploadMessage && (
            <p className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-md px-3 py-2">
              {uploadMessage}
            </p>
          )}
          {error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Error</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      {tagOptions.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant={activeTag == null ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setActiveTag(null)}
          >
            All
          </Button>
          {tagOptions.map(({ tag, count }) => (
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

      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-muted-foreground">
          {documents.length} document{documents.length === 1 ? "" : "s"}
          {activeTag ? ` tagged "${activeTag}"` : ""}
        </h3>
        <Button type="button" variant="outline" size="sm" onClick={load}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
          Refresh
        </Button>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <Card>
          <CardContent className="divide-y divide-border">
            {documents.map((doc) => (
              <div key={doc.id} className="py-3 flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <FileText className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                    <p className="font-medium truncate">{doc.title}</p>
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {doc.doc_type} · {doc.department} · v{doc.version}
                    {doc.client_id != null && ` · client #${doc.client_id}`} ·{" "}
                    {formatDate(doc.created_at)}
                  </p>
                  {doc.tags && doc.tags.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {doc.tags.map((tag) => (
                        <Badge key={tag} variant="secondary" className="text-xs font-normal">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {statusBadge(doc.approval_status)}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setTagEditDoc(doc)}
                    className="text-xs"
                  >
                    <Pencil className="h-3.5 w-3.5 mr-1" />
                    Tags
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setPreviewId(doc.id)}
                    className="text-xs"
                  >
                    <FileText className="h-3.5 w-3.5 mr-1" />
                    View
                  </Button>
                </div>
              </div>
            ))}
            {documents.length === 0 && (
              <div className="py-10 text-center">
                <Upload className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
                <p className="text-sm font-medium">
                  {activeTag ? "No documents carry this tag yet." : "Your knowledge base is empty."}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Upload documents above to get started. They are validated, then processed by
                  the batch ingestion pipeline.
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <DocumentPreviewDialog
        open={previewId != null}
        onOpenChange={(open) => !open && setPreviewId(null)}
        items={documents.map((d) => ({ id: d.id, title: d.title }))}
        initialId={previewId ?? documents[0]?.id ?? 0}
        fetchBlob={(id) => getDocumentFile(id, token)}
        loadingLabel="Loading document…"
      />

      <TagEditorDialog
        doc={tagEditDoc}
        token={token}
        onClose={() => setTagEditDoc(null)}
        onSaved={handleTagsSaved}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Users tab
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// H5: session management (active sessions + kill)
// ---------------------------------------------------------------------------

function SessionsDialog({
  open,
  onOpenChange,
  title,
  subjectLabel,
  loadSessions,
  revokeSessions,
  token,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  subjectLabel: string;
  loadSessions: () => Promise<{ active_sessions: number; sessions: ActiveSession[] }>;
  revokeSessions: () => Promise<{ revoked_sessions: number }>;
  token: string;
}) {
  const [sessions, setSessions] = useState<ActiveSession[]>([]);
  const [activeCount, setActiveCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    setMessage(null);
    try {
      const res = await loadSessions();
      setSessions(res.sessions);
      setActiveCount(res.active_sessions);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load sessions");
    } finally {
      setLoading(false);
    }
  }, [loadSessions]);

  useEffect(() => {
    if (open) {
      refresh();
    } else {
      setSessions([]);
      setActiveCount(0);
      setMessage(null);
    }
  }, [open, refresh]);

  const handleRevoke = async () => {
    setRevoking(true);
    setError(null);
    setMessage(null);
    try {
      const res = await revokeSessions();
      setMessage(`${res.revoked_sessions} session(s) revoked — the user will be signed out on next refresh.`);
      setSessions([]);
      setActiveCount(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to revoke sessions");
    } finally {
      setRevoking(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {subjectLabel} — active sessions:{" "}
            <span className="font-medium">{activeCount}</span>
          </DialogDescription>
        </DialogHeader>
        {loading ? (
          <div className="flex justify-center py-6">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="space-y-3">
            {error && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertTitle>Error</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            {message && (
              <Alert>
                <CheckCircle2 className="h-4 w-4" />
                <AlertTitle>Done</AlertTitle>
                <AlertDescription>{message}</AlertDescription>
              </Alert>
            )}
            {sessions.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No active refresh sessions right now.
              </p>
            ) : (
              <div className="space-y-2 max-h-60 overflow-y-auto">
                {sessions.map((s) => (
                  <div
                    key={s.id}
                    className="flex items-center justify-between rounded-md border px-3 py-2 text-sm"
                  >
                    <span className="text-muted-foreground">
                      Session #{s.id}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      created {new Date(s.created_at).toLocaleString()}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        <DialogFooter className="flex justify-between">
          <Button type="button" variant="outline" size="sm" onClick={refresh} disabled={loading || revoking}>
            <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
            Refresh
          </Button>
          <div className="flex gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Close
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={handleRevoke}
              disabled={revoking || loading}
            >
              {revoking ? (
                <Loader2 className="h-4 w-4 animate-spin mr-1.5" />
              ) : (
                <ShieldAlert className="h-4 w-4 mr-1.5" />
              )}
              Revoke all sessions
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function UsersTab({ token }: { token: string }) {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({
    email: "",
    password: "",
    full_name: "",
    role: "loan_officer",
    department: "general",
  });
  const [saving, setSaving] = useState(false);
  const [sessionsForUserId, setSessionsForUserId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await listUsers(token);
      setUsers(res.users);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load users");
    } finally {
      setIsLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async () => {
    setSaving(true);
    setError(null);
    try {
      await createUser(
        {
          email: form.email,
          password: form.password,
          full_name: form.full_name || null,
          role: form.role,
          department: form.department,
        },
        token
      );
      setShowCreate(false);
      setForm({ email: "", password: "", full_name: "", role: "loan_officer", department: "general" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create user");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {users.length} staff users
        </p>
        <Button type="button" size="sm" onClick={() => setShowCreate(true)}>
          <UserPlus className="h-3.5 w-3.5 mr-1.5" />
          New user
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <Card>
          <CardContent className="divide-y divide-border">
            {users.map((user) => (
              <div key={user.id} className="py-3 flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <p className="font-medium truncate">
                    {user.full_name || user.email}
                  </p>
                  <p className="text-xs text-muted-foreground">{user.email}</p>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setSessionsForUserId(user.id)}
                  >
                    <History className="h-3.5 w-3.5 mr-1.5" />
                    Sessions
                  </Button>
                  <Badge variant="outline">{user.role}</Badge>
                  <Badge variant="outline">{user.department}</Badge>
                  {!user.is_active && <Badge variant="destructive">inactive</Badge>}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create staff user</DialogTitle>
            <DialogDescription>
              Staff can search the knowledge base scoped to their department and
              assigned clients.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="user-email">Email</Label>
              <Input
                id="user-email"
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="user-fullname">Full name</Label>
              <Input
                id="user-fullname"
                value={form.full_name}
                onChange={(e) => setForm({ ...form, full_name: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="user-password">Password</Label>
              <Input
                id="user-password"
                type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                required
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Role</Label>
                <Select
                  value={form.role}
                  onValueChange={(v) => setForm({ ...form, role: v })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="admin">admin</SelectItem>
                    <SelectItem value="loan_officer">loan_officer</SelectItem>
                    <SelectItem value="underwriter">underwriter</SelectItem>
                    <SelectItem value="processor">processor</SelectItem>
                    <SelectItem value="viewer">viewer</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Department</Label>
                <Select
                  value={form.department}
                  onValueChange={(v) => setForm({ ...form, department: v })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="general">general</SelectItem>
                    <SelectItem value="loans">loans</SelectItem>
                    <SelectItem value="underwriting">underwriting</SelectItem>
                    <SelectItem value="hr">hr</SelectItem>
                    <SelectItem value="legal">legal</SelectItem>
                    <SelectItem value="operations">operations</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setShowCreate(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              onClick={handleCreate}
              disabled={saving || !form.email || !form.password}
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4 mr-1.5" />}
              Create user
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <SessionsDialog
        open={sessionsForUserId !== null}
        onOpenChange={(open) => !open && setSessionsForUserId(null)}
        title="User sessions"
        subjectLabel={
          users.find((u) => u.id === sessionsForUserId)?.email ?? "User"
        }
        loadSessions={async () => {
          if (sessionsForUserId == null) return { active_sessions: 0, sessions: [] };
          return listUserSessions(sessionsForUserId, token);
        }}
        revokeSessions={async () => {
          if (sessionsForUserId == null) return { revoked_sessions: 0 };
          return revokeUserSessions(sessionsForUserId, token);
        }}
        token={token}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Clients tab
// ---------------------------------------------------------------------------

function ClientsTab({ token }: { token: string }) {
  const [clients, setClients] = useState<AdminClient[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ email: "", password: "", full_name: "" });
  const [saving, setSaving] = useState(false);
  const [assignClientId, setAssignClientId] = useState<number | null>(null);
  const [assignUserId, setAssignUserId] = useState<string>("");
  const [assigning, setAssigning] = useState(false);
  const [sessionsForClientId, setSessionsForClientId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [clientsRes, usersRes] = await Promise.all([
        listClients(token),
        listUsers(token),
      ]);
      setClients(clientsRes.clients);
      setUsers(usersRes.users);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load clients");
    } finally {
      setIsLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async () => {
    setSaving(true);
    setError(null);
    try {
      await createClient(
        { email: form.email, password: form.password, full_name: form.full_name || null },
        token
      );
      setShowCreate(false);
      setForm({ email: "", password: "", full_name: "" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create client");
    } finally {
      setSaving(false);
    }
  };

  const handleAssign = async () => {
    if (assignClientId == null || !assignUserId) return;
    setAssigning(true);
    setError(null);
    try {
      await assignStaffToClient(assignClientId, Number(assignUserId), token);
      setAssignClientId(null);
      setAssignUserId("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to assign staff");
    } finally {
      setAssigning(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{clients.length} clients</p>
        <Button type="button" size="sm" onClick={() => setShowCreate(true)}>
          <UserPlus className="h-3.5 w-3.5 mr-1.5" />
          New client
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <Card>
          <CardContent className="divide-y divide-border">
            {clients.map((client) => (
              <div key={client.id} className="py-3 flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <p className="font-medium truncate">
                    {client.full_name || client.email}
                  </p>
                  <p className="text-xs text-muted-foreground">{client.email}</p>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  {!client.is_active && <Badge variant="destructive">inactive</Badge>}
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setSessionsForClientId(client.id)}
                  >
                    <History className="h-3.5 w-3.5 mr-1.5" />
                    Sessions
                  </Button>
                  <Dialog
                    open={assignClientId === client.id}
                    onOpenChange={(open) => !open && setAssignClientId(null)}
                  >
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setAssignClientId(client.id);
                        setAssignUserId("");
                      }}
                    >
                      <Users className="h-3.5 w-3.5 mr-1.5" />
                      Assign staff
                    </Button>
                    <DialogContent>
                      <DialogHeader>
                        <DialogTitle>Assign staff to client</DialogTitle>
                        <DialogDescription>
                          {client.full_name || client.email} — assigned staff
                          can see this client&apos;s documents in search.
                        </DialogDescription>
                      </DialogHeader>
                      <div className="space-y-2">
                        <Label>Staff user</Label>
                        <Select value={assignUserId} onValueChange={setAssignUserId}>
                          <SelectTrigger>
                            <SelectValue placeholder="Select a staff user" />
                          </SelectTrigger>
                          <SelectContent>
                            {users.map((u) => (
                              <SelectItem key={u.id} value={String(u.id)}>
                                {u.full_name || u.email}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <DialogFooter>
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => setAssignClientId(null)}
                        >
                          Cancel
                        </Button>
                        <Button
                          type="button"
                          onClick={handleAssign}
                          disabled={assigning || !assignUserId}
                        >
                          {assigning ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Users className="h-4 w-4 mr-1.5" />
                          )}
                          Assign
                        </Button>
                      </DialogFooter>
                    </DialogContent>
                  </Dialog>
                </div>
              </div>
            ))}
            {clients.length === 0 && (
              <p className="py-8 text-center text-sm text-muted-foreground">
                No clients yet.
              </p>
            )}
          </CardContent>
        </Card>
      )}

      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create client account</DialogTitle>
            <DialogDescription>
              Clients log in via the Client tab on the sign-in page and see only
              their own data.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="client-email">Email</Label>
              <Input
                id="client-email"
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="client-fullname">Full name</Label>
              <Input
                id="client-fullname"
                value={form.full_name}
                onChange={(e) => setForm({ ...form, full_name: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="client-password">Password</Label>
              <Input
                id="client-password"
                type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                required
              />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setShowCreate(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              onClick={handleCreate}
              disabled={saving || !form.email || !form.password}
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4 mr-1.5" />}
              Create client
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <SessionsDialog
        open={sessionsForClientId !== null}
        onOpenChange={(open) => !open && setSessionsForClientId(null)}
        title="Client sessions"
        subjectLabel={
          clients.find((c) => c.id === sessionsForClientId)?.email ?? "Client"
        }
        loadSessions={async () => {
          if (sessionsForClientId == null) return { active_sessions: 0, sessions: [] };
          return listClientSessions(sessionsForClientId, token);
        }}
        revokeSessions={async () => {
          if (sessionsForClientId == null) return { revoked_sessions: 0 };
          return revokeClientSessions(sessionsForClientId, token);
        }}
        token={token}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Analytics tab
// ---------------------------------------------------------------------------

function BarChart({
  data,
  valueKey,
  labelKey,
  color = "bg-primary",
  emptyLabel,
}: {
  data: { [k: string]: string | number }[];
  valueKey: string;
  labelKey: string;
  color?: string;
  emptyLabel: string;
}) {
  const max = Math.max(1, ...data.map((d) => Number(d[valueKey])));
  if (data.length === 0) {
    return <p className="text-sm text-muted-foreground">{emptyLabel}</p>;
  }
  return (
    <div className="space-y-2">
      {data.map((d, i) => {
        const value = Number(d[valueKey]);
        const width = Math.max(4, (value / max) * 100);
        return (
          <div key={i} className="flex items-center gap-3">
            <span className="w-32 shrink-0 truncate text-xs text-muted-foreground capitalize">
              {String(d[labelKey])}
            </span>
            <div className="flex-1 h-5 bg-muted rounded overflow-hidden">
              <div
                className={`h-full ${color} rounded`}
                style={{ width: `${width}%` }}
              />
            </div>
            <span className="w-8 shrink-0 text-right text-xs font-medium">
              {value}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function AnalyticsTab({ token }: { token: string }) {
  const [gaps, setGaps] = useState<KnowledgeGap[]>([]);
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [popularity, setPopularity] =
    useState<{ top_documents: DocumentPopularityEntry[]; underperforming_documents: DocumentPopularityEntry[] } | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [res, summaryRes, popRes] = await Promise.all([
        getKnowledgeGaps(token),
        getAnalyticsSummary(token),
        getDocumentPopularity(token),
      ]);
      setGaps(res.knowledge_gaps);
      setSummary(summaryRes.summary);
      setPopularity(popRes);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load analytics");
    } finally {
      setIsLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const statCards = [
    {
      label: "Total gaps",
      value: summary ? summary.total_gaps.toLocaleString() : "—",
    },
    {
      label: "Last 14 days",
      value: summary
        ? summary.by_day.reduce((acc, d) => acc + d.count, 0).toLocaleString()
        : "—",
    },
    {
      label: "Low confidence",
      value: summary ? summary.low_confidence_count.toLocaleString() : "—",
    },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Queries that returned no answer or low confidence — candidates for new
          or updated documents.
        </p>
        <Button type="button" variant="outline" size="sm" onClick={load}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
          Refresh
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            {statCards.map((s) => (
              <Card key={s.label}>
                <CardHeader className="pb-1">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    {s.label}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-2xl font-bold">{s.value}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Gaps by intent</CardTitle>
              </CardHeader>
              <CardContent>
                <BarChart
                  data={summary?.by_intent ?? []}
                  valueKey="count"
                  labelKey="intent"
                  emptyLabel="No knowledge gaps recorded yet."
                />
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Gaps per day (last 14 days)</CardTitle>
              </CardHeader>
              <CardContent>
                <BarChart
                  data={summary?.by_day ?? []}
                  valueKey="count"
                  labelKey="date"
                  color="bg-amber-500"
                  emptyLabel="No knowledge gaps in the last 14 days."
                />
              </CardContent>
            </Card>
          </div>

          {gaps.length === 0 ? (
            <Card>
              <CardContent className="p-8 text-center">
                <ShieldAlert className="h-8 w-8 mx-auto mb-2 text-muted-foreground" />
                <p className="font-medium">No knowledge gaps recorded</p>
                <p className="text-sm text-muted-foreground">
                  Queries that miss the knowledge base will show up here.
                </p>
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardContent className="divide-y divide-border">
                {gaps.map((gap) => (
                  <div key={gap.id} className="py-3">
                    <p className="font-medium">{gap.query}</p>
                    <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
                      {gap.intent && <Badge variant="outline">{gap.intent}</Badge>}
                      {gap.confidence != null && (
                        <span>confidence {Math.round(gap.confidence * 100)}%</span>
                      )}
                      <span>{formatDate(gap.created_at)}</span>
                    </div>
                  </div>
                ))}
              </CardContent>
             </Card>
          )}

          <div className="mt-6 space-y-3">
            <h3 className="text-sm font-medium">Document popularity</h3>
            <p className="text-sm text-muted-foreground">
              Which documents are being retrieved to answer queries, and how
              positively the answers they supported were reviewed.
            </p>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">
                  Top documents by answers
                </CardTitle>
              </CardHeader>
              <CardContent>
                {popularity?.top_documents.length ? (
                  <BarChart
                    data={popularity.top_documents.map((d) => ({
                      label: d.title,
                      value: d.answer_count,
                      ratio: d.positive_ratio,
                      users: d.distinct_users,
                    }))}
                    valueKey="value"
                    labelKey="label"
                    emptyLabel="No document popularity data yet."
                  />
                ) : (
                  <p className="text-sm text-muted-foreground">
                    No document popularity data yet.
                  </p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">
                  Underperforming documents
                </CardTitle>
              </CardHeader>
              <CardContent>
                {popularity?.underperforming_documents.length ? (
                  <div className="space-y-2">
                    {popularity.underperforming_documents.map((d) => (
                      <div
                        key={d.doc_id}
                        className="grid grid-cols-12 gap-2 text-xs"
                      >
                        <span className="col-span-5 truncate text-muted-foreground capitalize">
                          {d.title}
                        </span>
                        <span className="col-span-2">{d.department}</span>
                        <span className="col-span-2">
                          answered {d.answer_count} · no-answer {d.no_answer_count}
                        </span>
                        <span
                          className={
                            d.negative_count > 0
                              ? "col-span-3 text-destructive"
                              : "col-span-3"
                          }
                        >
                          {d.negative_count > 0
                            ? `${d.negative_count} negative review` +
                              (d.negative_count > 1 ? "s" : "")
                            : "low signal"}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    All documents performing well.
                  </p>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Knowledge Base tab (Phase F3 — read-only chunk browse)
// ---------------------------------------------------------------------------

function KnowledgeBaseTab({ token }: { token: string }) {
  const [documents, setDocuments] = useState<AdminDocument[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [chunks, setChunks] = useState<DocumentChunk[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadDocs = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await listAllDocuments(token);
      setDocuments(res.documents);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load documents");
    } finally {
      setIsLoading(false);
    }
  }, [token]);

  useEffect(() => {
    loadDocs();
  }, [loadDocs]);

  useEffect(() => {
    if (!selectedId) {
      setChunks([]);
      return;
    }
    setChunksLoading(true);
    setError(null);
    getDocumentChunks(Number(selectedId), token)
      .then((res) => setChunks(res.chunks))
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load chunks")
      )
      .finally(() => setChunksLoading(false));
  }, [selectedId, token]);

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Browse the raw text chunks each document contributes to the knowledge
        base. Read-only view.
      </p>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardContent className="pt-5 space-y-3">
          <Label htmlFor="kb-doc">Document</Label>
          <Select value={selectedId} onValueChange={setSelectedId}>
            <SelectTrigger id="kb-doc">
              <SelectValue placeholder="Choose a document…" />
            </SelectTrigger>
            <SelectContent>
              {isLoading ? (
                <SelectItem value="__loading" disabled>
                  Loading…
                </SelectItem>
              ) : (
                documents.map((doc) => (
                  <SelectItem key={doc.id} value={String(doc.id)}>
                    {doc.title} · {doc.department}
                  </SelectItem>
                ))
              )}
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      {chunksLoading ? (
        <div className="flex justify-center py-10">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : selectedId && chunks.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-center text-sm text-muted-foreground">
            No chunks found for this document.
          </CardContent>
        </Card>
      ) : (
        chunks.map((chunk) => (
          <Card key={chunk.id}>
            <CardContent className="p-5 space-y-2">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Badge variant="outline">{chunk.chunk_type}</Badge>
                {chunk.section && <Badge variant="outline">{chunk.section}</Badge>}
                <Badge variant="outline">{chunk.department}</Badge>
                <span
                  className={
                    chunk.is_approved ? "text-green-600" : "text-yellow-600"
                  }
                >
                  {chunk.approval_status}
                </span>
              </div>
              <p className="text-sm whitespace-pre-wrap">{chunk.content}</p>
            </CardContent>
          </Card>
        ))
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pinned Answers tab (curated verbatim response packages)
// ---------------------------------------------------------------------------

function PinnedAnswersTab({ token }: { token: string }) {
  const [pins, setPins] = useState<PinnedAnswer[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await listPinnedAnswers(token);
      setPins(res.pinned_answers);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load pinned answers");
    } finally {
      setIsLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const handleToggle = async (pin: PinnedAnswer) => {
    setBusyId(pin.id);
    setError(null);
    try {
      await patchPinnedAnswer(token, pin.id, { is_active: !pin.is_active });
      setPins((prev) =>
        prev.map((p) => (p.id === pin.id ? { ...p, is_active: !p.is_active } : p))
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update pin");
    } finally {
      setBusyId(null);
    }
  };

  const handleAudienceChange = async (pin: PinnedAnswer, audience: string) => {
    setBusyId(pin.id);
    setError(null);
    try {
      await patchPinnedAnswer(token, pin.id, {
        audience: audience as PinnedAnswer["audience"],
      });
      setPins((prev) =>
        prev.map((p) => (p.id === pin.id ? { ...p, audience: audience as PinnedAnswer["audience"] } : p))
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update audience");
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (pin: PinnedAnswer) => {
    setBusyId(pin.id);
    setError(null);
    try {
      await deletePinnedAnswer(token, pin.id);
      setPins((prev) => prev.filter((p) => p.id !== pin.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete pin");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Verified answers replay a stored response package verbatim when a
        staff or client query matches exactly — no retrieval, no generation.
        Pin new answers from the AI Assistant message menu (&quot;Pin as
        verified answer&quot;).
      </p>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {isLoading ? (
        <div className="flex justify-center py-10">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : pins.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-center text-sm text-muted-foreground">
            No pinned answers yet. Run a search in the AI Assistant and choose
            &quot;Pin as verified answer&quot; from the message menu.
          </CardContent>
        </Card>
      ) : (
        pins.map((pin) => (
          <Card key={pin.id} className={pin.is_active ? "" : "opacity-60"}>
            <CardContent className="p-5 space-y-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">{pin.query}</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    {pin.excerpt_count} excerpt{pin.excerpt_count === 1 ? "" : "s"} ·{" "}
                    {Math.round(pin.confidence * 100)}% confidence · source{" "}
                    {pin.source_response_id?.slice(0, 8) || "—"}
                  </p>
                </div>
                <Badge variant={pin.is_active ? "default" : "outline"}>
                  {pin.is_active ? "Active" : "Inactive"}
                </Badge>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <Select
                  value={pin.audience}
                  onValueChange={(v) => void handleAudienceChange(pin, v)}
                >
                  <SelectTrigger className="w-[150px] h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="staff">Staff only</SelectItem>
                    <SelectItem value="client">Clients only</SelectItem>
                    <SelectItem value="any">Everyone</SelectItem>
                  </SelectContent>
                </Select>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={busyId === pin.id}
                  onClick={() => void handleToggle(pin)}
                >
                  {pin.is_active ? "Deactivate" : "Activate"}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="text-destructive"
                  disabled={busyId === pin.id}
                  onClick={() => void handleDelete(pin)}
                >
                  <Trash2 className="h-3 w-3 mr-1" />
                  Delete
                </Button>
              </div>
            </CardContent>
          </Card>
        ))
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SOP Management tab (Phase F3 — read-all + access request review)
// ---------------------------------------------------------------------------

function SopManagementTab({ token }: { token: string }) {
  const [sops, setSops] = useState<Sop[]>([]);
  const [requests, setRequests] = useState<SopAccessRequest[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [sopRes, reqRes] = await Promise.all([
        listAllSops(token),
        listSopAccessRequests(token),
      ]);
      setSops(sopRes.sops);
      setRequests(reqRes.requests);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load SOP data");
    } finally {
      setIsLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const handleReview = async (requestId: number, decision: "approved" | "rejected") => {
    setBusyId(requestId);
    setError(null);
    try {
      await reviewSopAccessRequest(token, requestId, decision);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Review failed");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Standard operating procedures across all departments, plus pending
          authoring requests from staff.
        </p>
        <Button type="button" variant="outline" size="sm" onClick={load}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
          Refresh
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Access requests</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {requests.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No SOP access requests.
                </p>
              ) : (
                requests.map((req) => (
                  <div
                    key={req.id}
                    className="flex items-center justify-between gap-4 border-b border-border last:border-0 pb-2 last:pb-0"
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate">
                        {req.action} · {req.department}
                        <span className="ml-2 text-xs text-muted-foreground">
                          user #{req.user_id}
                        </span>
                      </p>
                      {req.reason && (
                        <p className="text-xs text-muted-foreground truncate">
                          {req.reason}
                        </p>
                      )}
                      <div className="mt-1 flex items-center gap-2">
                        {statusBadge(req.status)}
                        <span className="text-xs text-muted-foreground">
                          {formatDate(req.created_at)}
                        </span>
                      </div>
                    </div>
                    {req.status === "pending" && (
                      <div className="flex items-center gap-2 flex-shrink-0">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={busyId === req.id}
                          onClick={() => handleReview(req.id, "approved")}
                        >
                          Approve
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          disabled={busyId === req.id}
                          onClick={() => handleReview(req.id, "rejected")}
                        >
                          Reject
                        </Button>
                      </div>
                    )}
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <div className="space-y-2">
            {sops.map((sop) => (
              <Card key={sop.id}>
                <CardContent className="p-4 space-y-1">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium">{sop.title}</p>
                    <Badge variant="outline">{sop.department}</Badge>
                    <span className="text-xs text-muted-foreground">
                      v{sop.version}
                    </span>
                  </div>
                  <p className="text-sm text-muted-foreground whitespace-pre-wrap">
                    {sop.body.length > 280
                      ? `${sop.body.slice(0, 280)}…`
                      : sop.body}
                  </p>
                </CardContent>
              </Card>
            ))}
            {sops.length === 0 && (
              <p className="text-sm text-muted-foreground">No SOPs yet.</p>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Governance tab (Phase F3 config views + Phase H7 edit mode)
// ---------------------------------------------------------------------------

const CAPABILITY_LABELS: Record<string, string> = {
  onboard_clients: "Onboard clients",
};

function capabilityLabel(name: string): string {
  return CAPABILITY_LABELS[name] ?? name.replace(/_/g, " ");
}

const DEPT_NAME_RE = /^[a-z][a-z0-9_]*$/;

function GovernanceTab({ token }: { token: string }) {
  const [data, setData] = useState<GovernanceData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState<GovernanceUpdateInput | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      setData(await getGovernance(token));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load governance");
    } finally {
      setIsLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const startEditing = () => {
    if (!data) return;
    setError(null);
    setDraft({
      roles: data.roles.map((r) => ({
        name: r.name,
        label: r.label,
        description: r.description ?? "",
        access: r.access,
        capabilities: [...(r.capabilities ?? [])],
      })),
      departments: data.departments.map((d) => ({
        name: d.name,
        label: d.label,
        description: d.description ?? "",
      })),
      role_hierarchy: [...data.role_hierarchy],
    });
    setIsEditing(true);
  };

  const cancelEditing = () => {
    setIsEditing(false);
    setDraft(null);
    setError(null);
  };

  const handleSave = async () => {
    if (!draft) return;
    setError(null);

    const names = draft.departments.map((d) => d.name);
    if (new Set(names).size !== names.length) {
      setError("Department names must be unique");
      return;
    }
    for (const dept of draft.departments) {
      if (!DEPT_NAME_RE.test(dept.name)) {
        setError(`Invalid department name "${dept.name}" (use lowercase letters, digits, underscores)`);
        return;
      }
      if (!dept.label.trim()) {
        setError("Department labels cannot be empty");
        return;
      }
    }
    for (const role of draft.roles) {
      if (!role.label.trim()) {
        setError(`Role "${role.name}" needs a non-empty label`);
        return;
      }
      if (typeof role.access !== "string") {
        for (const dept of role.access) {
          if (!names.includes(dept)) {
            setError(`Role "${role.name}" references unknown department "${dept}"`);
            return;
          }
        }
      }
    }

    setSaving(true);
    try {
      const result = await updateGovernance(token, draft);
      setData(result);
      setIsEditing(false);
      setDraft(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save governance");
    } finally {
      setSaving(false);
    }
  };

  const renameDepartment = (from: string, to: string) => {
    if (!draft) return;
    setDraft({
      ...draft,
      roles: draft.roles.map((role) =>
        typeof role.access === "string"
          ? role
          : {
              ...role,
              access: role.access.map((d) => (d === from ? to : d)),
            }
      ),
    });
  };

  const allCapabilities = data
    ? Array.from(new Set(data.roles.flatMap((r) => r.capabilities ?? [])))
    : [];

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          {isEditing
            ? "Roles, capabilities, and departments are stored in roles_config.py. Renaming a department migrates existing records."
            : "Roles, capabilities, and departments are configuration-driven and enforced in the backend."}
        </p>
        {!isEditing ? (
          <Button type="button" variant="outline" size="sm" onClick={startEditing}>
            <Pencil className="h-3.5 w-3.5 mr-1.5" />
            Edit
          </Button>
        ) : (
          <div className="flex gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={cancelEditing}
              disabled={saving}
            >
              <X className="h-3.5 w-3.5 mr-1.5" />
              Cancel
            </Button>
            <Button type="button" size="sm" onClick={handleSave} disabled={saving}>
              {saving ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save className="h-3.5 w-3.5 mr-1.5" />
              )}
              Save changes
            </Button>
          </div>
        )}
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Roles &amp; permissions</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {(isEditing && draft ? draft.roles : data?.roles ?? []).map((role, idx) => (
            <div
              key={role.name}
              className="border-b border-border last:border-0 pb-3 last:pb-0"
            >
              {isEditing ? (
                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-mono text-muted-foreground">
                      {role.name}
                    </span>
                    <Badge variant="outline">
                      {typeof role.access === "string" && role.access === "all"
                        ? "All departments"
                        : (role.access as string[]).join(", ")}
                    </Badge>
                  </div>
                  <Input
                    aria-label={`${role.name} label`}
                    value={role.label}
                    onChange={(e) => {
                      setDraft({
                        ...draft!,
                        roles: draft!.roles.map((r, i) =>
                          i === idx ? { ...r, label: e.target.value } : r
                        ),
                      });
                    }}
                  />
                  <Input
                    aria-label={`${role.name} description`}
                    value={role.description}
                    onChange={(e) => {
                      setDraft({
                        ...draft!,
                        roles: draft!.roles.map((r, i) =>
                          i === idx ? { ...r, description: e.target.value } : r
                        ),
                      });
                    }}
                  />
                  {allCapabilities.length > 0 && (
                    <div className="flex flex-wrap gap-2 pt-1">
                      {allCapabilities.map((cap) => {
                        const roleCaps = draft!.roles[idx].capabilities;
                        const checked = roleCaps.includes(cap);
                        return (
                          <label
                            key={cap}
                            className="flex items-center gap-1.5 text-xs cursor-pointer"
                          >
                            <Checkbox
                              checked={checked}
                              onCheckedChange={(c) => {
                                const next = c === true;
                                setDraft({
                                  ...draft!,
                                  roles: draft!.roles.map((r, i) =>
                                    i === idx
                                      ? {
                                          ...r,
                                          capabilities: next
                                            ? Array.from(new Set([...r.capabilities, cap]))
                                            : r.capabilities.filter((x) => x !== cap),
                                        }
                                      : r
                                  ),
                                });
                              }}
                            />
                            <KeyRound className="h-3 w-3 text-muted-foreground" />
                            {capabilityLabel(cap)}
                          </label>
                        );
                      })}
                    </div>
                  )}
                </div>
              ) : (
                <>
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium">{role.label}</p>
                    <Badge variant="outline">
                      {typeof role.access === "string" && role.access === "all"
                        ? "All departments"
                        : (role.access as string[]).join(", ")}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    {role.description}
                  </p>
                  {(role.capabilities ?? []).length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {(role.capabilities ?? []).map((cap) => (
                        <Badge key={cap} variant="secondary" className="text-[11px]">
                          <KeyRound className="h-3 w-3 mr-1" />
                          {capabilityLabel(cap)}
                        </Badge>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          ))}
          {data && !isEditing && data.role_hierarchy.length > 0 && (
            <p className="text-xs text-muted-foreground pt-1">
              Hierarchy (lowest → highest): {data.role_hierarchy.join(" → ")}
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Departments</CardTitle>
          {isEditing && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="self-start"
              onClick={() =>
                setDraft({
                  ...draft!,
                  departments: [
                    ...draft!.departments,
                    { name: "", label: "", description: "" },
                  ],
                })
              }
            >
              <Plus className="h-3.5 w-3.5 mr-1.5" />
              Add department
            </Button>
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          {(isEditing && draft ? draft.departments : data?.departments ?? []).map(
            (dept, idx) => (
              <div
                key={`${dept.name}-${idx}`}
                className="border-b border-border last:border-0 pb-3 last:pb-0"
              >
                {isEditing ? (
                  <div className="space-y-2">
                    <div className="grid grid-cols-2 gap-2">
                      <Input
                        aria-label="Department name"
                        value={dept.name}
                        onChange={(e) => {
                          const old = draft!.departments[idx].name;
                          const next = e.target.value;
                          setDraft({
                            ...draft!,
                            departments: draft!.departments.map((d, i) =>
                              i === idx ? { ...d, name: next } : d
                            ),
                          });
                          renameDepartment(old, next);
                        }}
                        className="font-mono text-xs"
                      />
                      <Input
                        aria-label="Department label"
                        value={dept.label}
                        onChange={(e) => {
                          setDraft({
                            ...draft!,
                            departments: draft!.departments.map((d, i) =>
                              i === idx ? { ...d, label: e.target.value } : d
                            ),
                          });
                        }}
                      />
                    </div>
                    <Input
                      aria-label="Department description"
                      value={dept.description}
                      onChange={(e) => {
                        setDraft({
                          ...draft!,
                          departments: draft!.departments.map((d, i) =>
                            i === idx ? { ...d, description: e.target.value } : d
                          ),
                        });
                      }}
                    />
                  </div>
                ) : (
                  <>
                    <p className="text-sm font-medium">{dept.label}</p>
                    <p className="text-xs text-muted-foreground mt-1">
                      {dept.description}
                    </p>
                  </>
                )}
              </div>
            )
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dashboard tab (Phase F2)
// ---------------------------------------------------------------------------

function DashboardTab({ token }: { token: string }) {
  const [summary, setSummary] = useState<AdminSummary | null>(null);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [summaryRes, healthRes] = await Promise.all([
        getAdminSummary(token),
        getSystemHealth(token),
      ]);
      setSummary(summaryRes);
      setHealth(healthRes);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load summary");
    } finally {
      setIsLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const statCards: {
    label: string;
    value: string;
    hint: string;
    alert?: boolean;
  }[] = [
    {
      label: "Pending approvals",
      value: summary ? summary.pending_approvals.toLocaleString() : "—",
      hint: "documents awaiting review",
    },
    {
      label: "Stale pending approvals",
      value: summary ? summary.stale_pending_approvals.toLocaleString() : "—",
      hint: "awaiting review for 7+ days",
      alert: summary ? summary.stale_pending_approvals > 0 : false,
    },
    {
      label: "Documents",
      value: summary ? summary.total_documents.toLocaleString() : "—",
      hint: "in the knowledge base",
    },
    {
      label: "Active cases",
      value: summary ? summary.active_cases.toLocaleString() : "—",
      hint: "currently open",
    },
    {
      label: "Users",
      value: summary ? summary.total_users.toLocaleString() : "—",
      hint: "staff accounts",
    },
    {
      label: "Clients",
      value: summary ? summary.total_clients.toLocaleString() : "—",
      hint: "external accounts",
    },
    {
      label: "Knowledge gaps",
      value: summary ? summary.total_gaps.toLocaleString() : "—",
      hint: "low/no-answer queries",
    },
    {
      label: "SOP access requests",
      value: summary ? summary.pending_sop_requests.toLocaleString() : "—",
      hint: "awaiting review",
    },
    {
      label: "Reviews overdue",
      value: summary
        ? (summary.documents_review_overdue ?? 0).toLocaleString()
        : "—",
      hint: "documents past their review date",
      alert: summary ? (summary.documents_review_overdue ?? 0) > 0 : false,
    },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          At-a-glance system health. Deep links live in their own tabs.
        </p>
        <Button type="button" variant="outline" size="sm" onClick={load}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
          Refresh
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
          <div className="mt-2 flex gap-2">
            <Button type="button" variant="outline" size="sm" onClick={load}>
              <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
              Retry
            </Button>
          </div>
        </Alert>
      )}

      {isLoading ? (
        <DashboardSkeleton statCards={statCards.length} />
      ) : (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {statCards.map((s) => (
              <Card
                key={s.label}
                className={s.alert ? "border-amber-400 bg-amber-50 dark:bg-amber-950/30" : undefined}
              >
                <CardHeader className="pb-1">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    {s.label}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className={"text-2xl font-bold" + (s.alert ? " text-amber-600 dark:text-amber-400" : "")}>
                    {s.value}
                  </p>
                  <p className="text-xs text-muted-foreground mt-1">{s.hint}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">System status</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <div className="flex items-center gap-2">
                <span
                  className={
                    "inline-flex h-2 w-2 rounded-full " +
                    (health?.status === "healthy"
                      ? "bg-green-500"
                      : health?.status === "degraded"
                        ? "bg-amber-500"
                        : "bg-gray-400")
                  }
                />
                <span className="text-sm font-medium capitalize">
                  {health ? health.status : "unknown"}
                </span>
                <span className="text-xs text-muted-foreground">
                  API {health?.version ?? "—"} · database{" "}
                  {health ? health.database : "unknown"}
                </span>
              </div>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-md border p-3">
                  <p className="text-xs text-muted-foreground">Storage pending</p>
                  <p className="text-sm font-medium">
                    {health?.storage.pending.writable ? "writable" : "not writable"}
                  </p>
                </div>
                <div className="rounded-md border p-3">
                  <p className="text-xs text-muted-foreground">Storage processed</p>
                  <p className="text-sm font-medium">
                    {health?.storage.processed.writable ? "writable" : "not writable"}
                  </p>
                </div>
                <div className="rounded-md border p-3">
                  <p className="text-xs text-muted-foreground">Last ingest</p>
                  <p className="text-sm font-medium">
                    {health?.last_ingest
                      ? new Date(health.last_ingest).toLocaleString()
                      : "never"}
                  </p>
                </div>
                <div className="rounded-md border p-3">
                  <p className="text-xs text-muted-foreground">Checked at</p>
                  <p className="text-sm font-medium">
                    {health ? new Date(health.timestamp * 1000).toLocaleString() : "—"}
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Settings tab (Phase F2 — frontend preferences)
// ---------------------------------------------------------------------------

const SETTINGS_STORAGE_KEY = "asto_admin_settings";

interface AdminSettings {
  showAuditBanner: boolean;
  defaultTab: string;
}

function loadSettings(): AdminSettings {
  if (typeof window === "undefined") return { showAuditBanner: true, defaultTab: "dashboard" };
  try {
    const raw = localStorage.getItem(SETTINGS_STORAGE_KEY);
    if (raw) return { showAuditBanner: true, defaultTab: "dashboard", ...JSON.parse(raw) };
  } catch {
    // ignore corrupt prefs
  }
  return { showAuditBanner: true, defaultTab: "dashboard" };
}

function SettingsTab({
  token,
  onDefaultTabChange,
}: {
  token: string;
  onDefaultTabChange: (tab: string) => void;
}) {
  const [settings, setSettings] = useState<AdminSettings>({
    showAuditBanner: true,
    defaultTab: "dashboard",
  });
  const [saved, setSaved] = useState(false);
  const [flags, setFlags] = useState<FeatureFlag[]>([]);
  const [flagsLoading, setFlagsLoading] = useState(true);
  const [flagsError, setFlagsError] = useState<string | null>(null);

  useEffect(() => {
    setSettings(loadSettings());
  }, []);

  useEffect(() => {
    let cancelled = false;
    getFeatureFlags(token)
      .then((data) => {
        if (!cancelled) setFlags(data);
      })
      .catch((err) => {
        if (!cancelled)
          setFlagsError(err instanceof Error ? err.message : "Failed to load flags");
      })
      .finally(() => {
        if (!cancelled) setFlagsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const toggleFlag = async (name: string, enabled: boolean) => {
    try {
      await setFeatureFlag(token, name, enabled);
      setFlags((prev) =>
        prev.map((f) => (f.name === name ? { ...f, enabled, source: "table" } : f))
      );
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setFlagsError(err instanceof Error ? err.message : "Failed to update flag");
    }
  };

  const persist = (next: AdminSettings) => {
    setSettings(next);
    try {
      localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(next));
    } catch {
      // ignore
    }
    setSaved(true);
    window.setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="max-w-xl space-y-4">
      <p className="text-sm text-muted-foreground">
        Frontend preferences, stored in this browser. They don&apos;t affect the
        server or the audit trail.
      </p>

      {saved && (
        <Alert>
          <CheckCircle2 className="h-4 w-4" />
          <AlertTitle>Saved</AlertTitle>
          <AlertDescription>Preferences updated.</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Landing view</CardTitle>
        </CardHeader>
        <CardContent>
          <Label htmlFor="default-tab">Default tab after sign-in</Label>
          <Select
            value={settings.defaultTab}
            onValueChange={(value) => {
              persist({ ...settings, defaultTab: value });
              onDefaultTabChange(value);
            }}
          >
            <SelectTrigger id="default-tab" className="mt-2 w-full">
              <SelectValue placeholder="Choose a tab" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="dashboard">Dashboard</SelectItem>
              <SelectItem value="approvals">Approvals</SelectItem>
              <SelectItem value="documents">Documents</SelectItem>
              <SelectItem value="analytics">Analytics</SelectItem>
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Audit banner</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Label className="flex items-center justify-between gap-4">
            <span className="font-normal text-sm">
              Show the &quot;every decision is written to the audit trail&quot; banner
            </span>
            <input
              type="checkbox"
              checked={settings.showAuditBanner}
              onChange={(e) =>
                persist({ ...settings, showAuditBanner: e.target.checked })
              }
              className="h-4 w-4 rounded border-border"
            />
          </Label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Feature flags</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Server-side gates for risky endpoints. Changes are audit-logged and
            apply within seconds.
          </p>
          {flagsLoading ? (
            <div className="flex justify-center py-4">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            </div>
          ) : flagsError ? (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Error</AlertTitle>
              <AlertDescription>{flagsError}</AlertDescription>
            </Alert>
          ) : flags.length === 0 ? (
            <p className="text-sm text-muted-foreground">No flags defined.</p>
          ) : (
            <div className="space-y-2">
              {flags.map((flag) => (
                <Label
                  key={flag.name}
                  className="flex items-center justify-between gap-4 rounded-md border p-3"
                >
                  <span className="flex flex-col">
                    <span className="font-medium text-sm">{flag.name}</span>
                    <span className="text-xs text-muted-foreground">
                      source: {flag.source}
                    </span>
                  </span>
                  <input
                    type="checkbox"
                    checked={flag.enabled}
                    onChange={(e) => toggleFlag(flag.name, e.target.checked)}
                    className="h-5 w-5 rounded border-border accent-primary"
                  />
                </Label>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Audit Log tab (Phase F7)
// ---------------------------------------------------------------------------

const OUTCOME_TONES: Record<string, string> = {
  answer: "bg-green-100 text-green-800 border-green-200",
  partial: "bg-yellow-100 text-yellow-800 border-yellow-200",
  no_answer: "bg-red-100 text-red-800 border-red-200",
  no_sub_queries: "bg-red-100 text-red-800 border-red-200",
};

function AuditLogTab({ token }: { token: string }) {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [actor, setActor] = useState("");
  const [outcome, setOutcome] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 25;
  const [exporting, setExporting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getAdminAudit(token, {
        q: q || undefined,
        actor: actor || undefined,
        outcome: outcome || undefined,
        from: from || undefined,
        to: to || undefined,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      });
      setEntries(res.entries);
      setTotal(res.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load audit log");
    } finally {
      setLoading(false);
    }
  }, [token, q, actor, outcome, from, to, page]);

  useEffect(() => {
    load();
  }, [load]);

  const handleExport = async () => {
    setExporting(true);
    setError(null);
    try {
      await exportAuditLogCsv(token, {
        q: q || undefined,
        actor: actor || undefined,
        outcome: outcome || undefined,
        from: from || undefined,
        to: to || undefined,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to export audit log");
    } finally {
      setExporting(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Every query, decision, and action — recorded per CLAUDE.md rule 8.
        </p>
        <Button type="button" variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
          Refresh
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleExport}
          disabled={exporting}
        >
          <Download className="h-3.5 w-3.5 mr-1.5" />
          {exporting ? "Exporting…" : "Export CSV"}
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardContent className="p-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <div className="space-y-1">
              <Label htmlFor="audit-q" className="text-xs text-muted-foreground">
                Query text
              </Label>
              <Input
                id="audit-q"
                value={q}
                onChange={(e) => {
                  setQ(e.target.value);
                  setPage(1);
                }}
                placeholder="Search queries…"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="audit-actor" className="text-xs text-muted-foreground">
                Actor
              </Label>
              <Input
                id="audit-actor"
                value={actor}
                onChange={(e) => {
                  setActor(e.target.value);
                  setPage(1);
                }}
                placeholder="Email or name…"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="audit-outcome" className="text-xs text-muted-foreground">
                Outcome
              </Label>
              <Select
                value={outcome || "__all__"}
                onValueChange={(v) => {
                  setOutcome(v === "__all__" ? "" : v);
                  setPage(1);
                }}
              >
                <SelectTrigger id="audit-outcome">
                  <SelectValue placeholder="Any" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">Any</SelectItem>
                  <SelectItem value="answer">answer</SelectItem>
                  <SelectItem value="partial">partial</SelectItem>
                  <SelectItem value="no_answer">no_answer</SelectItem>
                  <SelectItem value="no_sub_queries">no_sub_queries</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="audit-from" className="text-xs text-muted-foreground">
                From
              </Label>
              <Input
                id="audit-from"
                type="date"
                value={from}
                onChange={(e) => {
                  setFrom(e.target.value);
                  setPage(1);
                }}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="audit-to" className="text-xs text-muted-foreground">
                To
              </Label>
              <Input
                id="audit-to"
                type="date"
                value={to}
                onChange={(e) => {
                  setTo(e.target.value);
                  setPage(1);
                }}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : entries.length === 0 ? (
            <div className="py-12 text-center text-sm text-muted-foreground">
              No audit entries match the current filters.
            </div>
          ) : (
            <div className="divide-y divide-border">
              {entries.map((e) => (
                <div key={e.id} className="px-4 py-3 space-y-1.5">
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <p className="text-sm font-medium truncate flex items-center gap-2">
                      <History className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
                      {e.query}
                    </p>
                    <span
                      className={cn(
                        "text-xs px-2 py-0.5 rounded-full border",
                        OUTCOME_TONES[e.outcome ?? ""] ?? "border-border text-muted-foreground"
                      )}
                    >
                      {e.outcome ?? "—"}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 flex-wrap text-xs text-muted-foreground">
                    <span>
                      {e.actor ?? "system"} ({e.actor_email ?? "no account"})
                    </span>
                    {e.confidence != null && <span>conf {Math.round(e.confidence * 100)}%</span>}
                    {e.latency_ms != null && <span>{e.latency_ms.toFixed(0)}ms</span>}
                    {e.created_at && <span>{formatDate(e.created_at)}</span>}
                  </div>
                  {e.retrieved_ids && e.retrieved_ids.length > 0 && (
                    <p className="text-xs text-muted-foreground">
                      sources: {e.retrieved_ids.join(", ")}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {total.toLocaleString()} matching entries
        </p>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={page <= 1 || loading}
            onClick={() => setPage((p) => p - 1)}
          >
            Prev
          </Button>
          <span className="text-sm text-muted-foreground">
            Page {page} of {totalPages}
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={page >= totalPages || loading}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Admin page shell
// ---------------------------------------------------------------------------

export default function AdminPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [activeNavId, setActiveNavId] = useState("dashboard");
  const [userName, setUserName] = useState<string | null>(null);
  const [userRole, setUserRole] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    let mounted = true;
    restoreSession().then((t) => {
      if (!mounted) return;
      const claims = t ? decodeToken(t) : null;
      if (!t || !isAdminRole(claims?.role)) {
        router.replace("/login");
        return;
      }
      setToken(t);
      setUserName(claims?.name ?? claims?.sub ?? null);
      setUserRole(claims?.role ?? null);
      setIsAdmin(true);
      try {
        const raw = localStorage.getItem("asto_admin_settings");
        if (raw) {
          const prefs = JSON.parse(raw);
          if (prefs.defaultTab) setActiveNavId(prefs.defaultTab);
        }
      } catch {
        // ignore corrupt prefs
      }
    });
    return () => {
      mounted = false;
    };
  }, [router]);

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

  if (!isAdmin || !token) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <>
      <AppShell
      navGroups={NAV_GROUPS.admin}
      activeNavId={activeNavId}
      onNavigate={(id) => setActiveNavId(id)}
      brandTitle="Asto"
      brandSubtitle="Admin Control Hub"
      headerTitle="Admin"
      headerSubtitle="Approvals · Documents · Users · Clients"
      headerActions={
        <Button asChild variant="outline" size="sm">
          <Link href="/">
            <MessageSquare className="h-4 w-4 mr-2" />
            Ask Asto
          </Link>
        </Button>
      }
      user={{ name: userName ?? "Administrator", role: userRole ?? "admin" }}
      onSignOut={handleLogout}
      onSettings={() => setSettingsOpen(true)}
    >
      <div className="max-w-5xl mx-auto px-4 py-8 flex-1 overflow-y-auto">
        <Tabs value={activeNavId} onValueChange={setActiveNavId}>
          <TabsList className="grid w-full grid-cols-12">
            <TabsTrigger value="dashboard">Dashboard</TabsTrigger>
            <TabsTrigger value="approvals">Approvals</TabsTrigger>
            <TabsTrigger value="documents">Documents</TabsTrigger>
            <TabsTrigger value="knowledge">Knowledge</TabsTrigger>
            <TabsTrigger value="pinned">Pinned</TabsTrigger>
            <TabsTrigger value="sops">SOPs</TabsTrigger>
            <TabsTrigger value="users">Users</TabsTrigger>
            <TabsTrigger value="clients">Clients</TabsTrigger>
            <TabsTrigger value="roles">Roles</TabsTrigger>
            <TabsTrigger value="departments">Departments</TabsTrigger>
            <TabsTrigger value="analytics">Analytics</TabsTrigger>
            <TabsTrigger value="audit">Audit</TabsTrigger>
            <TabsTrigger value="settings">Settings</TabsTrigger>
          </TabsList>
          <TabsContent value="dashboard">
            <DashboardTab token={token} />
          </TabsContent>
          <TabsContent value="approvals">
            <ApprovalsTab token={token} />
          </TabsContent>
          <TabsContent value="documents">
            <DocumentsTab token={token} />
          </TabsContent>
          <TabsContent value="knowledge">
            <KnowledgeBaseTab token={token} />
          </TabsContent>
          <TabsContent value="pinned">
            <PinnedAnswersTab token={token} />
          </TabsContent>
          <TabsContent value="sops">
            <SopManagementTab token={token} />
          </TabsContent>
          <TabsContent value="users">
            <UsersTab token={token} />
          </TabsContent>
          <TabsContent value="clients">
            <ClientsTab token={token} />
          </TabsContent>
          <TabsContent value="roles">
            <GovernanceTab token={token} />
          </TabsContent>
          <TabsContent value="departments">
            <GovernanceTab token={token} />
          </TabsContent>
          <TabsContent value="analytics">
            <AnalyticsTab token={token} />
          </TabsContent>
          <TabsContent value="audit">
            <AuditLogTab token={token} />
          </TabsContent>
          <TabsContent value="settings">
            <SettingsTab token={token} onDefaultTabChange={setActiveNavId} />
          </TabsContent>
        </Tabs>

        <footer className="border-t border-border py-4">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Sparkles className="w-3.5 h-3.5" />
            Asto — every decision here is written to the audit trail.
          </div>
        </footer>
      </div>
    </AppShell>

    <SettingsModal
      open={settingsOpen}
      onOpenChange={setSettingsOpen}
      user={{ name: userName ?? "Administrator", role: userRole ?? "admin" }}
      onSignOut={handleLogout}
      onSignOutAll={handleLogoutAll}
    />
    <OnboardingTour role="admin" />
    </>
  );
}
