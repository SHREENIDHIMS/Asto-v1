"use client";

import { Search, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";

interface HeroSectionProps {
  onSearch: (query: string) => void;
}

const QUICK_QUESTIONS = [
  "Minimum credit score for VA loan?",
  "Required documents for application?",
  "Maximum DTI ratio?",
  "First-time home buyer programs?",
];

export default function HeroSection({ onSearch }: HeroSectionProps) {
  return (
    <section className="flex flex-col items-center justify-center py-16 px-4 text-center">
      <div className="mb-8 flex items-center justify-center">
        <div className="p-3 rounded-full bg-primary/10">
          <Sparkles className="w-6 h-6 text-primary" />
        </div>
      </div>

      <h1 className="text-4xl md:text-5xl font-extrabold text-foreground mb-4">
        Ask me about requirements
      </h1>

      <p className="text-lg text-muted-foreground mb-10 max-w-2xl leading-relaxed">
        I can help you find information about credit scores, LTV ratios,
        required documents, eligibility criteria, and more — all from our
        internal knowledge base.
      </p>

      <div className="w-full max-w-2xl space-y-4 mb-8">
        <div className="flex flex-wrap justify-center gap-2">
          {QUICK_QUESTIONS.map((q) => (
            <Button
              key={q}
              variant="outline"
              size="sm"
              className="text-sm py-2"
              onClick={() => onSearch(q)}
            >
              {q}
            </Button>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Search className="w-3 h-3" />
        <span>Enter your question below to get started</span>
      </div>
    </section>
  );
}
