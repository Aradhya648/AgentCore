import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Spinner } from "@/components/ui/Spinner";
import {
  loadRememberedUsername,
  saveRememberedUsername,
} from "@/lib/rememberedUsername";
import { errorMessage } from "@/services/api";
import { login, loginMfa } from "@/services/auth";
import { useAuthStore } from "@/stores/auth";
import { ArrowLeft, ShieldCheck } from "lucide-react";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";

type Step = "credentials" | "mfa";

export function LoginPage() {
  const setAuthenticated = useAuthStore((s) => s.setAuthenticated);
  const setForbidden = useAuthStore((s) => s.setForbidden);
  const pendingMfaToken = useAuthStore((s) => s.pendingMfaToken);
  const setPendingMfaToken = useAuthStore((s) => s.setPendingMfaToken);

  const [step, setStep] = useState<Step>(pendingMfaToken ? "mfa" : "credentials");
  const [username, setUsername] = useState(() => loadRememberedUsername());
  const [password, setPassword] = useState("");
  /** Default off — session persistence is opt-in via「保持登录」. */
  const [persistSession, setPersistSession] = useState(false);
  const [totpCode, setTotpCode] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleCredentials = async (e: FormEvent) => {
    e.preventDefault();
    if (!username || !password || submitting) return;
    setSubmitting(true);
    try {
      const outcome = await login(username, password, persistSession);
      saveRememberedUsername(username);
      if (outcome.kind === "mfa_required") {
        setPendingMfaToken(outcome.pendingToken);
        setStep("mfa");
        setSubmitting(false);
        return;
      }
      if (outcome.kind === "mfa_setup_required") {
        if (outcome.user.role === "admin") {
          setAuthenticated(outcome.user, { mfaSetupRequired: true });
        } else {
          setForbidden(outcome.user);
        }
        return;
      }
      if (outcome.user.role === "admin") setAuthenticated(outcome.user);
      else setForbidden(outcome.user);
    } catch (err) {
      toast.error(errorMessage(err));
      setSubmitting(false);
    }
  };

  const handleMfa = async (e: FormEvent) => {
    e.preventDefault();
    const token = pendingMfaToken;
    if (!token || !totpCode || submitting) return;
    setSubmitting(true);
    try {
      const outcome = await loginMfa(token, totpCode.trim());
      if (outcome.kind !== "success") {
        toast.error("验证失败，请重试");
        setSubmitting(false);
        return;
      }
      saveRememberedUsername(username);
      if (outcome.user.role === "admin") setAuthenticated(outcome.user);
      else setForbidden(outcome.user);
    } catch (err) {
      toast.error(errorMessage(err));
      setSubmitting(false);
    }
  };

  const handleBack = () => {
    setPendingMfaToken(null);
    setStep("credentials");
    setTotpCode("");
    setSubmitting(false);
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <div className="flex size-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <ShieldCheck size={24} />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-foreground">
              AgentCore 管理后台
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {step === "mfa"
                ? "输入身份验证器中的 6 位验证码"
                : "仅限平台管理员登录"}
            </p>
          </div>
        </div>

        {step === "credentials" ? (
          <form onSubmit={(e) => void handleCredentials(e)} className="flex flex-col gap-3">
            <Input
              type="text"
              autoComplete="username"
              placeholder="用户名"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={submitting}
              // biome-ignore lint/a11y/noAutofocus: single-purpose login form
              autoFocus
            />
            <Input
              type="password"
              autoComplete="current-password"
              placeholder="密码"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={submitting}
            />
            <label className="flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
              <input
                type="checkbox"
                className="size-4 rounded border-input accent-primary"
                checked={persistSession}
                onChange={(e) => setPersistSession(e.target.checked)}
                disabled={submitting}
              />
              保持登录
            </label>
            <Button
              type="submit"
              disabled={submitting || !username || !password}
              className="mt-1 w-full"
            >
              {submitting && <Spinner />}
              {submitting ? "登录中…" : "登录"}
            </Button>
          </form>
        ) : (
          <form onSubmit={(e) => void handleMfa(e)} className="flex flex-col gap-3">
            <Input
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="验证码（6 位）"
              value={totpCode}
              onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, "").slice(0, 8))}
              disabled={submitting}
              autoFocus
            />
            <Button
              type="submit"
              disabled={submitting || totpCode.length < 6}
              className="mt-1 w-full"
            >
              {submitting && <Spinner />}
              {submitting ? "验证中…" : "验证并登录"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={handleBack}
              disabled={submitting}
              className="w-full"
            >
              <ArrowLeft size={14} />
              返回重新输入密码
            </Button>
          </form>
        )}

        {step === "credentials" && (
          <p className="mt-4 text-center text-xs text-muted-foreground">
            忘记密码？请联系其他平台管理员在用户管理中重置，或联系运维。
          </p>
        )}
      </div>
    </div>
  );
}
