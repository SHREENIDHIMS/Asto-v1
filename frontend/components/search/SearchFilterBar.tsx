"use client";

import { useMemo, useState } from "react";
import { SlidersHorizontal, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { SearchFilters, StaffDashboardCase } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export const DOC_TYPES = [
  "policy",
  "checklist",
  "reference",
  "process",
  "program_guide",
];

interface SearchFilterBarProps {
  departments: string[];
  cases: StaffDashboardCase[];
  active: SearchFilters;
  onChange: (filters: SearchFilters) => void;
  className?: string;
}

interface FilterSummary {
  key: string;
  label: string;
}

/**
 * J2 collapsible faceted filter bar (staff only — client audience is
 * auto-scoped server-side and this bar is not rendered there). Each change
 * is collected and applied with the next search; filters fold into the
 * backend SQL WHERE, so they can only narrow the staff member's scope.
 */
export default function SearchFilterBar({
  departments,
  cases,
  active,
  onChange,
  className,
}: SearchFilterBarProps) {
  const [open, setOpen] = useState(false);

  const clientOptions = useMemo(() => {
    const seen = new Map<number, string>();
    for (const c of cases) {
      if (!seen.has(c.client_id)) {
        seen.set(c.client_id, c.client_name ?? `Client ${c.client_id}`);
      }
    }
    return Array.from(seen.entries())
      .sort((a, b) => a[1].localeCompare(b[1]))
      .map(([id, name]) => ({ id, name }));
  }, [cases]);

  const toggleDepartment = (dept: string) => {
    const next = new Set(active.departments ?? []);
    if (next.has(dept)) next.delete(dept);
    else next.add(dept);
    onChange({ ...active, departments: Array.from(next) });
  };

  const toggleDocType = (dt: string) => {
    const next = new Set(active.doc_types ?? []);
    if (next.has(dt)) next.delete(dt);
    else next.add(dt);
    onChange({ ...active, doc_types: Array.from(next) });
  };

  const summary: FilterSummary[] = [
    ...(active.departments ?? []).map((d) => ({ key: `dept-${d}`, label: d })),
    ...(active.doc_types ?? []).map((d) => ({ key: `type-${d}`, label: d })),
    ...(active.date_from ? [{ key: "from", label: `From ${active.date_from}` }] : []),
    ...(active.date_to ? [{ key: "to", label: `To ${active.date_to}` }] : []),
    ...(active.client_id != null && active.client_id !== undefined
      ? [
          {
            key: "client",
            label: clientOptions.find((c) => c.id === active.client_id)?.name ??
              `Client ${active.client_id}`,
          },
        ]
      : []),
  ];

  const activeCount = summary.length;

  const clearAll = () =>
    onChange({ departments: [], doc_types: [], date_from: undefined, date_to: undefined, client_id: undefined });

  return (
    <div className={cn("w-full", className)}>
      <div className="flex items-center justify-between gap-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setOpen((o) => !o)}
          className="text-xs text-muted-foreground gap-1.5"
        >
          <SlidersHorizontal className="h-3.5 w-3.5" />
          Filters
          {activeCount > 0 && (
            <Badge variant="secondary" className="ml-1">
              {activeCount}
            </Badge>
          )}
        </Button>

        {activeCount > 0 && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={clearAll}
            className="text-xs text-muted-foreground gap-1"
          >
            <X className="h-3 w-3" />
            Clear
          </Button>
        )}
      </div>

      {activeCount > 0 && !open && (
        <div className="flex flex-wrap gap-1 mt-2">
          {summary.map((s) => (
            <Badge key={s.key} variant="secondary" className="text-[11px]">
              {s.label}
            </Badge>
          ))}
        </div>
      )}

      {open && (
        <div className="mt-2 rounded-lg border border-border bg-card p-3 space-y-3">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground">
                Department
              </p>
              <div className="flex flex-wrap gap-1.5">
                {departments.length === 0 ? (
                  <p className="text-xs text-muted-foreground">None assigned</p>
                ) : (
                  departments.map((dept) => {
                    const selected = (active.departments ?? []).includes(dept);
                    return (
                      <button
                        key={dept}
                        type="button"
                        onClick={() => toggleDepartment(dept)}
                        className={cn(
                          "rounded-full px-3 py-1 text-xs border transition-colors",
                          selected
                            ? "bg-primary text-primary-foreground border-primary"
                            : "bg-background text-foreground border-border hover:bg-muted"
                        )}
                      >
                        {dept}
                      </button>
                    );
                  })
                )}
              </div>
            </div>

            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground">
                Document type
              </p>
              <div className="flex flex-wrap gap-1.5">
                {DOC_TYPES.map((dt) => {
                  const selected = (active.doc_types ?? []).includes(dt);
                  return (
                    <button
                      key={dt}
                      type="button"
                      onClick={() => toggleDocType(dt)}
                      className={cn(
                        "rounded-full px-3 py-1 text-xs border transition-colors",
                        selected
                          ? "bg-primary text-primary-foreground border-primary"
                          : "bg-background text-foreground border-border hover:bg-muted"
                      )}
                    >
                      {dt}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <label className="space-y-1.5">
              <span className="text-xs font-medium text-muted-foreground">
                From date
              </span>
              <input
                type="date"
                value={active.date_from ?? ""}
                onChange={(e) =>
                  onChange({
                    ...active,
                    date_from: e.target.value || undefined,
                  })
                }
                className="w-full h-8 rounded-md border border-border bg-background px-2 text-xs"
              />
            </label>
            <label className="space-y-1.5">
              <span className="text-xs font-medium text-muted-foreground">
                To date
              </span>
              <input
                type="date"
                value={active.date_to ?? ""}
                onChange={(e) =>
                  onChange({
                    ...active,
                    date_to: e.target.value || undefined,
                  })
                }
                className="w-full h-8 rounded-md border border-border bg-background px-2 text-xs"
              />
            </label>
            <label className="space-y-1.5">
              <span className="text-xs font-medium text-muted-foreground">
                Client
              </span>
              <Select
                value={active.client_id != null ? String(active.client_id) : "none"}
                onValueChange={(v) =>
                  onChange({
                    ...active,
                    client_id: v && v !== "none" ? Number(v) : undefined,
                  })
                }
                disabled={clientOptions.length === 0}
              >
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue
                    placeholder={clientOptions.length === 0 ? "No clients" : "All clients"}
                  />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">All clients</SelectItem>
                  {clientOptions.map((c) => (
                    <SelectItem key={c.id} value={String(c.id)}>
                      {c.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
          </div>
        </div>
      )}
    </div>
  );
}
