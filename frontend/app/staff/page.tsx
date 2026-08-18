"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  Bell,
  Building2,
  Briefcase,
  CheckCircle2,
  FileText,
  Landmark,
  Loader2,
  MessageSquare,
  RefreshCw,
  Sparkles,
  Upload,
  UserPlus,
  Workflow as WorkflowIcon,
  XCircle,
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
  getStaffClients,
  staffUploadDocument,
  getStaffDocumentFile,
  getStaffTasks,
  createStaffTask,
  updateStaffTask,
  getStaffClient360,
  getWorkflowDefinitions,
  createWorkflowDefinition,
  deleteWorkflowDefinition,
  getMessageTemplates,
  createMessageTemplate,
  deleteMessageTemplate,
  getStaffAppointments,
  createStaffAppointment,
  logout,
  logoutAll,
  getNotifications,
  markNotificationRead,
  markAllNotificationsRead,
  StaffClient,
  StaffNotification,
  StaffDashboardCase,
  StaffDashboardResponse,
  StaffWorkflow,
  StaffSop,
  StaffTask,
  Client360,
  WorkflowDefinition,
  MessageTemplate,
  StaffAppointment,
  CaseNote,
  SopAccessRequest,
  Conversation,
} from "@/lib/api-client";
import { clearToken, decodeToken, getToken, isAdminRole, restoreSession } from "@/lib/auth";
import AppShell from "@/components/layout/AppShell";
import { NAV_GROUPS } from "@/config/navigation";
import ConversationThread from "@/components/messages/ConversationThread";
import SettingsModal from "@/components/settings/SettingsModal";
import { FileDropzone } from "@/components/upload/FileDropzone";
import { DocumentPreviewDialog } from "@/components/documents/DocumentPreviewDialog";
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
    { label: "Overdue workflows", value: data ? data.overdue_workflows.toLocaleString() : "—", hint: "past due date" },
    { label: "Overdue tasks", value: data ? data.overdue_tasks.toLocaleString() : "—", hint: "hand-assigned" },
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

      <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-5">
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
// Tasks tab (Phase L2 — real assigned tasks)
// ---------------------------------------------------------------------------

function taskStatusBadge(status: string) {
  switch (status) {
    case "completed":
      return <Badge className="bg-green-100 text-green-800 border-green-200">completed</Badge>;
    case "in_progress":
      return <Badge className="bg-yellow-100 text-yellow-800 border-yellow-200">in progress</Badge>;
    case "overdue":
      return <Badge className="bg-red-100 text-red-800 border-red-200">overdue</Badge>;
    default:
      return <Badge variant="outline">{status}</Badge>;
  }
}

function TasksTab({
  token,
  onError,
}: {
  token: string;
  onError: (message: string) => void;
}) {
  const [tasks, setTasks] = useState<StaffTask[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [caseId, setCaseId] = useState("");
  const [assigneeId, setAssigneeId] = useState("");
  const [dueAt, setDueAt] = useState("");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await getStaffTasks(token);
      setTasks(res.tasks);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to load tasks");
    } finally {
      setIsLoading(false);
    }
  }, [token, onError]);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async () => {
    if (!title.trim() || creating) return;
    setCreating(true);
    try {
      await createStaffTask(token, {
        title: title.trim(),
        description: description.trim() || null,
        case_id: caseId ? Number(caseId) : null,
        assignee_id: assigneeId ? Number(assigneeId) : null,
        due_at: dueAt ? new Date(dueAt).toISOString() : null,
      });
      setTitle("");
      setDescription("");
      setCaseId("");
      setAssigneeId("");
      setDueAt("");
      setShowCreate(false);
      await load();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to create task");
    } finally {
      setCreating(false);
    }
  };

  const handleComplete = async (task: StaffTask) => {
    try {
      await updateStaffTask(token, task.id, { status: "completed" });
      await load();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to complete task");
    }
  };

  const handleDelete = async (task: StaffTask) => {
    try {
      await updateStaffTask(token, task.id, { status: "overdue" });
      await load();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to update task");
    }
  };

  const openCount = tasks.filter((t) => t.status !== "completed" && t.status !== "overdue").length;
  const overdueCount = tasks.filter((t) => t.status === "overdue").length;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Assign and track tasks with teammates.
        </p>
        <div className="flex items-center gap-2">
          <Button type="button" variant="outline" size="sm" onClick={load}>
            <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
            Refresh
          </Button>
          <Button type="button" size="sm" onClick={() => setShowCreate((v) => !v)}>
            New task
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            {[
              { label: "Open tasks", value: openCount, hint: "pending or in progress" },
              { label: "Overdue", value: overdueCount, hint: "past due date" },
              { label: "Total tasks", value: tasks.length, hint: "all statuses" },
            ].map((s) => (
              <Card key={s.label}>
                <CardHeader className="pb-1">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    {s.label}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-2xl font-bold">{s.value.toLocaleString()}</p>
                  <p className="text-xs text-muted-foreground mt-1">{s.hint}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          {showCreate && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">New task</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="space-y-1">
                  <Label htmlFor="task-title">Title *</Label>
                  <Input
                    id="task-title"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="e.g. Collect signed deed"
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="task-desc">Description</Label>
                  <Input
                    id="task-desc"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                  />
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="space-y-1">
                    <Label htmlFor="task-case" className="text-xs">Case ID</Label>
                    <Input
                      id="task-case"
                      type="number"
                      value={caseId}
                      onChange={(e) => setCaseId(e.target.value)}
                      placeholder="optional"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="task-assignee" className="text-xs">Assignee user ID</Label>
                    <Input
                      id="task-assignee"
                      type="number"
                      value={assigneeId}
                      onChange={(e) => setAssigneeId(e.target.value)}
                      placeholder="optional"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="task-due" className="text-xs">Due date</Label>
                    <Input
                      id="task-due"
                      type="datetime-local"
                      value={dueAt}
                      onChange={(e) => setDueAt(e.target.value)}
                    />
                  </div>
                </div>
                <Button
                  type="button"
                  onClick={handleCreate}
                  disabled={!title.trim() || creating}
                >
                  {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create task"}
                </Button>
              </CardContent>
            </Card>
          )}

          {tasks.length === 0 ? (
            <Card>
              <CardContent className="p-6 text-center text-sm text-muted-foreground">
                <CheckCircle2 className="h-8 w-8 mx-auto mb-2 text-green-600" />
                No tasks yet — create one to get started.
              </CardContent>
            </Card>
          ) : (
            tasks.map((t) => (
              <Card key={t.id}>
                <CardContent className="p-4 flex items-start justify-between gap-4">
                  <div className="min-w-0 space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Briefcase className="h-4 w-4 text-muted-foreground" />
                      <p className="text-sm font-medium">{t.title}</p>
                      {taskStatusBadge(t.status)}
                    </div>
                    {t.description && (
                      <p className="text-sm text-muted-foreground whitespace-pre-wrap">
                        {t.description}
                      </p>
                    )}
                    <p className="text-xs text-muted-foreground">
                      {t.case_number ? `${t.case_number} · ` : ""}
                      {t.assignee_email ? `assigned to ${t.assignee_email}` : "unassigned"}
                      {t.due_at ? ` · due ${formatDate(t.due_at)}` : ""}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    {t.status !== "completed" && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => handleComplete(t)}
                      >
                        <CheckCircle2 className="h-3.5 w-3.5 mr-1.5" />
                        Complete
                      </Button>
                    )}
                    {t.status !== "overdue" && t.status !== "completed" && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDelete(t)}
                      >
                        Mark overdue
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </>
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
// Clients tab (Phase G4) + staff upload dialog (Phase G5)
// ---------------------------------------------------------------------------

function docStatusBadge(status: string) {
  switch (status) {
    case "approved":
      return <Badge className="bg-green-100 text-green-800 border-green-200">approved</Badge>;
    case "pending":
      return <Badge className="bg-yellow-100 text-yellow-800 border-yellow-200">pending</Badge>;
    case "rejected":
      return <Badge className="bg-red-100 text-red-800 border-red-200">rejected</Badge>;
    default:
      return <Badge variant="outline">{status}</Badge>;
  }
}

function StaffUploadDialog({
  open,
  onOpenChange,
  token,
  client,
  onUploaded,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  token: string;
  client: StaffClient | null;
  onUploaded: () => void;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [propertyId, setPropertyId] = useState<string>("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [progress, setProgress] = useState<{ done: number; total: number; name: string } | null>(null);

  const reset = () => {
    setFiles([]);
    setPropertyId("");
    setError(null);
    setMessage(null);
    setProgress(null);
  };

  const handleUpload = async () => {
    if (files.length === 0 || !client || uploading) return;
    setUploading(true);
    setError(null);
    setMessage(null);
    try {
      let uploadedCount = 0;
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        setProgress({ done: i, total: files.length, name: file.name });
        await staffUploadDocument(
          file,
          token,
          client.id,
          propertyId ? Number(propertyId) : null
        );
        uploadedCount += 1;
      }
      setProgress({ done: files.length, total: files.length, name: "" });
      setMessage(
        `${uploadedCount} document${uploadedCount === 1 ? "" : "s"} queued for indexing.`
      );
      onUploaded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      setProgress(null);
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
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Upload className="h-4 w-4" />
            Upload document for {client?.full_name || client?.email || "client"}
          </DialogTitle>
          <DialogDescription>
            The document enters the admin review queue as pending. It becomes
            searchable only after an admin approves it.
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
              <AlertTitle>Uploaded</AlertTitle>
              <AlertDescription>{message}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-1">
            <Label htmlFor="su-file">Files *</Label>
            <FileDropzone
              files={files}
              onFilesChange={setFiles}
              disabled={uploading}
              label="Drag & drop documents here, or click to browse"
              hint="Multiple files are uploaded one at a time."
            />
          </div>
          {progress && (
            <p className="text-sm text-muted-foreground">
              {progress.name
                ? `Uploading "${progress.name}" (${progress.done + 1} of ${progress.total})…`
                : `Uploading ${progress.total} file${progress.total === 1 ? "" : "s"}…`}
            </p>
          )}
          {client && client.properties.length > 0 && (
            <div className="space-y-1">
              <Label htmlFor="su-property">Property (optional)</Label>
              <Select value={propertyId} onValueChange={setPropertyId}>
                <SelectTrigger id="su-property">
                  <SelectValue placeholder="No property" />
                </SelectTrigger>
                <SelectContent>
                  {client.properties.map((p) => (
                    <SelectItem key={p.id} value={String(p.id)}>
                      {[p.address, p.city, p.state].filter(Boolean).join(", ") || `Property #${p.id}`}
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
            {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : `Upload ${files.length > 0 ? `${files.length} file${files.length === 1 ? "" : "s"} for review` : "for review"}`}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ClientsTab({
  token,
  onError,
}: {
  token: string;
  onError: (message: string) => void;
}) {
  const [clients, setClients] = useState<StaffClient[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [uploadClient, setUploadClient] = useState<StaffClient | null>(null);
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [view360, setView360] = useState<StaffClient | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await getStaffClients(token);
      setClients(res.clients);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to load clients");
    } finally {
      setIsLoading(false);
    }
  }, [token, onError]);

  useEffect(() => {
    load();
  }, [load]);

  if (view360) {
    return (
      <Client360Tab
        client={view360}
        token={token}
        onBack={() => setView360(null)}
        onError={onError}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Your assigned clients — properties, cases, and documents with review status.
        </p>
        <Button type="button" variant="outline" size="sm" onClick={load}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
          Refresh
        </Button>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : clients.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center">
            <Building2 className="h-8 w-8 mx-auto mb-2 text-muted-foreground" />
            <p className="font-medium">No assigned clients</p>
            <p className="text-sm text-muted-foreground">
              Clients assigned to you will appear here.
            </p>
          </CardContent>
        </Card>
      ) : (
        clients.map((client) => (
          <Card key={client.id}>
            <CardContent className="p-5 space-y-4">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <Building2 className="w-4 h-4 text-muted-foreground" />
                    <p className="font-medium truncate">
                      {client.full_name || client.email}
                    </p>
                  </div>
                  <p className="text-xs text-muted-foreground">{client.email}</p>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setView360(client)}
                  >
                    <Briefcase className="h-3.5 w-3.5 mr-1.5" />
                    360 view
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    onClick={() => setUploadClient(client)}
                  >
                    <Upload className="h-3.5 w-3.5 mr-1.5" />
                    Upload document
                  </Button>
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                    Properties
                  </p>
                  {client.properties.length === 0 ? (
                    <p className="text-xs text-muted-foreground">None</p>
                  ) : (
                    client.properties.map((p) => (
                      <div key={p.id} className="text-sm mb-1">
                        {[p.address, p.city, p.state].filter(Boolean).join(", ") ||
                          `Property #${p.id}`}
                      </div>
                    ))
                  )}
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                    Cases
                  </p>
                  {client.cases.length === 0 ? (
                    <p className="text-xs text-muted-foreground">None</p>
                  ) : (
                    client.cases.map((c) => (
                      <div key={c.id} className="flex items-center gap-2 text-sm mb-1">
                        <Landmark className="h-3.5 w-3.5 text-muted-foreground" />
                        <span className="truncate">{c.case_number}</span>
                        <span className="text-xs text-muted-foreground">
                          {c.status}
                        </span>
                      </div>
                    ))
                  )}
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                    Documents
                  </p>
                  {client.documents.length === 0 ? (
                    <p className="text-xs text-muted-foreground">None</p>
                  ) : (
                    client.documents.map((d) => (
                      <div
                        key={d.id}
                        className="flex items-center gap-2 text-sm mb-1 min-w-0"
                      >
                        <FileText className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
                        <span className="truncate">{d.title}</span>
                        <span className="text-xs text-muted-foreground flex-shrink-0">
                          v{d.version}
                        </span>
                        {docStatusBadge(d.approval_status)}
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-6 px-1.5 text-xs flex-shrink-0"
                          onClick={() => setPreviewId(d.id)}
                        >
                          <FileText className="h-3 w-3 mr-1" />
                          View
                        </Button>
                        {d.approval_status === "rejected" && (
                          <Button
                            type="button"
                            size="sm"
                            className="h-6 px-2 text-xs flex-shrink-0"
                            onClick={() => setUploadClient(client)}
                          >
                            <Upload className="h-3 w-3 mr-1" />
                            Upload corrected version
                          </Button>
                        )}
                      </div>
                    ))
                  )}
                  {client.documents.some((d) => d.approval_status === "rejected") && (
                    <div className="space-y-1.5 mt-2 border-t border-dashed pt-2">
                      {client.documents
                        .filter((d) => d.approval_status === "rejected")
                        .map((d) => (
                          <p key={d.id} className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2">
                            &ldquo;{d.title}&rdquo; was rejected
                            {d.rejection_reason ? `: ${d.rejection_reason}` : ""}
                            {d.rejected_at ? ` (${formatDate(d.rejected_at)})` : ""}
                          </p>
                        ))}
                    </div>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        ))
      )}

      <StaffUploadDialog
        open={uploadClient != null}
        onOpenChange={(open) => !open && setUploadClient(null)}
        token={token}
        client={uploadClient}
        onUploaded={load}
      />

      <DocumentPreviewDialog
        open={previewId != null}
        onOpenChange={(open) => !open && setPreviewId(null)}
        items={clients
          .flatMap((c) => c.documents)
          .map((d) => ({ id: d.id, title: d.title }))}
        initialId={previewId ?? 0}
        fetchBlob={(id) => getStaffDocumentFile(id, token)}
        loadingLabel="Loading document…"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Client 360 view (Phase L1 — everything about a client on one screen)
// ---------------------------------------------------------------------------

function Client360Tab({
  client,
  token,
  onBack,
  onError,
}: {
  client: StaffClient;
  token: string;
  onBack: () => void;
  onError: (message: string) => void;
}) {
  const [data, setData] = useState<Client360 | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      setData(await getStaffClient360(token, client.id));
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to load client 360");
    } finally {
      setIsLoading(false);
    }
  }, [token, client.id, onError]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="min-w-0">
          <Button type="button" variant="ghost" size="sm" onClick={onBack} className="mb-1">
            ← Back to clients
          </Button>
          <h2 className="text-lg font-semibold truncate">
            {client.full_name || client.email}
          </h2>
          <p className="text-xs text-muted-foreground">{client.email}</p>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={load}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
          Refresh
        </Button>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : data ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Properties</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {data.properties.length === 0 ? (
                <p className="text-sm text-muted-foreground">None</p>
              ) : (
                data.properties.map((p) => (
                  <div key={p.id} className="text-sm">
                    {[p.address, p.city, p.state].filter(Boolean).join(", ") ||
                      `Property #${p.id}`}
                    {p.property_type ? ` · ${p.property_type}` : ""}
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Documents</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {data.documents.length === 0 ? (
                <p className="text-sm text-muted-foreground">None</p>
              ) : (
                data.documents.map((d) => (
                  <div key={d.id} className="flex items-center gap-2 text-sm">
                    <FileText className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
                    <span className="truncate">{d.title}</span>
                    <span className="text-xs text-muted-foreground flex-shrink-0">
                      v{d.version}
                    </span>
                    {docStatusBadge(d.approval_status)}
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <Card className="lg:col-span-2">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Cases & timeline</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {data.cases.length === 0 ? (
                <p className="text-sm text-muted-foreground">No cases.</p>
              ) : (
                data.cases.map((c) => (
                  <div key={c.id} className="rounded-md border border-border p-3 space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-medium">{c.case_number}</p>
                      <Badge variant="outline">{c.status}</Badge>
                    </div>
                    {c.loan_amount != null && (
                      <p className="text-sm font-semibold">{formatMoney(c.loan_amount)}</p>
                    )}
                    <div className="space-y-1 border-l-2 border-border pl-3">
                      {c.timeline.length === 0 ? (
                        <p className="text-xs text-muted-foreground">No events yet.</p>
                      ) : (
                        c.timeline.map((e, i) => (
                          <div key={i} className="text-xs">
                            <span className="font-medium">{e.status}</span>
                            {e.note ? ` — ${e.note}` : ""}
                            {e.created_at ? ` · ${formatDate(e.created_at)}` : ""}
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <Card className="lg:col-span-2">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Recent conversations</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {data.conversations.length === 0 ? (
                <p className="text-sm text-muted-foreground">None.</p>
              ) : (
                data.conversations.map((cv) => (
                  <div key={cv.id} className="text-sm flex items-center justify-between gap-2">
                    <span className="truncate">{cv.subject}</span>
                    <span className="text-xs text-muted-foreground flex-shrink-0">
                      {formatDate(cv.updated_at)}
                    </span>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Workflow definitions (Phase L4)
// ---------------------------------------------------------------------------

function WorkflowDefinitionsTab({
  token,
  isAdmin,
  onError,
}: {
  token: string;
  isAdmin: boolean;
  onError: (message: string) => void;
}) {
  const [definitions, setDefinitions] = useState<WorkflowDefinition[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [stages, setStages] = useState("");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await getWorkflowDefinitions(token);
      setDefinitions(res.workflow_definitions);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to load workflow definitions");
    } finally {
      setIsLoading(false);
    }
  }, [token, onError]);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async () => {
    if (!name.trim() || creating) return;
    setCreating(true);
    try {
      await createWorkflowDefinition(token, {
        name: name.trim(),
        description: description.trim() || null,
        stages: stages
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      });
      setName("");
      setDescription("");
      setStages("");
      setShowCreate(false);
      await load();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to create definition");
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteWorkflowDefinition(token, id);
      await load();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to delete definition");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Config-driven workflow definitions.
        </p>
        <div className="flex items-center gap-2">
          <Button type="button" variant="outline" size="sm" onClick={load}>
            <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
            Refresh
          </Button>
          {isAdmin && (
            <Button type="button" size="sm" onClick={() => setShowCreate((v) => !v)}>
              New definition
            </Button>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <>
          {showCreate && isAdmin && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">New workflow definition</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="space-y-1">
                  <Label htmlFor="wd-name">Name *</Label>
                  <Input id="wd-name" value={name} onChange={(e) => setName(e.target.value)} />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="wd-desc">Description</Label>
                  <Input
                    id="wd-desc"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="wd-stages">Stages (comma-separated)</Label>
                  <Input
                    id="wd-stages"
                    value={stages}
                    onChange={(e) => setStages(e.target.value)}
                    placeholder="e.g. intake, underwriting, closing"
                  />
                </div>
                <Button
                  type="button"
                  onClick={handleCreate}
                  disabled={!name.trim() || creating}
                >
                  {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create definition"}
                </Button>
              </CardContent>
            </Card>
          )}

          {definitions.length === 0 ? (
            <Card>
              <CardContent className="p-6 text-center text-sm text-muted-foreground">
                No workflow definitions yet.
              </CardContent>
            </Card>
          ) : (
            definitions.map((d) => (
              <Card key={d.id}>
                <CardContent className="p-4 flex items-start justify-between gap-4">
                  <div className="min-w-0 space-y-1">
                    <div className="flex items-center gap-2">
                      <WorkflowIcon className="h-4 w-4 text-muted-foreground" />
                      <p className="text-sm font-medium">{d.name}</p>
                      <Badge variant="outline">{d.stages.length} stages</Badge>
                    </div>
                    {d.description && (
                      <p className="text-sm text-muted-foreground">{d.description}</p>
                    )}
                    <p className="text-xs text-muted-foreground">
                      {d.stages.join(" → ")}
                    </p>
                  </div>
                  {isAdmin && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDelete(d.id)}
                    >
                      Deactivate
                    </Button>
                  )}
                </CardContent>
              </Card>
            ))
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Message templates (Phase L5)
// ---------------------------------------------------------------------------

function MessageTemplatesTab({
  token,
  onError,
}: {
  token: string;
  onError: (message: string) => void;
}) {
  const [templates, setTemplates] = useState<MessageTemplate[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [department, setDepartment] = useState("general");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await getMessageTemplates(token);
      setTemplates(res.message_templates);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to load message templates");
    } finally {
      setIsLoading(false);
    }
  }, [token, onError]);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async () => {
    if (!name.trim() || !body.trim() || creating) return;
    setCreating(true);
    try {
      await createMessageTemplate(token, {
        name: name.trim(),
        body: body.trim(),
        department,
      });
      setName("");
      setBody("");
      setShowCreate(false);
      await load();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to create template");
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteMessageTemplate(token, id);
      await load();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to delete template");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Reusable replies for common client questions.
        </p>
        <Button type="button" size="sm" onClick={() => setShowCreate((v) => !v)}>
          New template
        </Button>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <>
          {showCreate && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">New message template</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="space-y-1">
                  <Label htmlFor="mt-name">Name *</Label>
                  <Input id="mt-name" value={name} onChange={(e) => setName(e.target.value)} />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="mt-body">Body *</Label>
                  <textarea
                    id="mt-body"
                    value={body}
                    onChange={(e) => setBody(e.target.value)}
                    rows={4}
                    className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="mt-dept">Department</Label>
                  <Select value={department} onValueChange={setDepartment}>
                    <SelectTrigger id="mt-dept">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="general">general</SelectItem>
                      <SelectItem value="underwriting">underwriting</SelectItem>
                      <SelectItem value="compliance">compliance</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <Button
                  type="button"
                  onClick={handleCreate}
                  disabled={!name.trim() || !body.trim() || creating}
                >
                  {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create template"}
                </Button>
              </CardContent>
            </Card>
          )}

          {templates.length === 0 ? (
            <Card>
              <CardContent className="p-6 text-center text-sm text-muted-foreground">
                No message templates yet.
              </CardContent>
            </Card>
          ) : (
            templates.map((t) => (
              <Card key={t.id}>
                <CardContent className="p-4 flex items-start justify-between gap-4">
                  <div className="min-w-0 space-y-1">
                    <div className="flex items-center gap-2">
                      <MessageSquare className="h-4 w-4 text-muted-foreground" />
                      <p className="text-sm font-medium">{t.name}</p>
                      <Badge variant="outline">{t.department}</Badge>
                    </div>
                    <p className="text-sm text-muted-foreground whitespace-pre-wrap">
                      {t.body.length > 240 ? `${t.body.slice(0, 240)}…` : t.body}
                    </p>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => handleDelete(t.id)}
                  >
                    Delete
                  </Button>
                </CardContent>
              </Card>
            ))
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Calendar / appointments (Phase L6)
// ---------------------------------------------------------------------------

function AppointmentsTab({
  token,
  onError,
}: {
  token: string;
  onError: (message: string) => void;
}) {
  const [appointments, setAppointments] = useState<StaffAppointment[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [startAt, setStartAt] = useState("");
  const [endAt, setEndAt] = useState("");
  const [department, setDepartment] = useState("general");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await getStaffAppointments(token);
      setAppointments(res.appointments);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to load appointments");
    } finally {
      setIsLoading(false);
    }
  }, [token, onError]);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async () => {
    if (!title.trim() || !startAt || !endAt || creating) return;
    setCreating(true);
    try {
      await createStaffAppointment(token, {
        title: title.trim(),
        description: description.trim() || null,
        start_at: new Date(startAt).toISOString(),
        end_at: new Date(endAt).toISOString(),
        department,
      });
      setTitle("");
      setDescription("");
      setStartAt("");
      setEndAt("");
      setShowCreate(false);
      await load();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to create appointment");
    } finally {
      setCreating(false);
    }
  };

  const sorted = [...appointments].sort((a, b) => {
    const ta = a.start_at ? new Date(a.start_at).getTime() : 0;
    const tb = b.start_at ? new Date(b.start_at).getTime() : 0;
    return ta - tb;
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Schedule and track appointments.
        </p>
        <Button type="button" size="sm" onClick={() => setShowCreate((v) => !v)}>
          New appointment
        </Button>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <>
          {showCreate && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">New appointment</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="space-y-1">
                  <Label htmlFor="apt-title">Title *</Label>
                  <Input
                    id="apt-title"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="e.g. Closing at title office"
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="apt-desc">Description</Label>
                  <Input
                    id="apt-desc"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                  />
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-1">
                    <Label htmlFor="apt-start">Start *</Label>
                    <Input
                      id="apt-start"
                      type="datetime-local"
                      value={startAt}
                      onChange={(e) => setStartAt(e.target.value)}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="apt-end">End *</Label>
                    <Input
                      id="apt-end"
                      type="datetime-local"
                      value={endAt}
                      onChange={(e) => setEndAt(e.target.value)}
                    />
                  </div>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="apt-dept">Department</Label>
                  <Select value={department} onValueChange={setDepartment}>
                    <SelectTrigger id="apt-dept">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="general">general</SelectItem>
                      <SelectItem value="underwriting">underwriting</SelectItem>
                      <SelectItem value="compliance">compliance</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <Button
                  type="button"
                  onClick={handleCreate}
                  disabled={!title.trim() || !startAt || !endAt || creating}
                >
                  {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create appointment"}
                </Button>
              </CardContent>
            </Card>
          )}

          {sorted.length === 0 ? (
            <Card>
              <CardContent className="p-6 text-center text-sm text-muted-foreground">
                No appointments scheduled.
              </CardContent>
            </Card>
          ) : (
            sorted.map((a) => (
              <Card key={a.id}>
                <CardContent className="p-4 flex items-center justify-between gap-4">
                  <div className="min-w-0 space-y-1">
                    <p className="text-sm font-medium">{a.title}</p>
                    {a.description && (
                      <p className="text-sm text-muted-foreground truncate">{a.description}</p>
                    )}
                    <p className="text-xs text-muted-foreground">
                      {a.start_at ? formatDate(a.start_at) : "—"}
                      {a.end_at ? ` → ${formatDate(a.end_at)}` : ""}
                      {" · "}
                      {a.department}
                    </p>
                  </div>
                  <Badge variant="outline">{a.status}</Badge>
                </CardContent>
              </Card>
            ))
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Notifications dialog (Phase G5)
// ---------------------------------------------------------------------------

function NotificationsDialog({
  open,
  onOpenChange,
  token,
  onCountChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  token: string;
  onCountChange: (count: number) => void;
}) {
  const [notifications, setNotifications] = useState<StaffNotification[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await getNotifications(token);
      setNotifications(res.notifications);
      onCountChange(res.unread_count);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load notifications");
    } finally {
      setIsLoading(false);
    }
  }, [token, onCountChange]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const handleMarkRead = async (id: number) => {
    try {
      await markNotificationRead(id, token);
      await load();
    } catch {
      // non-fatal
    }
  };

  const handleMarkAllRead = async () => {
    try {
      await markAllNotificationsRead(token);
      await load();
    } catch {
      // non-fatal
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Bell className="h-4 w-4" />
            Notifications
          </DialogTitle>
          <DialogDescription>
            Review outcomes and updates.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          {error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <div className="flex justify-end">
            <Button type="button" variant="ghost" size="sm" onClick={handleMarkAllRead}>
              Mark all as read
            </Button>
          </div>
          {isLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : notifications.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4 text-center">
              No notifications yet.
            </p>
          ) : (
            <div className="space-y-2 max-h-80 overflow-y-auto">
              {notifications.map((n) => (
                <button
                  key={n.id}
                  type="button"
                  onClick={() => !n.is_read && handleMarkRead(n.id)}
                  className={`w-full text-left border border-border rounded-lg p-3 ${
                    n.is_read ? "opacity-60" : ""
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-sm">{n.title}</span>
                    <span className="text-xs text-muted-foreground">
                      {formatDate(n.created_at)}
                    </span>
                  </div>
                  {n.body && <p className="text-xs text-muted-foreground mt-1">{n.body}</p>}
                </button>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
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
  const [userName, setUserName] = useState<string | null>(null);
  const [userRole, setUserRole] = useState<string | null>(null);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const refreshNotifications = useCallback(async () => {
    if (!token) return;
    try {
      const res = await getNotifications(token);
      setUnreadCount(res.unread_count);
    } catch {
      // non-fatal
    }
  }, [token]);

  useEffect(() => {
    if (token) {
      refreshNotifications();
      const interval = setInterval(refreshNotifications, 60000);
      return () => clearInterval(interval);
    }
  }, [token, refreshNotifications]);

  useEffect(() => {
    let mounted = true;
    restoreSession().then((t) => {
      if (!mounted) return;
      const claims = t ? decodeToken(t) : null;
      if (!t || !claims || claims.audience !== "staff") {
        router.replace("/login");
        return;
      }
      if (isAdminRole(claims.role)) {
        router.replace("/admin");
        return;
      }
      setToken(t);
      setUserName(claims.name ?? claims.sub ?? null);
      setUserRole(claims.role ?? null);
      setIsStaff(true);
    });
    return () => {
      mounted = false;
    };
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
    logout();
    clearToken();
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
      user={{ name: userName ?? "Staff", role: userRole ?? "Staff" }}
      onSignOut={handleLogout}
      onSettings={() => setSettingsOpen(true)}
      onNotifications={() => setNotificationsOpen(true)}
      notificationCount={unreadCount}
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
          <TabsList className="grid w-full grid-cols-10">
            <TabsTrigger value="dashboard">Dashboard</TabsTrigger>
            <TabsTrigger value="clients">Clients</TabsTrigger>
            <TabsTrigger value="cases">My Cases</TabsTrigger>
            <TabsTrigger value="tasks">Tasks</TabsTrigger>
            <TabsTrigger value="workflows">Workflows</TabsTrigger>
            <TabsTrigger value="definitions">Definitions</TabsTrigger>
            <TabsTrigger value="templates">Templates</TabsTrigger>
            <TabsTrigger value="appointments">Calendar</TabsTrigger>
            <TabsTrigger value="sops">SOPs</TabsTrigger>
            <TabsTrigger value="collaboration">Collab</TabsTrigger>
          </TabsList>
          <TabsContent value="dashboard">
            <StaffDashboardTab data={data} isLoading={isLoading} onRefresh={load} />
          </TabsContent>
          <TabsContent value="clients">
            <ClientsTab token={token} onError={setError} />
          </TabsContent>
          <TabsContent value="cases">
            <MyCasesTab cases={data?.cases ?? []} token={token} onRefresh={load} />
          </TabsContent>
          <TabsContent value="tasks">
            <TasksTab token={token} onError={setError} />
          </TabsContent>
          <TabsContent value="workflows">
            <WorkflowsTab workflows={data?.workflows ?? []} token={token} onRefresh={load} />
          </TabsContent>
          <TabsContent value="definitions">
            <WorkflowDefinitionsTab
              token={token}
              isAdmin={isAdminRole(userRole ?? "")}
              onError={setError}
            />
          </TabsContent>
          <TabsContent value="templates">
            <MessageTemplatesTab token={token} onError={setError} />
          </TabsContent>
          <TabsContent value="appointments">
            <AppointmentsTab token={token} onError={setError} />
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

    <NotificationsDialog
      open={notificationsOpen}
      onOpenChange={setNotificationsOpen}
      token={token}
      onCountChange={setUnreadCount}
    />

    <SettingsModal
      open={settingsOpen}
      onOpenChange={setSettingsOpen}
      user={{ name: userName ?? "Staff", role: userRole ?? "Staff" }}
      onSignOut={handleLogout}
      onSignOutAll={handleLogoutAll}
    />
    </>
  );
}
