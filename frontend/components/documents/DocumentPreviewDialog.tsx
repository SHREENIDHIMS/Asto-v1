"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Loader2, Minus, Plus, ZoomIn } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export interface PreviewItem {
  id: number;
  title: string;
}

interface DocumentPreviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: PreviewItem[];
  initialId: number;
  fetchBlob: (id: number) => Promise<Blob>;
  loadingLabel?: string;
}

/**
 * Inline document preview. Fetches the document file as a blob and renders it
 * in an embedded <iframe> via an object URL (no new dependency). Supports
 * prev/next navigation across a list (e.g. the approvals queue) and zoom.
 */
export function DocumentPreviewDialog({
  open,
  onOpenChange,
  items,
  initialId,
  fetchBlob,
  loadingLabel = "Loading document…",
}: DocumentPreviewDialogProps) {
  const [index, setIndex] = useState(() =>
    Math.max(0, items.findIndex((i) => i.id === initialId))
  );
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const objectUrlRef = useRef<string | null>(null);

  const current = items[index];

  const load = useCallback(
    async (id: number) => {
      setLoading(true);
      setError(null);
      try {
        const blob = await fetchBlob(id);
        if (objectUrlRef.current) {
          URL.revokeObjectURL(objectUrlRef.current);
        }
        const url = URL.createObjectURL(blob);
        objectUrlRef.current = url;
        setBlobUrl(url);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load document");
        setBlobUrl(null);
      } finally {
        setLoading(false);
      }
    },
    [fetchBlob]
  );

  useEffect(() => {
    if (open) {
      const startIndex = Math.max(0, items.findIndex((i) => i.id === initialId));
      setIndex(startIndex);
      setZoom(1);
      if (items[startIndex]) {
        load(items[startIndex].id);
      }
    }
  }, [open, initialId, items, load]);

  useEffect(() => {
    return () => {
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }
    };
  }, []);

  const go = (delta: number) => {
    const next = index + delta;
    if (next < 0 || next >= items.length) return;
    setIndex(next);
    setZoom(1);
    load(items[next].id);
  };

  const zoomIn = () => setZoom((z) => Math.min(2.5, Math.round((z + 0.1) * 10) / 10));
  const zoomOut = () => setZoom((z) => Math.max(0.5, Math.round((z - 0.1) * 10) / 10));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl h-[85vh] flex flex-col gap-0 p-0">
        <DialogHeader className="px-4 py-3 border-b">
          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0">
              <DialogTitle className="text-base truncate">
                {current?.title || "Document"}
              </DialogTitle>
              <DialogDescription className="text-xs mt-0.5">
                {items.length > 0 ? `Document ${index + 1} of ${items.length}` : "Preview"}
              </DialogDescription>
            </div>
            <div className="flex items-center gap-1 flex-shrink-0">
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="h-8 w-8"
                disabled={index <= 0 || loading}
                onClick={() => go(-1)}
                aria-label="Previous document"
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="h-8 w-8"
                disabled={index >= items.length - 1 || loading}
                onClick={() => go(1)}
                aria-label="Next document"
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
              <div className="mx-1 h-5 w-px bg-border" />
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="h-8 w-8"
                onClick={zoomOut}
                disabled={zoom <= 0.5}
                aria-label="Zoom out"
              >
                <Minus className="h-4 w-4" />
              </Button>
              <span className="text-xs text-muted-foreground w-12 text-center">
                {Math.round(zoom * 100)}%
              </span>
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="h-8 w-8"
                onClick={zoomIn}
                disabled={zoom >= 2.5}
                aria-label="Zoom in"
              >
                <Plus className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </DialogHeader>

        <div className="flex-1 overflow-auto bg-muted/40 relative">
          {loading && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-muted/40 z-10">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              <p className="text-sm text-muted-foreground">{loadingLabel}</p>
            </div>
          )}
          {error && (
            <div className="absolute inset-0 flex items-center justify-center z-10">
              <p className="text-sm text-destructive bg-background border rounded-md px-4 py-3">
                {error}
              </p>
            </div>
          )}
          {blobUrl && !loading && (
            <div className="h-full flex items-start justify-center p-4">
              <iframe
                title={current?.title || "Document preview"}
                src={blobUrl}
                className="bg-white shadow rounded border"
                style={{ width: "100%", height: "100%", zoom }}
              />
            </div>
          )}
        </div>

        <DialogFooter className="px-4 py-2 border-t justify-between sm:justify-between">
          <p className="text-xs text-muted-foreground flex items-center gap-1">
            <ZoomIn className="h-3.5 w-3.5" />
            Inline preview — use the controls to navigate and zoom.
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onOpenChange(false)}
          >
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}