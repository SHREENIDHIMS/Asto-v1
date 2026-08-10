// AsTo role-based navigation configuration.
// Single source of truth for the app shell nav across all three roles.
// Mirrors docs/navigation.md.

import { ReactNode } from "react";
import {
  BarChart3,
  BookOpen,
  Briefcase,
  Building2,
  CheckSquare,
  ClipboardList,
  FileText,
  FolderOpen,
  HelpCircle,
  Home,
  Inbox,
  LayoutDashboard,
  Landmark,
  MessagesSquare,
  ScrollText,
  Settings,
  Shield,
  Sparkles,
  Users,
  Workflow,
} from "lucide-react";

export type RoleKey = "admin" | "staff" | "client";

export interface NavItem {
  id: string;
  label: string;
  icon: ReactNode;
  /** View is not yet implemented — render disabled until its phase lands. */
  disabled?: boolean;
  /** Optional static badge number (e.g. pending approvals count). */
  badge?: number;
}

export interface NavGroup {
  title?: string;
  items: NavItem[];
}

export const NAV_GROUPS: Record<RoleKey, NavGroup[]> = {
  admin: [
    {
      items: [
        {
          id: "dashboard",
          label: "Dashboard",
          icon: <LayoutDashboard className="h-4 w-4" />,
        },
        { id: "approvals", label: "Approval Queue", icon: <Inbox className="h-4 w-4" /> },
        {
          id: "cases",
          label: "Cases",
          icon: <Landmark className="h-4 w-4" />,
          disabled: true,
        },
      ],
    },
    {
      title: "Governance",
      items: [
        { id: "documents", label: "Documents", icon: <FileText className="h-4 w-4" /> },
        {
          id: "knowledge",
          label: "Knowledge Base",
          icon: <BookOpen className="h-4 w-4" />,
        },
        {
          id: "sops",
          label: "SOP Management",
          icon: <ClipboardList className="h-4 w-4" />,
        },
        { id: "users", label: "Users", icon: <Users className="h-4 w-4" /> },
        { id: "clients", label: "Clients", icon: <Building2 className="h-4 w-4" /> },
        {
          id: "roles",
          label: "Roles & Permissions",
          icon: <Shield className="h-4 w-4" />,
        },
        {
          id: "departments",
          label: "Departments",
          icon: <Landmark className="h-4 w-4" />,
        },
      ],
    },
    {
      title: "System",
      items: [
        {
          id: "analytics",
          label: "Analytics",
          icon: <BarChart3 className="h-4 w-4" />,
        },
        {
          id: "audit",
          label: "Audit Log",
          icon: <ScrollText className="h-4 w-4" />,
          disabled: true,
        },
        {
          id: "settings",
          label: "Settings",
          icon: <Settings className="h-4 w-4" />,
        },
      ],
    },
  ],

  staff: [
    {
      items: [
        {
          id: "dashboard",
          label: "Dashboard",
          icon: <LayoutDashboard className="h-4 w-4" />,
          disabled: true,
        },
        {
          id: "cases",
          label: "My Cases",
          icon: <Briefcase className="h-4 w-4" />,
          disabled: true,
        },
        {
          id: "tasks",
          label: "Tasks",
          icon: <CheckSquare className="h-4 w-4" />,
          disabled: true,
        },
        {
          id: "workflows",
          label: "Workflows",
          icon: <Workflow className="h-4 w-4" />,
          disabled: true,
        },
      ],
    },
    {
      title: "Knowledge",
      items: [
        {
          id: "documents",
          label: "Documents",
          icon: <FileText className="h-4 w-4" />,
          disabled: true,
        },
        {
          id: "sops",
          label: "SOPs",
          icon: <ClipboardList className="h-4 w-4" />,
          disabled: true,
        },
        {
          id: "knowledge",
          label: "Knowledge",
          icon: <BookOpen className="h-4 w-4" />,
          disabled: true,
        },
      ],
    },
    {
      title: "Collaborate",
      items: [
        {
          id: "collaboration",
          label: "Collaboration",
          icon: <MessagesSquare className="h-4 w-4" />,
          disabled: true,
        },
        { id: "assistant", label: "AI Assistant", icon: <Sparkles className="h-4 w-4" /> },
      ],
    },
  ],

  client: [
    {
      items: [
        {
          id: "home",
          label: "Home",
          icon: <Home className="h-4 w-4" />,
          disabled: true,
        },
        { id: "case", label: "My Case", icon: <Landmark className="h-4 w-4" /> },
        { id: "documents", label: "Documents", icon: <FolderOpen className="h-4 w-4" /> },
        { id: "property", label: "Property", icon: <Building2 className="h-4 w-4" /> },
        {
          id: "messages",
          label: "Messages",
          icon: <MessagesSquare className="h-4 w-4" />,
          disabled: true,
        },
        { id: "assistant", label: "AI Assistant", icon: <Sparkles className="h-4 w-4" /> },
        {
          id: "help",
          label: "Help",
          icon: <HelpCircle className="h-4 w-4" />,
          disabled: true,
        },
      ],
    },
  ],
};
