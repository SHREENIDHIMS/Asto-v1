"use client";

import { ReactNode } from "react";
import { ChevronsLeft, ChevronsRight, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";

export interface SidebarNavItem {
  id: string;
  label: string;
  icon: ReactNode;
  active?: boolean;
  badge?: string | number;
  onClick: () => void;
}

interface AppSidebarProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  brandTitle: string;
  brandSubtitle?: string;
  brandIcon?: ReactNode;
  navItems: SidebarNavItem[];
  topContent?: ReactNode;
  footerContent?: ReactNode;
}

/**
 * Reusable collapsible left navigation rail (AI-assistant style).
 * When collapsed it becomes an icon-only strip; the state is owned by
 * the parent so it can be persisted per user.
 */
export default function AppSidebar({
  collapsed,
  onToggleCollapsed,
  brandTitle,
  brandSubtitle,
  brandIcon,
  navItems,
  topContent,
  footerContent,
}: AppSidebarProps) {
  return (
    <aside
      className={cn(
        "h-full border-r border-border bg-card/40 backdrop-blur-sm flex flex-col transition-[width] duration-200 shrink-0",
        collapsed ? "w-16" : "w-56"
      )}
    >
      {/* Header: brand + collapse toggle */}
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
          onClick={onToggleCollapsed}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <ChevronsRight className="h-4 w-4" />
          ) : (
            <ChevronsLeft className="h-4 w-4" />
          )}
        </Button>
      </div>

      {/* Optional top content (e.g. New Chat + Recent Chats) */}
      {topContent && !collapsed && (
        <div className="px-3 pt-3 flex-shrink-0">{topContent}</div>
      )}

      {/* Primary navigation */}
      <ScrollArea className="flex-1 min-h-0">
        <nav className={cn("py-3 space-y-1", collapsed && "px-2")}>
          {navItems.map((item) => (
            <Button
              key={item.id}
              type="button"
              variant={item.active ? "secondary" : "ghost"}
              onClick={item.onClick}
              title={collapsed ? item.label : undefined}
              className={cn(
                "w-full justify-start gap-3 font-normal",
                collapsed && "justify-center px-2"
              )}
            >
              <span className="flex-shrink-0">{item.icon}</span>
              {!collapsed && (
                <>
                  <span className="truncate flex-1 text-left">{item.label}</span>
                  {item.badge != null && (
                    <span className="text-xs text-muted-foreground flex-shrink-0">
                      {item.badge}
                    </span>
                  )}
                </>
              )}
            </Button>
          ))}
        </nav>
      </ScrollArea>

      {/* Footer (avatar, settings, sign out) */}
      <div className="border-t border-border p-3 flex-shrink-0">
        {footerContent ?? null}
      </div>
    </aside>
  );
}
