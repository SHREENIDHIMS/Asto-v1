"use client";

import { ReactNode, useEffect, useState } from "react";
import { Bell, ChevronsLeft, ChevronsRight, LogOut, Menu, Settings, Sparkles, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { NavGroup } from "@/config/navigation";

export interface ShellUser {
  name: string;
  email?: string;
  role: string;
}

export interface AppShellProps {
  /** Primary navigation groups for this role (from config/navigation.tsx). */
  navGroups: NavGroup[];
  /** Currently active nav item id. */
  activeNavId: string;
  onNavigate: (id: string) => void;
  /** brand block */
  brandTitle: string;
  brandSubtitle?: string;
  brandIcon?: ReactNode;
  /** mobile strategy: client = bottom tab bar, staff/admin = drawer */
  mobile?: "bottom-tabs" | "drawer";
  /** header contextual info */
  headerTitle: string;
  headerSubtitle?: string;
  /** right-side header actions (e.g. New Chat) */
  headerActions?: ReactNode;
  /** notification bell */
  onNotifications?: () => void;
  notificationCount?: number;
  /** optional sidebar extras (rendered above nav, e.g. chat session list) */
  sidebarTop?: ReactNode;
  /** optional custom footer replacing the default user block */
  sidebarFooter?: ReactNode;
  /** user footer */
  user?: ShellUser;
  onSettings?: () => void;
  onSignOut?: () => void;
  children: ReactNode;
}

/**
 * Unified role-aware application shell.
 * Desktop-first for staff/admin (persistent collapsible sidebar), mobile
 * bottom-tab bar for the client portal. Nav is data-driven.
 */
export default function AppShell({
  navGroups,
  activeNavId,
  onNavigate,
  brandTitle,
  brandSubtitle,
  brandIcon,
  mobile = "drawer",
  headerTitle,
  headerSubtitle,
  headerActions,
  onNotifications,
  notificationCount = 0,
  sidebarTop,
  sidebarFooter,
  user,
  onSettings,
  onSignOut,
  children,
}: AppShellProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    try {
      if (localStorage.getItem("asto_sidebar_collapsed") === "1") setCollapsed(true);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem("asto_sidebar_collapsed", collapsed ? "1" : "0");
    } catch {
      // ignore
    }
  }, [collapsed]);

  const sidebarBody = (
    <ScrollArea className="flex-1 min-h-0">
      <nav className={cn("py-3 space-y-5", collapsed && "px-2 space-y-3")}>
        {navGroups.map((group, gi) => (
          <div key={gi} className="space-y-1">
            {group.title && !collapsed && (
              <p className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                {group.title}
              </p>
            )}
            {group.items.map((item) => (
              <Button
                key={item.id}
                type="button"
                variant={item.id === activeNavId ? "secondary" : "ghost"}
                onClick={() => {
                  if (!item.disabled) {
                    onNavigate(item.id);
                    setDrawerOpen(false);
                  }
                }}
                disabled={item.disabled}
                title={collapsed ? item.label : undefined}
                aria-disabled={item.disabled}
                className={cn(
                  "w-full justify-start gap-3 font-normal",
                  collapsed && "justify-center px-2",
                  item.disabled && "opacity-50"
                )}
              >
                <span className="flex-shrink-0">{item.icon}</span>
                {!collapsed && (
                  <>
                    <span className="truncate flex-1 text-left">{item.label}</span>
                    {item.badge != null && item.badge > 0 && (
                      <span className="text-xs font-medium text-primary flex-shrink-0">
                        {item.badge}
                      </span>
                    )}
                  </>
                )}
              </Button>
            ))}
          </div>
        ))}
      </nav>
    </ScrollArea>
  );

  const footer = user ? (
    <div className="border-t border-border p-3 space-y-1 flex-shrink-0">
      {!collapsed && (
        <div className="px-2 pb-2 min-w-0">
          <p className="text-sm font-medium truncate">{user.name}</p>
          <p className="text-xs text-muted-foreground truncate">{user.role}</p>
        </div>
      )}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className={cn("w-full justify-start gap-3 font-normal", collapsed && "justify-center px-2")}
        onClick={onSettings}
        title={collapsed ? "Settings" : undefined}
      >
        <Settings className="h-4 w-4 flex-shrink-0" />
        {!collapsed && "Settings"}
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className={cn(
          "w-full justify-start gap-3 font-normal text-muted-foreground",
          collapsed && "justify-center px-2"
        )}
        onClick={onSignOut}
        title={collapsed ? "Sign out" : undefined}
      >
        <LogOut className="h-4 w-4 flex-shrink-0" />
        {!collapsed && "Sign out"}
      </Button>
    </div>
  ) : null;

  const isBottomTabs = mobile === "bottom-tabs";
  // Flatten first-level items for the mobile bottom bar (client role).
  const bottomTabs = isBottomTabs
    ? navGroups.flatMap((g) => g.items).filter((i) => !i.disabled).slice(0, 5)
    : [];

  return (
    <div className="flex h-screen bg-background text-foreground overflow-hidden">
      {/* Desktop sidebar (all roles on md+). Client swaps to bottom tabs below md. */}
      <aside
        className={cn(
          "h-full border-r border-border bg-card/40 backdrop-blur-sm flex-col transition-[width] duration-200 shrink-0 hidden md:flex",
          collapsed ? "w-16" : "w-56"
        )}
      >
          <div
            className={cn(
              "h-16 flex items-center border-b border-border px-3 gap-2 flex-shrink-0",
              collapsed && "justify-center px-2"
            )}
          >
            {!collapsed && (
              <div className="flex items-center gap-3 min-w-0">
                <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-primary text-primary-foreground flex-shrink-0">
                  {brandIcon ?? <Sparkles className="w-4 h-4" />}
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-bold text-foreground leading-tight truncate">
                    {brandTitle}
                  </p>
                  {brandSubtitle && (
                    <p className="text-xs text-muted-foreground leading-tight truncate">
                      {brandSubtitle}
                    </p>
                  )}
                </div>
              </div>
            )}
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="ml-auto flex-shrink-0"
              onClick={() => setCollapsed((p) => !p)}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              {collapsed ? <ChevronsRight className="h-4 w-4" /> : <ChevronsLeft className="h-4 w-4" />}
            </Button>
          </div>
          {sidebarTop && !collapsed && (
            <div className="px-3 pt-3 flex-shrink-0">{sidebarTop}</div>
          )}
          {sidebarBody}
          {sidebarFooter ?? footer}
        </aside>

      {/* Mobile drawer (staff/admin on small screens) */}
      {!isBottomTabs && drawerOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setDrawerOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 bg-background border-r border-border flex flex-col">
            <div className="h-16 flex items-center border-b border-border px-3">
              <p className="text-sm font-bold truncate">{brandTitle}</p>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="ml-auto"
                onClick={() => setDrawerOpen(false)}
                aria-label="Close navigation"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
            {sidebarTop && <div className="px-3 pt-3 flex-shrink-0">{sidebarTop}</div>}
            <div className="flex-1 min-h-0">
              <ScrollArea className="h-full">
                <nav className="py-3 px-2 space-y-5">
                  {navGroups.map((group, gi) => (
                    <div key={gi} className="space-y-1">
                      {group.title && (
                        <p className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                          {group.title}
                        </p>
                      )}
                      {group.items.map((item) => (
                        <Button
                          key={item.id}
                          type="button"
                          variant={item.id === activeNavId ? "secondary" : "ghost"}
                          disabled={item.disabled}
                          onClick={() => {
                            if (!item.disabled) {
                              onNavigate(item.id);
                              setDrawerOpen(false);
                            }
                          }}
                          className="w-full justify-start gap-3 font-normal"
                        >
                          <span className="flex-shrink-0">{item.icon}</span>
                          <span className="truncate flex-1 text-left">{item.label}</span>
                        </Button>
                      ))}
                    </div>
                  ))}
                </nav>
              </ScrollArea>
            </div>
            {sidebarFooter ?? footer}
          </aside>
        </div>
      )}

      {/* Main column */}
      <div className="flex-1 min-w-0 flex flex-col h-full">
        {/* Header */}
        <header className="border-b border-border bg-card/50 backdrop-blur-sm sticky top-0 z-10 flex-shrink-0">
          <div className="h-16 px-4 flex items-center gap-3">
            {!isBottomTabs && (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="md:hidden"
                onClick={() => setDrawerOpen(true)}
                aria-label="Open navigation"
              >
                <Menu className="h-5 w-5" />
              </Button>
            )}
            <div className="min-w-0">
              <h1 className="text-base font-semibold truncate">{headerTitle}</h1>
              {headerSubtitle && (
                <p className="text-xs text-muted-foreground truncate -mt-0.5">{headerSubtitle}</p>
              )}
            </div>
            <div className="ml-auto flex items-center gap-2 flex-shrink-0">
              {headerActions}
              {onNotifications && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={onNotifications}
                  aria-label="Notifications"
                  className="relative"
                >
                  <Bell className="h-4 w-4" />
                  {notificationCount > 0 && (
                    <span className="absolute top-1 right-1 h-2 w-2 rounded-full bg-destructive" />
                  )}
                </Button>
              )}
            </div>
          </div>
        </header>

        {/* Content */}
        <main className="flex-1 min-h-0 flex flex-col">{children}</main>

        {/* Mobile bottom tab bar (client portal) */}
        {isBottomTabs && bottomTabs.length > 0 && (
          <nav
            className="border-t border-border bg-background flex md:hidden flex-shrink-0 pb-[env(safe-area-inset-bottom)]"
            aria-label="Primary"
          >
            {bottomTabs.map((item) => (
              <Button
                key={item.id}
                type="button"
                variant="ghost"
                disabled={item.disabled}
                onClick={() => onNavigate(item.id)}
                aria-label={item.label}
                className={cn(
                  "flex-1 flex-col gap-1 h-16 rounded-none font-normal text-[10px]",
                  item.id === activeNavId ? "text-primary" : "text-muted-foreground",
                  item.disabled && "opacity-50"
                )}
              >
                {item.icon}
                {item.label}
              </Button>
            ))}
          </nav>
        )}
      </div>
    </div>
  );
}
