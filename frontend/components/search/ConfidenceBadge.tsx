"use client";

import { Shield, TrendingUp, AlertCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface ConfidenceBadgeProps {
  confidence: number;
  routing: "answer" | "partial" | "no_answer";
  size?: "sm" | "md" | "lg";
}

export default function ConfidenceBadge({
  confidence,
  routing,
  size = "md",
}: ConfidenceBadgeProps) {
  const sizeClasses = {
    sm: "px-2.5 py-1 text-xs",
    md: "px-3 py-1.5 text-sm",
    lg: "px-4 py-2 text-base",
  };

  const getVariant = () => {
    switch (routing) {
      case "answer":
        return "bg-green-100 text-green-800 border-green-200 hover:bg-green-100";
      case "partial":
        return "bg-yellow-100 text-yellow-800 border-yellow-200 hover:bg-yellow-100";
      case "no_answer":
        return "bg-gray-100 text-gray-800 border-gray-200 hover:bg-gray-100";
      default:
        return "bg-blue-100 text-blue-800 border-blue-200 hover:bg-blue-100";
    }
  };

  const getIcon = () => {
    switch (routing) {
      case "answer":
        return <Shield className="w-4 h-4" />;
      case "partial":
        return <TrendingUp className="w-4 h-4" />;
      case "no_answer":
        return <AlertCircle className="w-4 h-4" />;
      default:
        return <Shield className="w-4 h-4" />;
    }
  };

  const getLabel = () => {
    switch (routing) {
      case "answer":
        return "High Confidence";
      case "partial":
        return "Partial Answer";
      case "no_answer":
        return "No Answer Found";
      default:
        return "Uncertain";
    }
  };

  return (
    <Badge
      className={cn(
        "inline-flex items-center gap-1.5 font-medium",
        sizeClasses[size],
        getVariant()
      )}
    >
      {getIcon()}
      <span>{Math.round(confidence)}%</span>
      <span className="ml-1 opacity-75">·</span>
      <span>{getLabel()}</span>
    </Badge>
  );
}
