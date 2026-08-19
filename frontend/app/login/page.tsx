"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, ArrowLeft, Eye, EyeOff, Loader2, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  forgotPassword,
  login,
  resetPassword,
  twoFactorLogin,
} from "@/lib/api-client";
import { decodeToken, isAdminRole, storeToken } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

type Mode = "login" | "forgot" | "reset" | "2fa";

export default function LoginPage() {
  const router = useRouter();
  const { t } = useI18n();
  const [mode, setMode] = useState<Mode>("login");
  const [resetToken, setResetToken] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [twoFaToken, setTwoFaToken] = useState<string | null>(null);
  const [twoFaCode, setTwoFaCode] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const reset = params.get("reset");
    if (reset) {
      setResetToken(reset);
      setMode("reset");
      // The token came from an emailed link; it should never end up in the
      // address bar history or be shareable.
      window.history.replaceState({}, document.title, "/login");
    }
  }, []);

  /** Route a freshly-issued access token to the right interface. */
  const routeByToken = (accessToken: string) => {
    const claims = decodeToken(accessToken);
    if (claims?.audience === "client") {
      router.push("/client");
    } else if (isAdminRole(claims?.role)) {
      router.push("/admin");
    } else {
      router.push("/staff");
    }
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError(null);

    try {
      // Single unified sign-in: the backend resolves staff vs client.
      const result = await login(email, password);
      if (result.requires_2fa) {
        // H4: password was correct but TOTP is on. No credentials issued
        // yet — hold the short-lived token and ask for the app code.
        setTwoFaToken(result.two_fa_token ?? null);
        setMode("2fa");
        setNotice(t("login.twoFactorEnabled"));
        return;
      }
      if (!result.access_token) {
        throw new Error(t("login.noToken"));
      }
      storeToken(result.access_token, rememberMe);
      routeByToken(result.access_token);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("login.signInFailed"));
    } finally {
      setIsLoading(false);
    }
  };

  const handleTwoFactor = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!twoFaToken) return;
    setIsLoading(true);
    setError(null);
    setNotice(null);

    try {
      const result = await twoFactorLogin(twoFaToken, twoFaCode.trim());
      if (!result.access_token) {
        throw new Error(t("login.noToken"));
      }
      storeToken(result.access_token, rememberMe);
      routeByToken(result.access_token);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("login.verificationFailed"));
    } finally {
      setIsLoading(false);
    }
  };

  const handleForgot = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError(null);
    setNotice(null);

    try {
      await forgotPassword(email);
      setNotice(
        "If that email is registered, a reset link is on its way. Check your inbox."
      );
      setEmail("");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("login.requestFailed"));
    } finally {
      setIsLoading(false);
    }
  };

  const handleReset = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== confirmPassword) {
      setError(t("login.passwordMismatch"));
      return;
    }
    setIsLoading(true);
    setError(null);
    setNotice(null);

    try {
      if (!resetToken) {
        throw new Error("Missing reset token");
      }
      await resetPassword(resetToken, password);
      setNotice(
        "Your password has been updated and other sessions were signed out. Please sign in with your new password."
      );
      setMode("login");
      setPassword("");
      setConfirmPassword("");
      setResetToken(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reset failed");
    } finally {
      setIsLoading(false);
    }
  };

  const backToLogin = () => {
    setMode("login");
    setError(null);
    setNotice(null);
    setPassword("");
    setConfirmPassword("");
    setTwoFaToken(null);
    setTwoFaCode("");
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4 py-8">
      <div className="w-full max-w-[400px]">
        <div className="flex flex-col items-center gap-2 text-center">
          <div
            className="flex size-11 shrink-0 items-center justify-center rounded-full border border-border"
            aria-hidden="true"
          >
            <svg
              className="stroke-foreground"
              xmlns="http://www.w3.org/2000/svg"
              width="20"
              height="20"
              viewBox="0 0 32 32"
              aria-hidden="true"
            >
              <circle cx="16" cy="16" r="12" fill="none" strokeWidth="8" />
            </svg>
          </div>
          <div className="space-y-1.5">
            {mode === "login" && (
              <>
                <h1 className="text-lg font-semibold tracking-tight">{t("login.welcomeBack")}</h1>
                <p className="text-sm text-muted-foreground">
                  {t("login.subtitle")}
                </p>
              </>
            )}
        {mode === "2fa" && (
          <form className="mt-6 space-y-5" onSubmit={handleTwoFactor}>
            <div className="space-y-2">
              <Label htmlFor="twofa-code">{t("login.twoFaCode")}</Label>
              <Input
                id="twofa-code"
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder={t("login.twoFaCodePlaceholder")}
                maxLength={6}
                className="text-center text-lg tracking-widest"
                value={twoFaCode}
                onChange={(e) => setTwoFaCode(e.target.value.replace(/\D/g, ""))}
                required
                autoFocus
              />
            </div>

            {error && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertTitle>{t("login.verificationFailed")}</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <Button type="submit" className="w-full" disabled={isLoading || twoFaCode.length !== 6}>
              {isLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ShieldCheck className="h-4 w-4" />
              )}
              {isLoading ? t("login.verifying") : t("login.verifyAndSignIn")}
            </Button>

            <Button
              type="button"
              variant="ghost"
              className="w-full text-muted-foreground"
              onClick={backToLogin}
            >
              <ArrowLeft className="h-4 w-4" />
              {t("login.backToLogin")}
            </Button>
          </form>
        )}

        {mode === "forgot" && (
              <>
                <h1 className="text-lg font-semibold tracking-tight">{t("login.resetYourPassword")}</h1>
                <p className="text-sm text-muted-foreground">
                  {t("login.resetHint")}
                </p>
              </>
            )}
            {mode === "reset" && (
              <>
                <h1 className="text-lg font-semibold tracking-tight">{t("login.chooseNewPassword")}</h1>
                <p className="text-sm text-muted-foreground">
                  {t("login.resetNewPasswordHint")}
                </p>
              </>
            )}
            {mode === "2fa" && (
              <>
                <h1 className="text-lg font-semibold tracking-tight">{t("login.twoFactorVerification")}</h1>
                <p className="text-sm text-muted-foreground">
                  {t("login.twoFactorCodeHint")}
                </p>
              </>
            )}
          </div>
        </div>

        {mode === "login" && (
          <form className="mt-6 space-y-5" onSubmit={handleLogin}>
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="login-email">{t("login.email")}</Label>
                <Input
                  id="login-email"
                  placeholder={t("login.emailPlaceholder")}
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="login-password">{t("login.password")}</Label>
                <div className="relative">
                  <Input
                    id="login-password"
                    placeholder={t("login.passwordPlaceholder")}
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    className="pr-10"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    aria-label={showPassword ? t("login.hidePassword") : t("login.showPassword")}
                    className="absolute inset-y-0 right-0 flex items-center justify-center px-3 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-md"
                  >
                    {showPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Checkbox
                  id="login-remember"
                  checked={rememberMe}
                  onCheckedChange={(checked) => setRememberMe(checked === true)}
                />
                <Label htmlFor="login-remember" className="font-normal text-muted-foreground">
                  {t("login.rememberMe")}
                </Label>
              </div>
              <button
                type="button"
                onClick={() => setMode("forgot")}
                className="text-sm underline hover:no-underline"
              >
                {t("login.forgotPassword")}
              </button>
            </div>

            {notice && (
              <Alert>
                <AlertDescription>{notice}</AlertDescription>
              </Alert>
            )}

            {error && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertTitle>{t("login.signInFailed")}</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <Button type="submit" className="w-full" disabled={isLoading}>
              {isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
              {isLoading ? t("login.signingIn") : t("login.signIn")}
            </Button>
          </form>
        )}

        {mode === "forgot" && (
          <form className="mt-6 space-y-5" onSubmit={handleForgot}>
            <div className="space-y-2">
              <Label htmlFor="forgot-email">{t("login.email")}</Label>
              <Input
                id="forgot-email"
                placeholder={t("login.emailPlaceholder")}
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            {notice && (
              <Alert>
                <AlertDescription>{notice}</AlertDescription>
              </Alert>
            )}

            {error && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertTitle>{t("login.requestFailed")}</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <Button type="submit" className="w-full" disabled={isLoading}>
              {isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
              {isLoading ? t("login.sending") : t("login.sendResetLink")}
            </Button>

            <Button
              type="button"
              variant="ghost"
              className="w-full text-muted-foreground"
              onClick={backToLogin}
            >
              <ArrowLeft className="h-4 w-4" />
              {t("login.backToLogin")}
            </Button>
          </form>
        )}

        {mode === "reset" && (
          <form className="mt-6 space-y-5" onSubmit={handleReset}>
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="reset-password">{t("login.newPassword")}</Label>
                <div className="relative">
                  <Input
                    id="reset-password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="new-password"
                    className="pr-10"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    minLength={8}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    aria-label={showPassword ? t("login.hidePassword") : t("login.showPassword")}
                    className="absolute inset-y-0 right-0 flex items-center justify-center px-3 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-md"
                  >
                    {showPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="reset-confirm">{t("login.confirmNewPassword")}</Label>
                <Input
                  id="reset-confirm"
                  type="password"
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                  minLength={8}
                />
              </div>
            </div>

            {error && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertTitle>{t("login.passwordResetFailed")}</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <Button type="submit" className="w-full" disabled={isLoading}>
              {isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
              {isLoading ? t("login.updating") : t("login.updatePassword")}
            </Button>

            <Button
              type="button"
              variant="ghost"
              className="w-full text-muted-foreground"
              onClick={backToLogin}
            >
              <ArrowLeft className="h-4 w-4" />
              {t("login.backToLogin")}
            </Button>
          </form>
        )}
      </div>
    </div>
  );
}