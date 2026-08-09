# AsTo Navigation & Information Architecture

> Phase 0 deliverable. Single source of truth for role-based navigation.
> The runtime config lives in `frontend/config/navigation.ts` and mirrors
> this document.

## 1. Guiding principle

Three genuinely different workspaces, one coherent product. The AI assistant
is the intelligence layer embedded in each workspace — never an isolated page.
Nav is **data-driven**: one config file per role, consumed by `AppShell`.

## 2. Role map

| Role (token) | Workspace | Route | Responsive |
|---|---|---|---|
| `admin` / `super_admin` | Admin Control Hub | `/admin` | Desktop-first |
| staff (loan_officer, underwriter, processor, compliance, viewer) | Process Staff Workspace | `/` | Desktop-first |
| client audience | Client Portal | `/client` | Mobile-optimized |

## 3. Admin navigation (`/admin`)

| Item | Purpose |
|---|---|
| Dashboard | Pending approvals, access requests, system activity, items needing intervention |
| Approval Queue | Unified inbox: documents, SOPs, access requests (reject requires reason) |
| Cases | All cases, reassignment, status events |
| Documents | Repository, upload, versions |
| Knowledge Base | Articles, docs, SOPs, FAQs, policies, archived; metadata + approval status |
| SOP Management | Lifecycle + version history + restore |
| Users | Create/disable users, roles, departments |
| Clients | Client records, cases, assignment, status |
| Roles & Permissions | Grouped permissions (Documents: View/Upload/Edit/Approve/Delete; Knowledge: View/Create/Edit/Publish/Archive) |
| Departments | Department → staff, roles, cases, SOPs, knowledge sources |
| Analytics | Usage, queries, approval throughput, gaps |
| Audit Log | Governance view of changes |
| Settings | Knowledge config, approval config, admin-enforced max session timeout |

## 4. Process Staff navigation (`/`)

| Item | Purpose |
|---|---|
| Dashboard | Operational: my cases, cases needing attention, overdue tasks, pending docs, active workflows, recent activity |
| My Cases | Assigned cases, filterable |
| Tasks | Derived from workflows + case_events (no separate task board yet) |
| Workflows | Active department workflows, advance actions |
| Documents | Per-case documents |
| SOPs | Department SOP library + Request Access flow |
| Knowledge | Department-relevant policies/FAQs |
| Collaboration | Case notes, activity |
| AI Assistant | Context-aware Q&A (global or per-case) |

## 5. Client navigation (`/client`)

| Item | Purpose |
|---|---|
| Home (Dashboard) | Status, action needed, documents, urgency, next step |
| My Case | Case details + timeline |
| Documents | Own approved docs + upload (pending→review) |
| Property | Properties + related docs |
| Messages | Read-only event feed from case_events (full inbox in Phase 5) |
| AI Assistant | Own-case Q&A |
| Help | Contact/guidance |

Clients never see: internal notes, SOPs, staff-only documents, admin screens,
restricted knowledge, or staff names beyond what a case explicitly exposes.

## 6. Navigation config contract

`frontend/config/navigation.ts` exports a `NAV_GROUPS` record keyed by role:

```ts
type Role = "admin" | "staff" | "client";
interface NavItem {
  id: string;
  label: string;
  icon: ReactNode;
  disabled?: boolean; // shown but not clickable until its phase lands
  badge?: number;     // static badge (e.g. count); a resolver may replace this later
}
interface NavGroup { title?: string; items: NavItem[]; }
const NAV_GROUPS: Record<Role, NavGroup[]> = { ... };
```

Rules:
- Icon + label are the only display fields; order = render order.
- Groups with a `title` render a small uppercase heading; untitled groups
  render items directly.
- Each item maps to a view id in its workspace; `AppShell` owns highlighting.
- Missing/incomplete views: item may be disabled (opacity + `aria-disabled`)
  until its phase lands, rather than hidden — keeps IA visible.
