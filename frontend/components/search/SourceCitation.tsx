"use client";

import { FileText, Hash } from "lucide-react";

interface SourceCitationProps {
  title: string;
  section?: string | null;
  chunkType?: string;
}

export default function SourceCitation({
  title,
  section,
  chunkType = "paragraph",
}: SourceCitationProps) {
  return (
    <div className="flex items-start gap-2.5 text-sm">
      <div className="mt-0.5 flex-shrink-0">
        {chunkType === "table" ? (
          <Hash className="w-3.5 h-3.5 text-muted-foreground" />
        ) : (
          <FileText className="w-3.5 h-3.5 text-muted-foreground" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <span className="font-medium text-foreground">{title}</span>
        {section && (
          <>
            <span className="mx-1 text-muted-foreground">·</span>
            <span className="text-muted-foreground">{section}</span>
          </>
        )}
      </div>
    </div>
  );
}
