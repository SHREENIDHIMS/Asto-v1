"use client";

import { Moon, Sun, Monitor } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useTheme } from "@/components/theme/ThemeProvider";
import type { Theme } from "@/lib/theme";

const ORDER: Theme[] = ["light", "dark", "system"];

const LABELS: Record<Theme, string> = {
  light: "Light",
  dark: "Dark",
  system: "System",
};

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  const next = ORDER[(ORDER.indexOf(theme) + 1) % ORDER.length];

  const Icon = theme === "dark" ? Moon : theme === "light" ? Sun : Monitor;

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className="justify-between gap-2"
      onClick={() => setTheme(next)}
      aria-label={`Theme: ${LABELS[theme]}. Switch to ${LABELS[next]}.`}
    >
      <span className="flex items-center gap-2">
        <Icon className="h-3.5 w-3.5" />
        {LABELS[theme]}
      </span>
      <span className="text-xs text-muted-foreground">{LABELS[next]}</span>
    </Button>
  );
}