"use client";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";

interface RelatedQuestionsProps {
  questions: string[];
  onAskQuestion?: (question: string) => void;
}

export default function RelatedQuestions({
  questions,
  onAskQuestion,
}: RelatedQuestionsProps) {
  if (!questions || questions.length === 0) return null;

  return (
    <div className="mt-6 border-t border-border pt-4">
      <Accordion type="single" collapsible defaultValue="related">
        <AccordionItem value="related" className="border-none">
          <AccordionTrigger className="text-sm font-medium text-muted-foreground hover:text-foreground hover:no-underline">
            Related Questions ({questions.length})
          </AccordionTrigger>
          <AccordionContent className="pb-0">
            <div className="space-y-2 pt-1">
              {questions.map((q, i) => (
                <Button
                  key={i}
                  type="button"
                  variant="outline"
                  onClick={() => onAskQuestion?.(q)}
                  className="w-full justify-start h-auto py-2.5 px-3 text-left text-sm text-wrap rounded-lg"
                >
                  {q}
                </Button>
              ))}
            </div>
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </div>
  );
}
