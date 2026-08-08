"use client";

import { SearchExcerpt, SearchSummarySentence } from "@/lib/api-client";
import ConfidenceBadge from "./ConfidenceBadge";
import SourceCitation from "./SourceCitation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ResponsePackageCardProps {
  title: string;
  excerpts: SearchExcerpt[];
  summary: SearchSummarySentence[];
  confidence: number;
  routing: "answer" | "partial" | "no_answer";
}

export default function ResponsePackageCard({
  title,
  excerpts,
  summary,
  confidence,
  routing,
}: ResponsePackageCardProps) {
  if (routing === "no_answer" || excerpts.length === 0) {
    return (
      <Card className="max-w-4xl mx-auto mt-8 shadow-sm text-center">
        <CardContent className="p-8">
          <h3 className="text-lg font-semibold text-foreground mb-2">
            No Answer Found
          </h3>
          <p className="text-muted-foreground">
            I couldn&apos;t find information matching your query in the knowledge
            base. Try rephrasing or asking about a different topic.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="max-w-4xl mx-auto mt-8 space-y-6">
      <div className="flex items-start justify-between">
        <h2 className="text-2xl font-bold text-foreground">{title}</h2>
        <ConfidenceBadge confidence={confidence} routing={routing} />
      </div>

      {summary.length > 0 && (
        <Card className="shadow-sm border-primary/20">
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-semibold">
              Key Points
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="prose prose-sm max-w-none">
              {summary.map((sentence, i) => (
                <p key={i} className="mb-2 leading-relaxed">
                  {sentence.text}
                </p>
              ))}
            </div>
            <div className="pt-3 border-t border-border">
              <p className="text-xs text-muted-foreground mb-2">
                Sources:
              </p>
              <div className="space-y-1">
                {Array.from(
                  new Map(
                    summary.map((sentence) => [
                      `${sentence.source.title}:${sentence.source.section ?? ""}`,
                      sentence.source,
                    ])
                  ).values()
                ).map((source, i) => (
                  <SourceCitation
                    key={i}
                    title={source.title}
                    section={source.section}
                    chunkType={source.chunk_type}
                  />
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="space-y-4">
        {excerpts.map((excerpt, i) => (
          <Card key={i} className="shadow-sm">
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-semibold">
                Source {i + 1}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="prose prose-sm max-w-none">
                {excerpt.text.split("\n").map((line, j) => (
                  <p key={j} className="mb-2 leading-relaxed">
                    {line}
                  </p>
                ))}
              </div>
              <div className="pt-3 border-t border-border">
                <SourceCitation
                  title={excerpt.source.title}
                  section={excerpt.source.section}
                  chunkType={excerpt.source.chunk_type}
                />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
