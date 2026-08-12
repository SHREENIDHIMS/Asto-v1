"use client";

import { useState } from "react";
import {
  User,
  Shield,
  LogOut,
  LogOut as LogOutAll,
  PlusCircle,
  Trash2,
  KeySquare,
  Save,
  Loader2,
  Clock,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { changePassword } from "@/lib/api-client";
import { getToken, decodeToken, type TokenClaims } from "@/lib/auth";

export interface SettingsModalProps {
  trigger?: React.ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Human-readable identity shown in the Account section. */
  user?: {
    avatar?: string;
    name?: string;
    email?: string;
    role?: string;
  };
  onSignOut?: () => void;
  onSignOutAll?: () => void;
  onNewChat?: () => void;
  onClearHistory?: () => void;
  suggestionsEnabled?: boolean;
  onToggleSuggestions?: (enabled: boolean) => void;
  timeoutSeconds?: number;
  onTimeoutChange?: (seconds: number) => void;
};

const SESSION_TIMEOUTS = [
  { label: "15 minutes", value: 15 * 60 },
  { label: "30 minutes", value: 30 * 60 },
  { label: "60 minutes", value: 60 * 60 },
  { label: "Off (stay signed in)", value: 0 },
];

export default function SettingsModal({
  trigger,
  open,
  onOpenChange,
  user,
  onSignOut,
  onSignOutAll,
  onNewChat,
  onClearHistory,
  suggestionsEnabled = true,
  onToggleSuggestions,
  timeoutSeconds = 0,
  onTimeoutChange,
}: SettingsModalProps) {
  const [pwCurrent, setPwCurrent] = useState("");
  const [pwNew, setPwNew] = useState("");
  const [pwConfirm, setPwConfirm] = useState("");
  const [pwLoading, setPwLoading] = useState(false);
  const [pwError, setPwError] = useState<string | null>(null);
  const [pwSuccess, setPwSuccess] = useState(false);

const identity = user ?? (() => {
  const token = getToken();
  const claims: TokenClaims | null = token ? decodeToken(token) : null;
  return {
    name: claims?.name ?? (claims?.audience === "client" ? "Client" : "Staff"),
    email: claims?.audience === "client" ? "" : claims?.sub ?? "",
    role: claims?.audience === "client" ? "Client" : claims?.role ?? "Staff",
  };
})();

  const handleSavePassword = async () => {
    setPwError(null);
    setPwSuccess(false);

    if (pwNew !== pwConfirm) {
      setPwError("New passwords do not match");
      return;
    }
    if (pwNew.length < 8) {
      setPwError("Password must be at least 8 characters");
      return;
    }

    setPwLoading(true);
    try {
      await changePassword(
        { current_password: pwCurrent, new_password: pwNew },
        getToken() ?? undefined
      );
      setPwSuccess(true);
      setPwCurrent("");
      setPwNew("");
      setPwConfirm("");
    } catch (err) {
      setPwError(
        err instanceof Error ? err.message : "Password change failed"
      );
    } finally {
      setPwLoading(false);
    }
  };

  const content = (
    <div className="space-y-4">
      {/* Account */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <User className="h-4 w-4" />
            Account
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
              <User className="h-4 w-4" />
            </div>
            <div>
              <p className="font-medium text-sm">{identity.name || "—"}</p>
              <p className="text-xs text-muted-foreground">
                {identity.email || identity.role}
              </p>
            </div>
          </div>

          <div className="grid gap-2">
            <Label className="text-xs text-muted-foreground">
              Current password
            </Label>
            <Input
              type="password"
              value={pwCurrent}
              onChange={(e) => setPwCurrent(e.target.value)}
              placeholder="••••••••"
            />
          </div>
          <div className="grid gap-2">
            <Label className="text-xs text-muted-foreground">
              New password
            </Label>
            <Input
              type="password"
              value={pwNew}
              onChange={(e) => setPwNew(e.target.value)}
              placeholder="••••••••"
            />
          </div>
          <div className="grid gap-2">
            <Label className="text-xs text-muted-foreground">
              Confirm new password
            </Label>
            <Input
              type="password"
              value={pwConfirm}
              onChange={(e) => setPwConfirm(e.target.value)}
              placeholder="••••••••"
            />
          </div>

          {pwError && <p className="text-xs text-destructive">{pwError}</p>}
          {pwSuccess && (
            <p className="text-xs text-green-700">Password updated.</p>
          )}

          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full"
            onClick={handleSavePassword}
            disabled={pwLoading || !pwCurrent || !pwNew || !pwConfirm}
          >
            {pwLoading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <KeySquare className="h-3.5 w-3.5 mr-1.5" />
            )}
            Change password
          </Button>
        </CardContent>
      </Card>

      {/* Conversations */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <Clock className="h-4 w-4" />
            Conversations
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full justify-start gap-2"
            onClick={() => {
              onNewChat?.();
              onOpenChange?.(false);
            }}
          >
            <PlusCircle className="h-4 w-4" />
            Start new chat
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full justify-start gap-2 text-destructive hover:text-destructive"
            onClick={() => {
              onClearHistory?.();
              onOpenChange?.(false);
            }}
          >
            <Trash2 className="h-4 w-4" />
            Clear chat history
          </Button>
        </CardContent>
      </Card>

      {/* Smart Suggestions */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <Shield className="h-4 w-4" />
            Smart Suggestions
          </CardTitle>
          <CardDescription>
            Show related follow-up question suggestions in the chat.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex items-center justify-between">
          <span className="text-sm text-muted-foreground">
            {suggestionsEnabled ? "On" : "Off"}
          </span>
          <label className="relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus-within:outline-none focus-within:ring-2 focus-within:ring-ring">
            <Checkbox
              checked={suggestionsEnabled}
              onCheckedChange={(c) => {
                const next = !!c;
                onToggleSuggestions?.(next);
              }}
              className="sr-only"
              aria-label="Toggle related question suggestions"
            />
            <span
              className={cn(
                "inline-block h-5 w-5 transform rounded-full bg-background transition",
                suggestionsEnabled
                  ? "translate-x-5 ring-1 ring-primary/20"
                  : "translate-x-1"
              )}
            />
          </label>
        </CardContent>
      </Card>

      {/* Session */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <LogOutAll className="h-4 w-4" />
            Security & Session
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-1.5">
            <Label className="text-xs text-muted-foreground">
              Auto-timeout when idle
            </Label>
            <Select
              value={String(timeoutSeconds)}
              onValueChange={(v) => onTimeoutChange?.(Number(v))}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select a timeout" />
              </SelectTrigger>
              <SelectContent>
                {SESSION_TIMEOUTS.map((t) => (
                  <SelectItem key={t.value} value={String(t.value)}>
                    {t.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="w-full justify-start gap-2"
              onClick={onSignOutAll}
            >
              <LogOutAll className="h-4 w-4" />
              Sign out on all devices
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="w-full justify-start gap-2 text-muted-foreground"
              onClick={onSignOut}
            >
              <LogOut className="h-4 w-4" />
              Sign out here
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {trigger ? <DialogTrigger asChild>{trigger}</DialogTrigger> : null}
      <DialogContent className="max-w-lg p-0">
        <DialogHeader className="p-6 pb-0">
          <DialogTitle>Settings</DialogTitle>
          <DialogDescription>
            Manage your account, conversations, and security preferences.
          </DialogDescription>
        </DialogHeader>
        <div className="px-6 pb-6 pt-2 max-h-[70vh] overflow-y-auto">
          {content}
        </div>
      </DialogContent>
    </Dialog>
  );
}
