# AsTo Design System & State Machines

> Phase 0 deliverable. Companion to `docs/architecture/dual_path_assistant.md`.
> This document is the single source of truth for visual tokens, components,
> interaction patterns, and page states across all three role workspaces.

## 1. Brand & Visual Identity

- **Branding: Indigo/Neutral (retained).** No rebrand. `Asto` wordmark.
- **Tone:** professional enterprise platform — trust, accuracy, security,
  operational efficiency. Financial/property/case-management appropriate.
- **Principle:** no decorative UI, no chart-dashboards for their own sake.
  Every component must answer *"what user problem does this solve?"*

## 2. Design Tokens

Tokens come from `frontend/styles/globals.css` (CSS variables in `:root` /
`.dark`). The shadcn/ui variables are the token source of truth.

| Token | Variable | Usage |
|---|---|---|
| Background | `--background` | App canvas |
| Foreground | `--foreground` | Primary text |
| Card | `--card` / `--card-foreground` | Containers |
| Primary | `--primary` / `--primary-foreground` | Brand indigo, key actions |
| Secondary | `--secondary` / `--secondary-foreground` | Selected nav, muted fills |
| Muted | `--muted` / `--muted-foreground` | De-emphasized UI |
| Destructive | `--destructive` / `--destructive-foreground` | Errors, reject, delete |
| Border | `--border` | Hairlines, dividers |
| Ring | `--ring` | Focus rings |
| Radius | `--radius` | 0.5rem default |

### Semantic status colors (badges / status indicators)

| Status | Color | Meaning |
|---|---|---|
| Success / Approved / Done / Active | `emerald` | Positive, complete |
| Warning / Pending / In review / Attention | `amber` | Needs attention |
| Destructive / Rejected / Overdue | `red` | Negative, blocked |
| Secondary / Submitted / In progress | muted | Neutral, in flight |
| Outline / default | neutral | Unclassified |

These are applied via the `Badge` `variant` prop (`default`, `secondary`,
`destructive`, `outline`, `success`, `warning`).

## 3. Typography

- Font stack inherited from `globals.css` (system + Inter). Single weight axis
  (font-medium / font-semibold / font-bold) — no exotic typefaces.
- Hierarchy via size + weight, not color alone.
  - Page title: `text-2xl font-bold`
  - Section title: `text-base font-semibold`
  - Body: `text-sm`
  - Meta / captions: `text-xs text-muted-foreground`
- Contrast: minimum AA for body text; `muted-foreground` reserved for
  supplementary text, never for essential information.

## 4. Spacing & Layout

- Scale: 1 / 2 / 3 / 4 / 6 / 8 / 12 / 16 (Tailwind default spacing).
- Page gutter: `p-6` on desktop, `px-4` on mobile.
- Max content width: `max-w-6xl` (management views), `max-w-3xl`
  (conversational views).
- Vertical rhythm: `space-y-6` between top-level blocks, `space-y-3` inside
  cards.

## 5. App Shell

### Layout anatomy (all roles)

```
┌────────────┬────────────────────────────────────────────┐
│ Sidebar    │ Header (contextual title + actions + notif) │
│ (role nav) ├────────────────────────────────────────────┤
│            │ Main content                                │
│            │                                             │
└────────────┴────────────────────────────────────────────┘
```

### Responsive strategy

- **Client Portal: mobile-optimized.** Sidebar becomes a bottom tab bar on
  `< md`; header shrinks. Content stacks.
- **Staff & Admin: desktop-first.** Sidebar persists (collapsible to icon
  rail); tablet/mobile degrade gracefully (drawer + hamburger), but the
  primary workflows are desktop.

### Sidebar rules

- Nav is **data-driven** from `frontend/config/navigation.ts` (single source
  of truth, per-role).
- Active item is highlighted with `variant="secondary"`.
- Badges may appear on nav items (e.g. pending approvals count).
- Brand block at top; profile + settings + sign-out at bottom.
- Collapse state persisted per user (`asto_sidebar_collapsed`).

### Header rules

- Left: contextual title + optional breadcrumb / sub-caption.
- Right: notifications bell (with unread dot/count), avatar menu
  (profile, settings, sign out).
- Header is sticky; `backdrop-blur` over content.

## 6. Core Components

All from `frontend/components/ui/` (shadcn/ui). Usage contracts:

| Component | When to use | Notes |
|---|---|---|
| `Button` | Primary action / navigation | Variants: `default`, `secondary`, `outline`, `ghost`, `destructive`; sizes `sm`/`default`/`icon` |
| `Card` | Grouped related content | `CardHeader` (title) + `CardContent`; avoid nesting deep |
| `Badge` | Short status/label | See status colors §2 |
| `Tabs` | Peer views (case workspace tabs) | `TabsList` labels, `TabsContent` panels |
| `Dialog` | Focused task (form, preview, confirm) | `DialogContent` capped width; `DialogFooter` for actions |
| `AlertDialog` | **Destructive / irreversible confirm** | Must confirm clears, deletes, rejections |
| `Alert` | Inline page/flow errors or info | `destructive` for errors |
| `Input` / `Textarea` / `Select` | Forms | Always paired with `Label` |
| `ScrollArea` | Constrained scroll regions | Notes lists, chat history |
| `Skeleton` | Loading placeholders | Never full-page spinner if data is partially available |
| `Toast` / `Toaster` | Transient success/error feedback | Non-blocking |

### Loading buttons

- `Button` shows `Loader2 animate-spin` + disables while a mutation runs.
- Never allow double-submit: disable while `busyId === item.id`.

## 7. Status Indicators (spec §5)

Case stages are rendered as a **timeline**, not a score:

```
Application → Verification → Processing → Review → Approval → Closing → Completed
```

- **Completed:** filled node, success tone.
- **Current:** ringed/highlighted node, primary tone.
- **Pending:** muted outline.
- **Blocked:** destructive tone + reason.
- **Requires client action:** explicit badge with the action verb.
- Do **not** imply a deadline unless the system actually stores one.

Stage names are configurable by Admin (Phase 4); the renderer is data-driven.

## 8. Urgency Meter (spec §6)

Not a decorative score. A structured alert:

```
Urgency: High          Reason: Document required before Aug 12
                       Related: Case #204 · Due: Aug 12 · Action: Upload paystub
```

- Levels: `Normal` / `Attention` / `Urgent` (default `Normal`, no alarm).
- Computed from real data (due date, missing required documents), never
  hardcoded.
- Rendered via `Alert` (info/warning/destructive) or a dedicated card.

## 9. State Machines (spec §25)

Every major page must implement all of: loading, empty, error, success,
permission-denied, no-results, partial. Define per page:

### List pages (Documents, Cases, Approvals, Users)
- `loading` → `Skeleton` rows or centered `Loader2` (short-lived only)
- `empty` → friendly empty state with a call-to-action (never blank card rows)
- `error` → destructive `Alert` with retry
- `success` → data rows; `partial` → rows + notice of what couldn't load

### Detail / workspace pages (Case Workspace)
- `loading` → skeleton layout matching the tab structure
- `error` → destructive alert + retry
- `permission-denied` → explicit "You don't have access to this case" state
  (never a 500, never an empty look-alike)
- `empty` → per-tab empty states ("No documents yet", "No notes yet")

### Forms / mutations
- `idle` → `submitting` (disabled + spinner) → `success` (toast + clear
  form) | `error` (inline alert, keep user input)

### Chat (spec §19)
- `idle` → `processing` → `searching` → `ranking` → `packaging` → `done`
- `no-answer` → explicit "I couldn't find this in your available sources"
  with suggestion to upload/contact
- `error` → destructive inline state with retry
- Regenerate in place; never duplicate the turn.

### Offline / network failure
- Detect `fetch` failure vs API 4xx/5xx; surface distinct copy.
- Retry action always available.

## 10. Confirmation & Destructive Actions

- Permanent deletions, clear-history, rejections, overwrites → `AlertDialog`.
- Copy states *what will happen* ("This clears the current chat history from
  this browser").
- Destructive buttons use `variant="destructive"`; primary buttons the
  default variant.

## 11. Accessibility

- Focus-visible rings on all interactive elements (`--ring`).
- Keyboard operable nav, tabs, dialogs (shadcn primitives handle this).
- Semantic HTML: `nav`, `main`, `header`, `button`/`a` for actions.
- Color not the only signal: status = badge text + color.
- Target `size 44px` minimum for mobile touch targets.

## 12. Empty-State Copy Guide

| Page | Empty copy |
|---|---|
| Client documents | "No documents available yet." |
| Client cases | "No cases on file yet." |
| Staff My Cases | "No cases assigned to you yet." |
| Admin approvals | "No documents awaiting approval." |
| Notes | "No notes yet." |
| Chat history | "No recent chats" |
