/**
 * N2 — i18n: English-first dictionary, structured for translation.
 *
 * Add a new language as a sibling module (e.g. `es.ts`) with the same
 * shape and swap `useI18n()`'s source. JWT/API responses stay
 * language-neutral (CLAUDE.md — the API never returns prose to translate).
 */
export const en = {
  common: {
    appName: "Asto",
    loading: "Loading…",
    save: "Save",
    cancel: "Cancel",
    retry: "Retry",
    back: "Back",
  },
  login: {
    welcomeBack: "Welcome back",
    subtitle: "Enter your credentials to login to your account.",
    email: "Email",
    emailPlaceholder: "you@company.com",
    password: "Password",
    passwordPlaceholder: "Enter your password",
    showPassword: "Show password",
    hidePassword: "Hide password",
    rememberMe: "Remember me",
    forgotPassword: "Forgot password?",
    signIn: "Sign in",
    signingIn: "Signing in…",
    signInFailed: "Login failed",
    noToken: "Sign-in did not return a token",
    twoFactorEnabled:
      "Your account has two-factor authentication enabled. Enter the 6-digit code from your authenticator app.",
    twoFaCode: "6-digit code",
    twoFaCodePlaceholder: "000000",
    verificationFailed: "Verification failed",
    verifying: "Verifying…",
    verifyAndSignIn: "Verify & sign in",
    backToLogin: "Back to login",
    twoFactorVerification: "Two-factor verification",
    twoFactorCodeHint: "Enter the 6-digit code from your authenticator app.",
    resetYourPassword: "Reset your password",
    resetHint:
      "Enter your account email and we'll send you a one-time reset link.",
    chooseNewPassword: "Choose a new password",
    resetNewPasswordHint:
      "Use at least 8 characters. All other sessions will be signed out.",
    newPassword: "New password",
    confirmNewPassword: "Confirm new password",
    sendResetLink: "Send reset link",
    sending: "Sending…",
    updating: "Updating…",
    updatePassword: "Update password",
    requestFailed: "Request failed",
    passwordResetFailed: "Password reset failed",
    passwordMismatch: "Passwords do not match",
  },
  staff: {
    title: "Staff Portal",
  },
  client: {
    title: "Client Portal",
  },
  admin: {
    title: "Admin Console",
  },
} as const;

export type TranslationKey = NestedKeys<typeof en>;

type NestedKeys<T, Prefix extends string = ""> = {
  [K in keyof T]: T[K] extends string
    ? `${Prefix}${K & string}`
    : NestedKeys<T[K], `${Prefix}${K & string}.`>;
}[keyof T];