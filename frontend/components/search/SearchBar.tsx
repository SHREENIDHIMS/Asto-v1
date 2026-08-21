"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Search, Loader2, AlertCircle, CornerDownLeft, Mic } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { getSearchSuggestions } from "@/lib/api-client";
import { getToken } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { useSpeechRecognition } from "@/hooks/use-speech-recognition";

interface SearchBarProps {
  onSearch: (query: string, urgency?: boolean) => void;
  isLoading?: boolean;
  placeholder?: string;
  /** When true, shows the urgency (time-sensitive) toggle in the input bar. */
  showUrgency?: boolean;
  /** External value to seed the input (e.g. a clicked recent-chat query). */
  prefill?: string;
}

const DEBOUNCE_MS = 250;
const MIN_PREFIX = 2;

export default function SearchBar({
  onSearch,
  isLoading = false,
  placeholder = "Ask about requirements...",
  showUrgency = false,
  prefill,
}: SearchBarProps) {
  const [query, setQuery] = useState("");
  const [urgency, setUrgency] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tokenRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    tokenRef.current = getToken() ?? undefined;
  }, []);

  // Seed the input when a parent programmatically prefills a query
  // (e.g. clicking a recent chat in the sidebar).
  useEffect(() => {
    if (prefill) {
      setQuery(prefill);
      setOpen(false);
    }
  }, [prefill]);

  // Debounced suggestion fetch (J4). Only fires for non-empty prefixes.
  const fetchSuggestions = useCallback((value: string) => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }
    debounceRef.current = setTimeout(async () => {
      const trimmed = value.trim();
      if (trimmed.length < MIN_PREFIX) {
        setSuggestions([]);
        setOpen(false);
        setHighlighted(-1);
        return;
      }
      try {
        const results = await getSearchSuggestions(trimmed, tokenRef.current);
        setSuggestions(results);
        setOpen(results.length > 0);
        setHighlighted(-1);
      } catch {
        setSuggestions([]);
        setOpen(false);
      }
    }, DEBOUNCE_MS);
  }, []);

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  const selectSuggestion = useCallback(
    (s: string) => {
      setQuery(s);
      setOpen(false);
      setSuggestions([]);
      setHighlighted(-1);
      inputRef.current?.focus();
    },
    []
  );

  const runSearch = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (trimmed && !isLoading) {
        onSearch(trimmed, showUrgency ? urgency : undefined);
        setQuery("");
        setOpen(false);
        setSuggestions([]);
        if (showUrgency) setUrgency(false);
      }
    },
    [isLoading, onSearch, showUrgency, urgency]
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    runSearch(query);
  };

  // Voice input (Web Speech API, browser-side only). A final transcript
  // fills the input and submits immediately.
  const speech = useSpeechRecognition((text) => {
    setQuery(text);
    runSearch(text);
  });

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!open || suggestions.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlighted((h) => (h + 1) % suggestions.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlighted((h) =>
        h <= 0 ? suggestions.length - 1 : h - 1
      );
    } else if (e.key === "Enter") {
      if (highlighted >= 0 && highlighted < suggestions.length) {
        e.preventDefault();
        selectSuggestion(suggestions[highlighted]);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
      setHighlighted(-1);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="relative max-w-3xl mx-auto">
      <div className="relative flex items-center">
        <Input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            fetchSuggestions(e.target.value);
          }}
          onKeyDown={handleKeyDown}
          onFocus={() => {
            if (suggestions.length > 0) setOpen(true);
          }}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder={placeholder}
          disabled={isLoading}
          maxLength={500}
          autoComplete="off"
          className={cn(
            "pl-12 pr-36 text-lg rounded-xl shadow-sm transition-colors",
            showUrgency && urgency && "border-destructive/50 focus:border-destructive"
          )}
        />
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />

        {speech.supported && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className={cn(
              "absolute right-[3.75rem] top-1/2 -translate-y-1/2 h-9 w-9 rounded-full",
              speech.listening && "text-destructive animate-pulse"
            )}
            onClick={() => (speech.listening ? speech.stop() : speech.start())}
            disabled={isLoading}
            aria-label={speech.listening ? "Stop voice input" : "Start voice input"}
            title={speech.listening ? "Stop voice input" : "Ask by voice"}
          >
            {speech.listening ? (
              <span className="block h-2.5 w-2.5 rounded-full bg-destructive" />
            ) : (
              <Mic className="h-4 w-4" />
            )}
          </Button>
        )}

        {showUrgency && (
          <Button
            type="button"
            variant={urgency ? "default" : "outline"}
            size="sm"
            className={cn(
              "absolute top-1/2 -translate-y-1/2 h-9",
              speech.supported ? "right-[6.75rem]" : "right-20",
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
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg w-11 h-11"
          aria-label="Send"
        >
          {isLoading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Search className="h-4 w-4" />
          )}
        </Button>
      </div>

      {open && suggestions.length > 0 && (
        <ul
          role="listbox"
          className="absolute left-0 right-0 top-full mt-1 z-50 overflow-hidden rounded-lg border border-border bg-popover shadow-lg"
        >
          {suggestions.map((s, i) => (
            <li
              key={s}
              role="option"
              aria-selected={i === highlighted}
              onMouseDown={(e) => {
                e.preventDefault();
                selectSuggestion(s);
              }}
              onMouseEnter={() => setHighlighted(i)}
              className={cn(
                "flex items-center justify-between gap-2 px-3 py-2.5 text-sm cursor-pointer",
                i === highlighted ? "bg-muted" : "bg-transparent"
              )}
            >
              <span className="truncate">{s}</span>
              {i === highlighted && (
                <CornerDownLeft className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              )}
            </li>
          ))}
        </ul>
      )}
    </form>
  );
}
