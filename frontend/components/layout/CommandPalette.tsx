"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CornerDownLeft, Search, Sparkles } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import type { NavGroup } from "@/config/navigation";

export interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  navGroups: NavGroup[];
  onNavigate: (id: string) => void;
  /** When provided, typed text can be run as a knowledge search (Enter). */
  onAsk?: (query: string) => void;
}

interface CommandItem {
  key: string;
  label: string;
  group: string;
  icon?: React.ReactNode;
  run: () => void;
}

/**
 * Global Ctrl/Cmd+K command palette: filter over the role's navigation
 * items plus "Ask Asto" for free-text queries. Rendered inside AppShell so
 * it is available on every staff/admin/client view.
 */
export default function CommandPalette({
  open,
  onOpenChange,
  navGroups,
  onNavigate,
  onAsk,
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onOpenChange(!open);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onOpenChange]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIndex(0);
      // Focus after Radix mounts the content.
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  const items = useMemo<CommandItem[]>(
    () =>
      navGroups.flatMap((group) =>
        group.items
          .filter((item) => !item.disabled)
          .map((item) => ({
            key: `nav:${item.id}`,
            label: item.label,
            group: group.title ?? "Navigate",
            icon: item.icon,
            run: () => {
              onOpenChange(false);
              onNavigate(item.id);
            },
          }))
      ),
    [navGroups, onNavigate, onOpenChange]
  );

  const filtered = useMemo<CommandItem[]>(() => {
    const q = query.trim().toLowerCase();
    const matches = q
      ? items.filter(
          (item) =>
            item.label.toLowerCase().includes(q) ||
            item.group.toLowerCase().includes(q)
        )
      : items;
    if (q && onAsk) {
      const askItem: CommandItem = {
        key: "ask",
        label: query.trim(),
        group: "Ask Asto",
        icon: <Sparkles className="h-4 w-4" />,
        run: () => {
          onOpenChange(false);
          onAsk(query.trim());
        },
      };
      return [askItem, ...matches];
    }
    return matches;
  }, [items, query, onAsk, onOpenChange]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-index="${activeIndex}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  const runActive = useCallback(() => {
    filtered[activeIndex]?.run();
  }, [filtered, activeIndex]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      runActive();
    }
  };

  let lastGroup = "";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="top-[20%] translate-y-0 p-0 gap-0 max-w-xl">
        <DialogTitle className="sr-only">Command palette</DialogTitle>
        <DialogDescription className="sr-only">
          Search pages or ask a question. Use arrow keys and Enter.
        </DialogDescription>
        <div className="flex items-center gap-2 border-b border-border px-4">
          <Search className="h-4 w-4 text-muted-foreground flex-shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Search pages or ask a question…"
            aria-label="Search commands"
            className="w-full h-12 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
          <kbd className="hidden sm:inline-flex h-5 items-center rounded border border-border bg-muted px-1.5 text-[10px] font-medium text-muted-foreground">
            Esc
          </kbd>
        </div>
        <div ref={listRef} className="max-h-80 overflow-y-auto p-2">
          {filtered.length === 0 ? (
            <p className="px-3 py-6 text-center text-sm text-muted-foreground">
              No matching pages
            </p>
          ) : (
            filtered.map((item, index) => {
              const showGroup = item.group !== lastGroup;
              lastGroup = item.group;
              return (
                <div key={item.key}>
                  {showGroup && (
                    <p className="px-2 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                      {item.group}
                    </p>
                  )}
                  <button
                    type="button"
                    data-index={index}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      item.run();
                    }}
                    onMouseMove={() => setActiveIndex(index)}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-md px-2 py-2 text-left text-sm",
                      index === activeIndex && "bg-muted"
                    )}
                  >
                    <span className="flex-shrink-0 text-muted-foreground">
                      {item.icon ?? <CornerDownLeft className="h-4 w-4" />}
                    </span>
                    <span className="truncate flex-1">{item.label}</span>
                    {index === activeIndex && (
                      <CornerDownLeft className="h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" />
                    )}
                  </button>
                </div>
              );
            })
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
