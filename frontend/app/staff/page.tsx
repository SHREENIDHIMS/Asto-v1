"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  Briefcase,
  CheckCircle2,
  Loader2,
  MessageSquare,
  RefreshCw,
  Sparkles,
  UserPlus,
  Workflow as WorkflowIcon,
} from "lucide-react";
import {
  getStaffDashboard,
  getCaseNotes,
  addCaseNote,
  advanceWorkflow,
  createSop,
  getMySopRequests,
  createSopAccessRequest,
  getStaffConversations,
  createStaffConversation,
  getStaffConversationMessages,
  sendStaffMessage,
  onboardClient,
  StaffDashboardCase,
  StaffDashboardResponse,
  StaffWorkflow,
  StaffSop,
  CaseNote,
  SopAccessRequest,
  Conversation,
} from "@/lib/api-client";
import { clearToken, decodeToken, getToken } from "@/lib/auth";
import AppShell from "@/components/layout/AppShell";
import { NAV_GROUPS } from "@/config/navigation";
import ConversationThread from "@/components/messages/ConversationThread";
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
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

function formatMoney(value: number | null): string {
  if (value == null) return "—";
  return value.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

function workflowBadge(status: string) {
  switch (status) {
    case "done":
      return <Badge className="bg-green-100 text-green-800 border-green-200">done</Badge>;
    case "review":
      return <Badge className="bg-yellow-100 text-yellow-800 border-yellow-200">review</Badge>;
    default:
      return <Badge variant="outline">{status}</Badge>;
  }
}

// ---------------------------------------------------------------------------
// Dashboard tab
// ---------------------------------------------------------------------------

function StaffDashboardTab({
  data,
  isLoading,
  onRefresh,
}: {
  data: StaffDashboardResponse | null;
  isLoading: boolean;
  onRefresh: () => void;
}) {
  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const statCards = [
    { label: "My cases", value: data ? data.cases.length.toLocaleString() : "—", hint: "assigned clients" },
    { label: "Active workflows", value: data ? data.workflows.length.toLocaleString() : "—", hint: "in progress or review" },
    { label: "Department SOPs", value: data ? data.sops.length.toLocaleString() : "—", hint: "available to you" },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Your cases, active workflows, and department SOPs at a glance.
        </p>
        <Button type="button" variant="outline" size="sm" onClick={onRefresh}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
          Refresh
        </Button>
      </div>

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
              <p className="text-xs text-muted-foreground mt-1">{s.hint}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Recent workflows</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {data && data.workflows.length > 0 ? (
            data.workflows.slice(0, 5).map((wf) => (
              <div
                key={wf.id}
                className="flex items-center justify-between gap-4 border-b border-border last:border-0 pb-2 last:pb-0"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">{wf.title}</p>
                  <p className="text-xs text-muted-foreground truncate">
                    {wf.department}
                    {wf.case_number ? ` · ${wf.case_number}` : ""}
                  </p>
                </div>
                {workflowBadge(wf.status)}
              </div>
            ))
          ) : (
            <p className="text-sm text-muted-foreground">No workflows.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// My Cases tab (case list + notes)
// ---------------------------------------------------------------------------

function MyCasesTab({
  cases,
  token,
  onRefresh,
}: {
  cases: StaffDashboardCase[];
  token: string;
  onRefresh: () => void;
}) {
  const [selectedCase, setSelectedCase] = useState<number | null>(null);
  const [notes, setNotes] = useState<CaseNote[]>([]);
  const [notesLoading, setNotesLoading] = useState(false);
  const [noteBody, setNoteBody] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadNotes = useCallback(
    async (caseId: number) => {
      setNotesLoading(true);
      setError(null);
      try {
        const res = await getCaseNotes(token, caseId);
        setNotes(res.notes);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load notes");
      } finally {
        setNotesLoading(false);
      }
    },
    [token]
  );

  useEffect(() => {
    if (selectedCase != null) loadNotes(selectedCase);
  }, [selectedCase, loadNotes]);

  const handleAddNote = async () => {
    if (selectedCase == null || !noteBody.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await addCaseNote(token, selectedCase, noteBody.trim());
      setNoteBody("");
      await loadNotes(selectedCase);
      onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add note");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-4">
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {cases.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-center text-sm text-muted-foreground">
            No cases assigned to you.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-2">
            {cases.map((c) => (
              <Card
                key={c.id}
                className={`cursor-pointer transition-colors ${
                  selectedCase === c.id ? "ring-2 ring-primary" : ""
                }`}
                onClick={() => setSelectedCase(c.id)}
              >
                <CardContent className="p-4 space-y-1">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium">{c.case_number}</p>
                    <Badge variant="outline">{c.status}</Badge>
                  </div>
                  <p className="text-xs text-muted-foreground truncate">
                    {c.client_name ?? `client #${c.client_id}`}
                  </p>
                  <p className="text-xs text-muted-foreground truncate">
                    {[c.address, c.city, c.state].filter(Boolean).join(", ") || "—"}
                  </p>
                  <p className="text-sm font-semibold">{formatMoney(c.loan_amount)}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">
                Case notes
                {selectedCase != null ? ` — ${cases.find((c) => c.id === selectedCase)?.case_number}` : ""}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {selectedCase == null ? (
                <p className="text-sm text-muted-foreground">
                  Select a case to view and add collaboration notes.
                </p>
              ) : notesLoading ? (
                <div className="flex justify-center py-6">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <>
                  <div className="space-y-2 max-h-64 overflow-y-auto">
                    {notes.length === 0 ? (
                      <p className="text-sm text-muted-foreground">No notes yet.</p>
                    ) : (
                      notes.map((n) => (
                        <div key={n.id} className="rounded-md border border-border p-3">
                          <p className="text-sm whitespace-pre-wrap">{n.body}</p>
                          <p className="text-xs text-muted-foreground mt-1">
                            {n.author_name ?? `user #${n.user_id}`} · {formatDate(n.created_at)}
                          </p>
                        </div>
                      ))
                    )}
                  </div>
                  <div className="flex items-end gap-2 pt-2 border-t border-border">
                    <Input
                      placeholder="Add a note…"
                      value={noteBody}
                      onChange={(e) => setNoteBody(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          handleAddNote();
                        }
                      }}
                    />
                    <Button type="button" onClick={handleAddNote} disabled={submitting || !noteBody.trim()}>
                      {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : "Add"}
                    </Button>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Workflows tab
// ---------------------------------------------------------------------------

function WorkflowsTab({
  workflows,
  token,
  onRefresh,
}: {
  workflows: StaffWorkflow[];
  token: string;
  onRefresh: () => void;
}) {
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleAdvance = async (id: number) => {
    setBusyId(id);
    setError(null);
    try {
      await advanceWorkflow(token, id);
      onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to advance workflow");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-4">
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {workflows.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-center text-sm text-muted-foreground">
            No workflows in your departments.
          </CardContent>
        </Card>
      ) : (
        workflows.map((wf) => (
          <Card key={wf.id}>
            <CardContent className="p-4 flex items-center justify-between gap-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <WorkflowIcon className="h-4 w-4 text-muted-foreground" />
                  <p className="text-sm font-medium truncate">{wf.title}</p>
                  {workflowBadge(wf.status)}
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  {wf.department}
                  {wf.case_number ? ` · ${wf.case_number}` : ""}
                  {" · "}updated {formatDate(wf.updated_at)}
                </p>
              </div>
              {wf.status !== "done" && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={busyId === wf.id}
                  onClick={() => handleAdvance(wf.id)}
                >
                  {busyId === wf.id ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    "Advance"
                  )}
                </Button>
              )}
            </CardContent>
          </Card>
        ))
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tasks tab (Phase F5 — derived from workflows)
// ---------------------------------------------------------------------------

function TasksTab({
  workflows,
  token,
  onRefresh,
}: {
  workflows: StaffWorkflow[];
  token: string;
  onRefresh: () => void;
}) {
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleAdvance = async (id: number) => {
    setBusyId(id);
    setError(null);
    try {
      await advanceWorkflow(token, id);
      onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to advance task");
    } finally {
      setBusyId(null);
    }
  };

  const actionable = workflows.filter((w) => w.status !== "done");
  const doneCount = workflows.length - actionable.length;

  const statCards = [
    { label: "Open tasks", value: actionable.length.toLocaleString(), hint: "in progress or review" },
    { label: "Completed", value: doneCount.toLocaleString(), hint: "finished workflows" },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Tasks are derived from your department&apos;s active workflows.
        </p>
        <Button type="button" variant="outline" size="sm" onClick={onRefresh}>
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

      <div className="grid gap-4 sm:grid-cols-2">
        {statCards.map((s) => (
          <Card key={s.label}>
            <CardHeader className="pb-1">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {s.label}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold">{s.value}</p>
              <p className="text-xs text-muted-foreground mt-1">{s.hint}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {actionable.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-center text-sm text-muted-foreground">
            <CheckCircle2 className="h-8 w-8 mx-auto mb-2 text-green-600" />
            All caught up — no open tasks.
          </CardContent>
        </Card>
      ) : (
        actionable.map((wf) => (
          <Card key={wf.id}>
            <CardContent className="p-4 flex items-center justify-between gap-4">
              <div className="min-w-0 flex items-start gap-3">
                <WorkflowIcon className="h-4 w-4 text-muted-foreground mt-0.5" />
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className="text-sm font-medium">{wf.title}</p>
                    {workflowBadge(wf.status)}
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    {wf.department}
                    {wf.case_number ? ` · ${wf.case_number}` : ""}
                  </p>
                </div>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={busyId === wf.id}
                onClick={() => handleAdvance(wf.id)}
              >
                {busyId === wf.id ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  "Advance"
                )}
              </Button>
            </CardContent>
          </Card>
        ))
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SOPs tab
// ---------------------------------------------------------------------------

function SopsTab({
  sops,
  sopAccess,
  token,
  onRefresh,
}: {
  sops: StaffSop[];
  sopAccess: boolean;
  token: string;
  onRefresh: () => void;
}) {
  const [myRequests, setMyRequests] = useState<SopAccessRequest[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [showRequest, setShowRequest] = useState(false);
  const [title, setTitle] = useState("");
  const [department, setDepartment] = useState("general");
  const [body, setBody] = useState("");
  const [reason, setReason] = useState("");
  const [action, setAction] = useState<"create" | "edit">("create");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const loadRequests = useCallback(async () => {
    try {
      const res = await getMySopRequests(token);
      setMyRequests(res.requests);
    } catch {
      // non-fatal
    }
  }, [token]);

  useEffect(() => {
    loadRequests();
  }, [loadRequests]);

  const handleCreate = async () => {
    setSubmitting(true);
    setError(null);
    setMessage(null);
    try {
      await createSop(token, { title: title.trim(), department, body: body.trim() });
      setTitle("");
      setBody("");
      setShowCreate(false);
      setMessage("SOP created.");
      onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create SOP");
    } finally {
      setSubmitting(false);
    }
  };

  const handleRequestAccess = async () => {
    setSubmitting(true);
    setError(null);
    setMessage(null);
    try {
      await createSopAccessRequest(token, {
        action,
        department,
        reason: reason.trim() || undefined,
      });
      setReason("");
      setShowRequest(false);
      setMessage("Access request submitted for review.");
      await loadRequests();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit request");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {sopAccess
            ? "You can author SOPs in your departments."
            : "Request permission to author SOPs."}
        </p>
        <div className="flex items-center gap-2">
          <Button type="button" variant="outline" size="sm" onClick={onRefresh}>
            <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
            Refresh
          </Button>
          {sopAccess ? (
            <Button type="button" size="sm" onClick={() => setShowCreate((v) => !v)}>
              New SOP
            </Button>
          ) : (
            <Button type="button" size="sm" onClick={() => setShowRequest((v) => !v)}>
              Request access
            </Button>
          )}
        </div>
      </div>

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

      {showCreate && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Create SOP</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="sop-title">Title</Label>
              <Input id="sop-title" value={title} onChange={(e) => setTitle(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="sop-dept">Department</Label>
              <Select value={department} onValueChange={setDepartment}>
                <SelectTrigger id="sop-dept">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="general">general</SelectItem>
                  <SelectItem value="underwriting">underwriting</SelectItem>
                  <SelectItem value="compliance">compliance</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="sop-body">Body</Label>
              <textarea
                id="sop-body"
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows={6}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
              />
            </div>
            <Button type="button" onClick={handleCreate} disabled={submitting || !title.trim() || !body.trim()}>
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create SOP"}
            </Button>
          </CardContent>
        </Card>
      )}

      {showRequest && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Request SOP authoring access</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="req-action">Action</Label>
              <Select value={action} onValueChange={(v) => setAction(v as "create" | "edit")}>
                <SelectTrigger id="req-action">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="create">create</SelectItem>
                  <SelectItem value="edit">edit</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="req-dept">Department</Label>
              <Select value={department} onValueChange={setDepartment}>
                <SelectTrigger id="req-dept">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="general">general</SelectItem>
                  <SelectItem value="underwriting">underwriting</SelectItem>
                  <SelectItem value="compliance">compliance</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="req-reason">Reason</Label>
              <Input id="req-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
            </div>
            <Button type="button" onClick={handleRequestAccess} disabled={submitting}>
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : "Submit request"}
            </Button>
          </CardContent>
        </Card>
      )}

      {myRequests.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">My access requests</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {myRequests.map((r) => (
              <div key={r.id} className="flex items-center justify-between gap-3 border-b border-border last:border-0 pb-2 last:pb-0">
                <p className="text-sm truncate">
                  {r.action} · {r.department}
                </p>
                <span className="text-xs text-muted-foreground">{r.status}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <div className="space-y-2">
        {sops.map((sop) => (
          <Card key={sop.id}>
            <CardContent className="p-4 space-y-1">
              <div className="flex items-center gap-2">
                <p className="text-sm font-medium">{sop.title}</p>
                <Badge variant="outline">{sop.department}</Badge>
                <span className="text-xs text-muted-foreground">v{sop.version}</span>
              </div>
              <p className="text-sm text-muted-foreground whitespace-pre-wrap">
                {sop.body.length > 280 ? `${sop.body.slice(0, 280)}…` : sop.body}
              </p>
            </CardContent>
          </Card>
        ))}
        {sops.length === 0 && (
          <p className="text-sm text-muted-foreground">No SOPs available.</p>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Onboard client dialog (Session 9, decision #2 — manual onboarding)
// ---------------------------------------------------------------------------

function OnboardClientDialog({
  open,
  onOpenChange,
  token,
  onOnboarded,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  token: string;
  onOnboarded: () => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [address, setAddress] = useState("");
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [postalCode, setPostalCode] = useState("");
  const [propertyType, setPropertyType] = useState("");
  const [caseNumber, setCaseNumber] = useState("");
  const [loanAmount, setLoanAmount] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const reset = () => {
    setEmail("");
    setPassword("");
    setFullName("");
    setAddress("");
    setCity("");
    setState("");
    setPostalCode("");
    setPropertyType("");
    setCaseNumber("");
    setLoanAmount("");
    setError(null);
    setMessage(null);
  };

  const handleSubmit = async () => {
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    setMessage(null);
    try {
      const result = await onboardClient(token, {
        email,
        password,
        full_name: fullName || undefined,
        address: address || undefined,
        city: city || undefined,
        state: state || undefined,
        postal_code: postalCode || undefined,
        property_type: propertyType || undefined,
        case_number: caseNumber || undefined,
        loan_amount: loanAmount ? Number(loanAmount) : undefined,
      });
      setMessage(
        `${result.message} (client #${result.client_id})` +
          (result.case_number ? ` — case ${result.case_number}` : "")
      );
      onOnboarded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to onboard client");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <UserPlus className="h-4 w-4" />
            Onboard a client
          </DialogTitle>
          <DialogDescription>
            Create the client account, optional property, and initial case.
            Same shape as the future CRM import path, so nothing differs later.
          </DialogDescription>
        </DialogHeader>

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

          <div className="space-y-1">
            <Label htmlFor="ob-email">Email *</Label>
            <Input
              id="ob-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="client@example.com"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ob-password">Password *</Label>
            <Input
              id="ob-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 8 characters"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ob-name">Full name</Label>
            <Input
              id="ob-name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          </div>

          <div className="rounded-md border border-border p-3 space-y-3">
            <p className="text-xs font-medium text-muted-foreground">
              Property (optional)
            </p>
            <div className="space-y-1">
              <Label htmlFor="ob-address">Address</Label>
              <Input
                id="ob-address"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
              />
            </div>
            <div className="grid grid-cols-3 gap-2">
              <div className="space-y-1">
                <Label htmlFor="ob-city" className="text-xs">City</Label>
                <Input id="ob-city" value={city} onChange={(e) => setCity(e.target.value)} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="ob-state" className="text-xs">State</Label>
                <Input id="ob-state" value={state} onChange={(e) => setState(e.target.value)} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="ob-zip" className="text-xs">ZIP</Label>
                <Input id="ob-zip" value={postalCode} onChange={(e) => setPostalCode(e.target.value)} />
              </div>
            </div>
            <div className="space-y-1">
              <Label htmlFor="ob-type" className="text-xs">Property type</Label>
              <Input
                id="ob-type"
                value={propertyType}
                onChange={(e) => setPropertyType(e.target.value)}
                placeholder="e.g. Single family"
              />
            </div>
          </div>

          <div className="rounded-md border border-border p-3 space-y-3">
            <p className="text-xs font-medium text-muted-foreground">
              Initial case (created when a property or loan amount is set)
            </p>
            <div className="space-y-1">
              <Label htmlFor="ob-case" className="text-xs">Case number (auto if blank)</Label>
              <Input
                id="ob-case"
                value={caseNumber}
                onChange={(e) => setCaseNumber(e.target.value)}
                placeholder="e.g. CAS-2026-9001"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="ob-loan" className="text-xs">Loan amount</Label>
              <Input
                id="ob-loan"
                type="number"
                value={loanAmount}
                onChange={(e) => setLoanAmount(e.target.value)}
                placeholder="e.g. 275000"
              />
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={handleSubmit}
            disabled={!email || password.length < 8 || submitting}
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : "Onboard client"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Collaboration tab (Phase F6 — client conversations)
// ---------------------------------------------------------------------------

function CollaborationTab({
  token,
  cases,
  onError,
}: {
  token: string;
  cases: StaffDashboardCase[];
  onError: (msg: string) => void;
}) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [subject, setSubject] = useState("");
  const [clientId, setClientId] = useState("");
  const [caseId, setCaseId] = useState("");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await getStaffConversations(token);
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

  const clientOptions = Array.from(
    new Map(
      cases.map((c) => [c.client_id, { id: c.client_id, name: c.client_name ?? `client #${c.client_id}` }])
    ).values()
  );

  const handleCreate = async () => {
    if (!subject.trim() || !clientId || creating) return;
    setCreating(true);
    try {
      await createStaffConversation(token, {
        subject: subject.trim(),
        client_id: Number(clientId),
        case_id: caseId ? Number(caseId) : null,
      });
      setSubject("");
      setClientId("");
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
          Conversations with clients assigned to you.
        </p>
        <Button type="button" size="sm" onClick={() => setShowCreate((v) => !v)}>
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
              <Label htmlFor="collab-subject">Subject</Label>
              <Input
                id="collab-subject"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder="e.g. Follow-up on documents"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="collab-client">Client</Label>
              <Select value={clientId} onValueChange={setClientId}>
                <SelectTrigger id="collab-client">
                  <SelectValue placeholder="Select a client" />
                </SelectTrigger>
                <SelectContent>
                  {clientOptions.map((c) => (
                    <SelectItem key={c.id} value={String(c.id)}>
                      {c.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {clientId && (
              <div className="space-y-1">
                <Label htmlFor="collab-case">Related case (optional)</Label>
                <Select value={caseId} onValueChange={setCaseId}>
                  <SelectTrigger id="collab-case">
                    <SelectValue placeholder="No case" />
                  </SelectTrigger>
                  <SelectContent>
                    {cases
                      .filter((c) => c.client_id === Number(clientId))
                      .map((c) => (
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
              disabled={!subject.trim() || !clientId || creating}
            >
              {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : "Start conversation"}
            </Button>
          </CardContent>
        </Card>
      )}

      <ConversationThread
        conversations={conversations}
        selfSenderType="staff"
        loadMessages={async (id) => (await getStaffConversationMessages(token, id)).messages}
        sendMessage={async (id, body) => {
          await sendStaffMessage(token, id, body);
        }}
        emptyLabel="No conversations with your clients yet."
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Staff page shell
// ---------------------------------------------------------------------------

export default function StaffPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [isStaff, setIsStaff] = useState(false);
  const [activeNavId, setActiveNavId] = useState("dashboard");
  const [data, setData] = useState<StaffDashboardResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [onboardOpen, setOnboardOpen] = useState(false);

  useEffect(() => {
    const t = getToken();
    const claims = t ? decodeToken(t) : null;
    if (!t || !claims || claims.audience !== "staff" || claims.role === "admin") {
      router.replace("/login");
      return;
    }
    setToken(t);
    setIsStaff(true);
  }, [router]);

  const load = useCallback(async () => {
    if (!token) return;
    setIsLoading(true);
    setError(null);
    try {
      setData(await getStaffDashboard(token));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dashboard");
    } finally {
      setIsLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (token) load();
  }, [token, load]);

  const handleLogout = useCallback(() => {
    clearToken();
    router.push("/login");
  }, [router]);

  if (!isStaff || !token) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <>
      <AppShell
        navGroups={NAV_GROUPS.staff}
      activeNavId={activeNavId}
      onNavigate={(id) => setActiveNavId(id)}
      brandTitle="Asto"
      brandSubtitle="Staff Workspace"
      headerTitle="Staff"
      headerSubtitle="Dashboard · Cases · Workflows · SOPs"
      headerActions={
        <div className="flex items-center gap-2">
          <Button type="button" size="sm" onClick={() => setOnboardOpen(true)}>
            <UserPlus className="h-4 w-4 mr-1.5" />
            Onboard client
          </Button>
          <Button asChild variant="outline" size="sm">
            <a href="/">
              <MessageSquare className="h-4 w-4 mr-2" />
              Ask Asto
            </a>
          </Button>
        </div>
      }
      user={{ name: "Staff", role: "staff" }}
      onSignOut={handleLogout}
    >
      <div className="max-w-5xl mx-auto px-4 py-8 flex-1 overflow-y-auto">
        {error && (
          <Alert variant="destructive" className="mb-4">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Error</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <Tabs value={activeNavId} onValueChange={setActiveNavId}>
          <TabsList className="grid w-full grid-cols-6">
            <TabsTrigger value="dashboard">Dashboard</TabsTrigger>
            <TabsTrigger value="cases">My Cases</TabsTrigger>
            <TabsTrigger value="tasks">Tasks</TabsTrigger>
            <TabsTrigger value="workflows">Workflows</TabsTrigger>
            <TabsTrigger value="sops">SOPs</TabsTrigger>
            <TabsTrigger value="collaboration">Collaboration</TabsTrigger>
          </TabsList>
          <TabsContent value="dashboard">
            <StaffDashboardTab data={data} isLoading={isLoading} onRefresh={load} />
          </TabsContent>
          <TabsContent value="cases">
            <MyCasesTab cases={data?.cases ?? []} token={token} onRefresh={load} />
          </TabsContent>
          <TabsContent value="tasks">
            <TasksTab workflows={data?.workflows ?? []} token={token} onRefresh={load} />
          </TabsContent>
          <TabsContent value="workflows">
            <WorkflowsTab workflows={data?.workflows ?? []} token={token} onRefresh={load} />
          </TabsContent>
          <TabsContent value="sops">
            <SopsTab
              sops={data?.sops ?? []}
              sopAccess={data?.sop_access ?? false}
              token={token}
              onRefresh={load}
            />
          </TabsContent>
          <TabsContent value="collaboration">
            <CollaborationTab token={token} cases={data?.cases ?? []} onError={setError} />
          </TabsContent>
        </Tabs>

        <footer className="border-t border-border py-4">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Sparkles className="w-3.5 h-3.5" />
            Asto — work is scoped to your departments and assigned clients.
          </div>
        </footer>
      </div>
    </AppShell>

    <OnboardClientDialog
      open={onboardOpen}
      onOpenChange={setOnboardOpen}
      token={token}
      onOnboarded={load}
    />
    </>
  );
}
