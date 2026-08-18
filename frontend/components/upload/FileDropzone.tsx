"use client";

import { useCallback, useRef, useState } from "react";
import { FileText, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";

interface FileDropzoneProps {
  files: File[];
  onFilesChange: (files: File[]) => void;
  accept?: string;
  multiple?: boolean;
  disabled?: boolean;
  label?: string;
  hint?: string;
}

/**
 * Drag-and-drop multi-file dropzone with a native input fallback.
 * Files are held in the parent via `files`/`onFilesChange` so the caller
 * decides how to upload them (e.g. sequentially with progress).
 */
export function FileDropzone({
  files,
  onFilesChange,
  accept,
  multiple = true,
  disabled,
  label = "Drag & drop files here, or click to browse",
  hint,
}: FileDropzoneProps) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback(
    (incoming: FileList | null) => {
      if (!incoming || incoming.length === 0) return;
      const incomingList = Array.from(incoming);
      if (multiple) {
        onFilesChange([...files, ...incomingList]);
      } else {
        onFilesChange(incomingList.slice(0, 1));
      }
    },
    [files, multiple, onFilesChange]
  );

  const removeFile = (index: number) => {
    onFilesChange(files.filter((_, i) => i !== index));
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    if (disabled) return;
    addFiles(e.dataTransfer.files);
  };

  return (
    <div className="space-y-3">
      <div
        role="button"
        tabIndex={0}
        aria-label={label}
        onClick={() => !disabled && inputRef.current?.click()}
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === " ") && !disabled) {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={`flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-8 text-center transition-colors cursor-pointer ${
          dragging
            ? "border-primary bg-primary/5"
            : "border-muted-foreground/25 hover:border-primary/50 hover:bg-muted/30"
        } ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
      >
        <Upload className="h-6 w-6 text-muted-foreground" />
        <p className="text-sm font-medium">{label}</p>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          accept={accept}
          multiple={multiple}
          disabled={disabled}
          onChange={(e) => {
            addFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {files.length > 0 && (
        <ul className="space-y-1.5">
          {files.map((file, index) => (
            <li
              key={`${file.name}-${file.lastModified}-${index}`}
              className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm"
            >
              <FileText className="h-4 w-4 text-muted-foreground flex-shrink-0" />
              <span className="truncate flex-1">{file.name}</span>
              <span className="text-xs text-muted-foreground flex-shrink-0">
                {(file.size / 1024).toFixed(0)} KB
              </span>
              {!disabled && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6"
                  aria-label={`Remove ${file.name}`}
                  onClick={() => removeFile(index)}
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
