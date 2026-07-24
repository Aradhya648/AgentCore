import { Button } from "@/components/ui";
import { LegalDocPane } from "@/pages/legal/LegalDocPane";
import type { LegalDocId } from "@/pages/legal/types";
import { persistAgentTownSession } from "@/services/agentTownSession";
import { ApiError } from "@/services/api";
import { login, register } from "@/services/auth";
import { useAuthStore } from "@/stores/auth";
import { useState } from "react";

type Mode = "login" | "register";

/** Pull a human-readable message out of the API's `{error:{message}}` body. */
function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.code === "ADMIN_PRODUCT_FORBIDDEN") {
      return "此账号为管理员账号，请使用管理后台登录";
    }
    try {
      const parsed = JSON.parse(err.body);
      const msg = parsed?.error?.message ?? parsed?.detail;
      if (typeof msg === "string" && msg) return msg;
    } catch {
      /* non-JSON body */
    }
    if (err.status === 401) return "用户名或密码错误";
  }
  return fallback;
}

function LegalLink({
  docId,
  children,
  onOpen,
}: {
  docId: LegalDocId;
  children: string;
  onOpen: (id: LegalDocId) => void;
}) {
  return (
    <button
      type="button"
      className="text-foreground underline-offset-2 hover:underline"
      onClick={() => onOpen(docId)}
    >
      {children}
    </button>
  );
}

export function LoginPage() {
  const setAuthenticated = useAuthStore((s) => s.setAuthenticated);
  const [mode, setMode] = useState<Mode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [isAdult, setIsAdult] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [legalDoc, setLegalDoc] = useState<LegalDocId | null>(null);

  const registerReady = agreed && isAdult;
  const canSubmit =
    username.trim().length >= 3 &&
    password.length >= (mode === "register" ? 8 : 1) &&
    (mode === "login" || registerReady) &&
    !busy;

  const switchMode = (next: Mode) => {
    setMode(next);
    setError(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "register") {
        // Register does not set session cookies; log in right after so the new
        // account lands authenticated instead of bouncing back to this screen.
        await register({
          username: username.trim(),
          password,
          displayName: displayName.trim() || undefined,
        });
      }
      const user = await login(username.trim(), password);
      setAuthenticated(user);
      void persistAgentTownSession();
    } catch (err) {
      setError(
        errorMessage(
          err,
          mode === "login" ? "登录失败，请重试" : "注册失败，请重试",
        ),
      );
    } finally {
      setBusy(false);
    }
  };

  if (legalDoc) {
    return <LegalDocPane docId={legalDoc} onBack={() => setLegalDoc(null)} />;
  }

  const inputClass =
    "h-10 w-full rounded-lg border border-input bg-background px-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring";

  const checkClass =
    "mt-0.5 size-4 shrink-0 rounded border border-input accent-primary";

  return (
    <div className="flex h-full w-full items-center justify-center bg-background p-6">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-xl font-semibold text-foreground">AgentCore</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            你的 Multi-Agent AI 工作台
          </p>
        </div>

        <div className="mb-4 flex gap-1 rounded-lg bg-muted p-1">
          {(["login", "register"] as const).map((m) => (
            <Button
              key={m}
              variant="ghost"
              onClick={() => switchMode(m)}
              className={`h-8 flex-1 rounded-lg text-sm ${
                mode === m
                  ? "bg-card text-foreground shadow-sm hover:bg-card"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {m === "login" ? "登录" : "注册"}
            </Button>
          ))}
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            className={inputClass}
            placeholder="用户名"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
          <input
            className={inputClass}
            type="password"
            placeholder={mode === "register" ? "密码（至少 8 位）" : "密码"}
            autoComplete={
              mode === "login" ? "current-password" : "new-password"
            }
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {mode === "register" && (
            <input
              className={inputClass}
              placeholder="显示名（可选）"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              autoComplete="name"
            />
          )}

          {mode === "register" && (
            <div className="space-y-2 pt-1 text-xs leading-relaxed text-muted-foreground">
              <label className="flex gap-2">
                <input
                  type="checkbox"
                  className={checkClass}
                  checked={isAdult}
                  onChange={(e) => setIsAdult(e.target.checked)}
                />
                <span>我已年满 18 周岁</span>
              </label>
              <label className="flex gap-2">
                <input
                  type="checkbox"
                  className={checkClass}
                  checked={agreed}
                  onChange={(e) => setAgreed(e.target.checked)}
                />
                <span>
                  我已阅读并同意
                  <LegalLink docId="terms" onOpen={setLegalDoc}>
                    《用户协议》
                  </LegalLink>
                  、
                  <LegalLink docId="privacy" onOpen={setLegalDoc}>
                    《隐私政策》
                  </LegalLink>
                  和
                  <LegalLink docId="notice" onOpen={setLegalDoc}>
                    《注册须知》
                  </LegalLink>
                </span>
              </label>
            </div>
          )}

          {error && <p className="text-sm text-destructive">{error}</p>}

          <Button type="submit" className="h-10 w-full" disabled={!canSubmit}>
            {busy ? "请稍候…" : mode === "login" ? "登录" : "注册并登录"}
          </Button>

          {/* 自助找回密码依赖邮件，属后续阶段；内测期由管理员重置。 */}
          {mode === "login" && (
            <p className="pt-1 text-center text-xs text-muted-foreground">
              忘记密码？请联系管理员重置。
            </p>
          )}
        </form>

        <p className="mt-6 text-center text-xs text-muted-foreground">
          <LegalLink docId="terms" onOpen={setLegalDoc}>
            用户协议
          </LegalLink>
          <span className="mx-1.5">·</span>
          <LegalLink docId="privacy" onOpen={setLegalDoc}>
            隐私政策
          </LegalLink>
          <span className="mx-1.5">·</span>
          <LegalLink docId="notice" onOpen={setLegalDoc}>
            注册须知
          </LegalLink>
        </p>
      </div>
    </div>
  );
}
