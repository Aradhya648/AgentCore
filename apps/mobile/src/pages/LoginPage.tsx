import { login, register } from "@/api/auth";
import {
  getRememberedUsername,
  setRememberedUsername,
} from "@/lib/rememberedUsername";
import type { LegalDocId } from "@/pages/legal/types";
import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

type Mode = "login" | "register";

function legalPath(id: LegalDocId): string {
  return `/legal/${id}`;
}

export function LoginPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("login");
  // Prefill last successful login username; shared across login/register tabs.
  const [username, setUsername] = useState(() => getRememberedUsername() ?? "");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [isAdult, setIsAdult] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const registerReady = agreed && isAdult;
  const canSubmit =
    username.trim().length >= 3 &&
    password.length >= (mode === "register" ? 8 : 1) &&
    (mode === "login" || registerReady) &&
    !busy;

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setError(null);
    setBusy(true);
    try {
      const trimmed = username.trim();
      if (mode === "register") {
        await register({
          username: trimmed,
          password,
          displayName: displayName.trim() || undefined,
        });
      }
      await login(trimmed, password);
      setRememberedUsername(trimmed);
      navigate("/", { replace: true });
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : mode === "login"
            ? "登录失败，请重试"
            : "注册失败，请重试",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="screen center">
      <div className="auth-wrap">
        <div className="auth-header">
          <h1>AgentCore</h1>
          <p className="muted">你的 Multi-Agent AI 工作台</p>
        </div>

        <div className="auth-seg" role="tablist" aria-label="登录或注册">
          {(["login", "register"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={mode === m}
              className={`auth-seg-btn${mode === m ? " auth-seg-active" : ""}`}
              onClick={() => switchMode(m)}
            >
              {m === "login" ? "登录" : "注册"}
            </button>
          ))}
        </div>

        <form className="card auth-card" onSubmit={onSubmit}>
          <input
            placeholder="用户名"
            value={username}
            autoComplete="username"
            disabled={busy}
            onChange={(e) => setUsername(e.target.value)}
          />
          <input
            placeholder={mode === "register" ? "密码（至少 8 位）" : "密码"}
            type="password"
            value={password}
            autoComplete={
              mode === "login" ? "current-password" : "new-password"
            }
            disabled={busy}
            onChange={(e) => setPassword(e.target.value)}
          />
          {mode === "register" && (
            <input
              placeholder="显示名（可选）"
              value={displayName}
              autoComplete="name"
              disabled={busy}
              onChange={(e) => setDisplayName(e.target.value)}
            />
          )}

          {mode === "register" && (
            <div className="auth-legal">
              <label className="auth-check">
                <input
                  type="checkbox"
                  checked={isAdult}
                  disabled={busy}
                  onChange={(e) => setIsAdult(e.target.checked)}
                />
                <span>我已年满 18 周岁</span>
              </label>
              <label className="auth-check">
                <input
                  type="checkbox"
                  checked={agreed}
                  disabled={busy}
                  onChange={(e) => setAgreed(e.target.checked)}
                />
                <span>
                  我已阅读并同意
                  <Link to={legalPath("terms")}>《用户协议》</Link>和
                  <Link to={legalPath("privacy")}>《隐私政策》</Link>
                </span>
              </label>
            </div>
          )}

          {error && <div className="error">{error}</div>}

          <button type="submit" disabled={!canSubmit}>
            {busy ? "请稍候…" : mode === "login" ? "登录" : "注册并登录"}
          </button>

          {mode === "login" && (
            <p className="auth-foot muted">忘记密码？请联系管理员重置。</p>
          )}
        </form>
      </div>
    </div>
  );
}
