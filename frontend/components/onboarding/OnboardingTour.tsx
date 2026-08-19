"use client";

import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Sparkles, Upload, Users, LayoutDashboard, ShieldCheck } from "lucide-react";

export type OnboardingRole = "staff" | "admin";

const STEPS: Record<
  OnboardingRole,
  { title: string; body: string; icon: React.ReactNode }[]
> = {
  staff: [
    {
      title: "Welcome to Asto",
      body: "This is your workspace for managing clients, cases, and the knowledge base — all in one place.",
      icon: <Sparkles className="h-5 w-5" />,
    },
    {
      title: "Find answers fast",
      body: "Use the search bar to ask questions and get sourced answers drawn only from your approved documents.",
      icon: <LayoutDashboard className="h-5 w-5" />,
    },
    {
      title: "Serve your clients",
      body: "Track cases and pending requests from the Clients and My Cases tabs. Everything is logged to the audit trail.",
      icon: <Users className="h-5 w-5" />,
    },
  ],
  admin: [
    {
      title: "Welcome to Asto Admin",
      body: "This is your control center: approvals, knowledge base, users, roles, and health monitoring.",
      icon: <Sparkles className="h-5 w-5" />,
    },
    {
      title: "Grow the knowledge base",
      body: "Upload documents from the Documents tab. They are validated first, then processed by the batch ingestion pipeline.",
      icon: <Upload className="h-5 w-5" />,
    },
    {
      title: "Govern access",
      body: "Manage users, roles, and departments to control who can query and administer the knowledge base.",
      icon: <ShieldCheck className="h-5 w-5" />,
    },
  ],
};

const STORAGE_KEY: Record<OnboardingRole, string> = {
  staff: "asto_onboarded_staff",
  admin: "asto_onboarded_admin",
};

export function OnboardingTour({ role }: { role: OnboardingRole }) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);
  const steps = STEPS[role];

  useEffect(() => {
    try {
      if (localStorage.getItem(STORAGE_KEY[role]) !== "1") setOpen(true);
    } catch {
      // storage unavailable; never block the app
    }
  }, [role]);

  const finish = () => {
    try {
      localStorage.setItem(STORAGE_KEY[role], "1");
    } catch {
      // ignore
    }
    setOpen(false);
  };

  const current = steps[step];
  const last = step === steps.length - 1;

  return (
    <Dialog open={open} onOpenChange={(o) => (o ? setOpen(true) : finish())}>
      <DialogContent className="max-w-md">
        <div className="flex items-start gap-4">
          <div className="flex size-11 shrink-0 items-center justify-center rounded-full border border-border bg-primary/10 text-primary">
            {current.icon}
          </div>
          <div className="min-w-0">
            <DialogTitle className="text-base">{current.title}</DialogTitle>
            <DialogDescription className="mt-1 text-sm leading-relaxed">
              {current.body}
            </DialogDescription>
          </div>
        </div>

        <div className="mt-4 flex items-center justify-between">
          <div className="flex items-center gap-1.5" aria-hidden="true">
            {steps.map((_, i) => (
              <span
                key={i}
                className={
                  i === step
                    ? "h-2 w-5 rounded-full bg-primary transition-all"
                    : "h-2 w-2 rounded-full bg-border"
                }
              />
            ))}
          </div>
          <div className="flex items-center gap-2">
            {!last && (
              <Button type="button" variant="ghost" size="sm" onClick={finish}>
                Skip tour
              </Button>
            )}
            {!last && (
              <Button type="button" size="sm" onClick={() => setStep((s) => s + 1)}>
                Next
              </Button>
            )}
            {last && (
              <Button type="button" size="sm" onClick={finish}>
                <Sparkles className="h-4 w-4 mr-1.5" />
                Get started
              </Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}