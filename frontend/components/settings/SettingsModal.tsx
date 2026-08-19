"use client";

import { useEffect, useState } from "react";
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
  ShieldCheck,
  CheckCircle2,
  Copy,
  Sun,
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
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import {
  changePassword,
  twoFaDisable,
  twoFaSetup,
  twoFaStatus,
  twoFaVerify,
  updateClientProfile,
  type ClientProfile,
} from "@/lib/api-client";
import { getToken, decodeToken, isAdminRole, type TokenClaims } from "@/lib/auth";

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
  /** Client-only: the authenticated client's profile, enables the profile card. */
  clientProfile?: ClientProfile | null;
  onProfileChange?: (profile: ClientProfile) => void;
};

const SESSION_TIMEOUTS = [
  { label: "15 minutes", value: 15 * 60 },
  { label: "30 minutes", value: 30 * 60 },
  { label: "60 minutes", value: 60 * 60 },
  { label: "Off (stay signed in)", value: 0 },
];

// ---------------------------------------------------------------------------
// H4: admin two-factor authentication (TOTP) — setup / disable
// ---------------------------------------------------------------------------

function TwoFactorCard({ token }: { token: string }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [setup, setSetup] = useState<{ otpauth_uri: string; secret: string } | null>(null);
  const [code, setCode] = useState("");
  const [disablePw, setDisablePw] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // Load the admin's current 2FA state on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await twoFaStatus(token);
        if (cancelled) return;
        setEnabled(res.enabled);
        if (!res.enabled) setSetup(null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load 2FA status");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const handleStartSetup = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await twoFaSetup(token);
      setSetup(res);
      setCode("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start setup");
    } finally {
      setBusy(false);
    }
  };

  const handleVerify = async () => {
    setBusy(true);
    setError(null);
    try {
      await twoFaVerify(token, code.trim());
      setEnabled(true);
      setSetup(null);
      setCode("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification failed");
    } finally {
      setBusy(false);
    }
  };

  const handleDisable = async () => {
    setBusy(true);
    setError(null);
    try {
      await twoFaDisable(token, disablePw);
      setEnabled(false);
      setDisablePw("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to disable 2FA");
    } finally {
      setBusy(false);
    }
  };

  const copySecret = async () => {
    if (!setup) return;
    try {
      await navigator.clipboard.writeText(setup.secret);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard may be unavailable; the secret is visible to copy by hand.
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-semibold flex items-center gap-2">
          <ShieldCheck className="h-4 w-4" />
          Two-factor authentication
        </CardTitle>
        <CardDescription>
          Protects the account that approves documents and reads the audit log.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {error && <p className="text-xs text-destructive">{error}</p>}

        {loading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Checking status…
          </div>
        ) : enabled ? (
          <>
            <div className="flex items-center gap-2 text-sm">
              <CheckCircle2 className="h-4 w-4 text-green-600" />
              <span className="font-medium text-green-700">Enabled</span>
              <span className="text-xs text-muted-foreground">
                A 6-digit code is required at sign-in.
              </span>
            </div>
            <div className="grid gap-2">
              <Label className="text-xs text-muted-foreground">
                Current password to disable
              </Label>
              <Input
                type="password"
                value={disablePw}
                onChange={(e) => setDisablePw(e.target.value)}
                placeholder="••••••••"
              />
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="w-full"
              onClick={handleDisable}
              disabled={busy || !disablePw}
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5 mr-1.5" />}
              Disable 2FA
            </Button>
          </>
        ) : setup ? (
          <>
            <p className="text-xs text-muted-foreground">
              Scan the URI or enter the secret in your authenticator app, then
              confirm with the 6-digit code it shows.
            </p>
            <div className="grid gap-1.5">
              <Label className="text-xs text-muted-foreground">Secret</Label>
              <div className="flex items-center gap-2">
                <code className="flex-1 rounded-md border bg-muted px-2 py-1.5 font-mono text-xs break-all">
                  {setup.secret}
                </code>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={copySecret}
                  aria-label="Copy secret"
                >
                  {copied ? <CheckCircle2 className="h-3.5 w-3.5 text-green-600" /> : <Copy className="h-3.5 w-3.5" />}
                </Button>
              </div>
            </div>
            <div className="grid gap-1.5">
              <Label className="text-xs text-muted-foreground">otpauth URI</Label>
              <code className="rounded-md border bg-muted px-2 py-1.5 font-mono text-[11px] break-all text-muted-foreground">
                {setup.otpauth_uri}
              </code>
            </div>
            <div className="grid gap-2">
              <Label className="text-xs text-muted-foreground">6-digit code</Label>
              <Input
                inputMode="numeric"
                placeholder="000000"
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
              />
            </div>
            <Button
              type="button"
              size="sm"
              className="w-full"
              onClick={handleVerify}
              disabled={busy || code.length !== 6}
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5 mr-1.5" />}
              Confirm & enable
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="w-full text-muted-foreground"
              onClick={() => setSetup(null)}
              disabled={busy}
            >
              Cancel
            </Button>
          </>
        ) : (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full justify-start gap-2"
            onClick={handleStartSetup}
            disabled={busy}
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
            Set up two-factor authentication
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// K4: client profile — contact details + notification preferences
// ---------------------------------------------------------------------------

const NOTIFICATION_TYPES = [
  { value: "info", label: "General updates" },
  { value: "warning", label: "Warnings" },
  { value: "error", label: "Errors / urgent" },
  { value: "success", label: "Success confirmations" },
];

function ClientProfileCard({
  token,
  profile,
  onProfileChange,
}: {
  token: string;
  profile: ClientProfile;
  onProfileChange?: (profile: ClientProfile) => void;
}) {
  const [fullName, setFullName] = useState(profile.full_name ?? "");
  const [prefs, setPrefs] = useState<string[]>(profile.notification_prefs ?? []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setFullName(profile.full_name ?? "");
    setPrefs(profile.notification_prefs ?? []);
  }, [profile]);

  const togglePref = (value: string) => {
    setPrefs((prev) =>
      prev.includes(value) ? prev.filter((p) => p !== value) : [...prev, value]
    );
    setSaved(false);
  };

  const handleSave = async () => {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const res = await updateClientProfile(token, {
        full_name: fullName.trim(),
        notification_prefs: prefs,
      });
      onProfileChange?.(res.client);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save profile");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-semibold flex items-center gap-2">
          <User className="h-4 w-4" />
          Profile
        </CardTitle>
        <CardDescription>
          Update your display name and which notification types you receive.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-2">
          <Label className="text-xs text-muted-foreground">Full name</Label>
          <Input
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            placeholder="Your name"
            disabled={busy}
          />
        </div>

        <div className="grid gap-1.5">
          <Label className="text-xs text-muted-foreground">
            Notify me about
          </Label>
          {NOTIFICATION_TYPES.map((n) => (
            <label
              key={n.value}
              className="flex items-center gap-2 text-sm"
            >
              <Checkbox
                checked={prefs.includes(n.value)}
                onCheckedChange={() => togglePref(n.value)}
              />
              {n.label}
            </label>
          ))}
        </div>

        {error && <p className="text-xs text-destructive">{error}</p>}
        {saved && (
          <p className="text-xs text-green-700">Profile saved.</p>
        )}

        <Button
          type="button"
          variant="outline"
          size="sm"
          className="w-full"
          onClick={handleSave}
          disabled={busy}
        >
          {busy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Save className="h-3.5 w-3.5 mr-1.5" />
          )}
          Save profile
        </Button>
      </CardContent>
    </Card>
  );
}

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
  clientProfile,
  onProfileChange,
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

  const isAdmin = isAdminRole(identity.role);
  const sessionToken = getToken() ?? null;

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

      {/* K4: client profile (contact + notification prefs) */}
      {clientProfile && sessionToken && (
        <ClientProfileCard
          token={sessionToken}
          profile={clientProfile}
          onProfileChange={onProfileChange}
        />
      )}

      {/* H4: admin two-factor authentication */}
      {isAdmin && sessionToken && <TwoFactorCard token={sessionToken} />}

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

      {/* N1: Appearance — theme toggle */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <Sun className="h-4 w-4" />
            Appearance
          </CardTitle>
          <CardDescription>
            Choose a theme. System follows your device setting.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ThemeToggle />
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
