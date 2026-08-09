"use client";

import { useState, useRef, useEffect } from "react";
import { Search, Loader2, AlertCircle } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface SearchBarProps {
  onSearch: (query: string, urgency?: boolean) => void;
  isLoading?: boolean;
  placeholder?: string;
  /** When true, shows the urgency (time-sensitive) toggle in the input bar. */
  showUrgency?: boolean;
  /** External value to seed the input (e.g. a clicked recent-chat query). */
  prefill?: string;
}

export default function SearchBar({
  onSearch,
  isLoading = false,
  placeholder = "Ask about requirements...",
  showUrgency = false,
  prefill,
}: SearchBarProps) {
  const [query, setQuery] = useState("");
  const [urgency, setUrgency] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Seed the input when a parent programmaticaly prefills a query
  // (e.g. clicking a recent chat in the sidebar).
  useEffect(() => {
    if (prefill) setQuery(prefill);
  }, [prefill]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (trimmed && !isLoading) {
      onSearch(trimmed, showUrgency ? urgency : undefined);
      setQuery("");
      if (showUrgency) setUrgency(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="relative max-w-3xl mx-auto">
      <div className="relative flex items-center">
        <Input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={placeholder}
          disabled={isLoading}
          maxLength={500}
          className={cn(
            "pl-12 pr-28 text-lg rounded-xl shadow-sm transition-colors",
            showUrgency && urgency && "border-destructive/50 focus:border-destructive"
          )}
        />
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />

        {showUrgency && (
          <Button
            type="button"
            variant={urgency ? "default" : "outline"}
            size="sm"
            className={cn(
              "absolute right-16 top-1/2 -translate-y-1/2 h-8",
              "gap-1.5 text-xs",
              urgency
                ? "bg-destructive text-destructive-foreground hover:bg-destructive/90"
                : "border-destructive/30 text-destructive hover:bg-destructive/10"
            )}
            onClick={() => setUrgency(!urgency)}
            aria-pressed={urgency}
            aria-label="Flag as time-sensitive"
          >
            <AlertCircle
              className={cn("h-3.5 w-3.5", urgency && "fill-current")}
            />
            Urgent
          </Button>
        )}

        <Button
          type="submit"
          size="icon"
          disabled={isLoading || !query.trim()}
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg w-10 h-10"
          aria-label="Send"
        >
          {isLoading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Search className="h-4 w-4" />
          )}
        </Button>
      </div>
    </form>
  );
}
