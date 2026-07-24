import {
  AVATAR_MAX_BYTES,
  changePassword,
  deleteAccount,
  deleteAvatar,
  updateProfile,
  uploadAvatar,
} from "@/api/account";
import { type User, logout, me } from "@/api/auth";
import { getTokens } from "@/api/client";
import {
  type SessionSummary,
  listSessions,
  revokeOtherSessions,
  revokeSession,
} from "@/api/sessions";
import { Avatar } from "@/pages/more/Avatar";
import {
  formatDeviceLabel,
  formatRelativeTime,
} from "@/pages/more/sessionDisplay";
// 账户设置 (/more/account) — profile / password / avatar / 登录设备 / 注销.
//
// Independent sections, each posting on its own. No global auth store on mobile, so
// the page loads `me()` on open and keeps the user in local state, re-syncing it after
// each mutation that returns the refreshed user.
import {
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";
import "@/pages/more/more.css";

export function AccountSettings() {
  const navigate = useNavigate();
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    me()
      .then((u) => !cancelled && setUser(u))
      .catch(() => {
        if (!getTokens()) navigate("/login", { replace: true });
        else if (!cancelled) setError("加载账户失败");
      });
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  return (
    <div className="screen">
      <header className="bar">
        <button
          type="button"
          className="link"
          onClick={() => navigate("/more")}
        >
          ← 设置
        </button>
        <span>账户设置</span>
        <span style={{ width: 44 }} />
      </header>

      <div className="settings-body">
        {error && <p className="error hint">{error}</p>}
        {user && (
          <>
            <AvatarSection user={user} onUser={setUser} />
            <ProfileSection user={user} onUser={setUser} />
            <PasswordSection />
            <SessionsSection
              onSignedOut={async () => {
                await logout().catch(() => {});
                navigate("/login", { replace: true });
              }}
            />
            <DangerSection
              onDeleted={async () => {
                await logout().catch(() => {});
                navigate("/login", { replace: true });
              }}
            />
          </>
        )}
      </div>
    </div>
  );
}

function Section({
  title,
  note,
  danger,
  children,
}: {
  title: string;
  note?: string;
  danger?: boolean;
  children: ReactNode;
}) {
  return (
    <section className="section">
      <h2 className={`section-title${danger ? " danger" : ""}`}>{title}</h2>
      {note && <p className="section-note">{note}</p>}
      <div className={`section-card${danger ? " danger" : ""}`}>{children}</div>
    </section>
  );
}

function AvatarSection({
  user,
  onUser,
}: { user: User; onUser: (u: User) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // let the user re-pick the same file after an error
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setError("请选择图片文件");
      return;
    }
    if (file.size > AVATAR_MAX_BYTES) {
      setError("图片不能超过 5 MB");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      onUser(await uploadAvatar(file));
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败，请重试");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      onUser(await deleteAvatar());
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败，请重试");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title="头像" note="建议使用清晰的正方形图片。">
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <Avatar user={user} size={64} />
        <div className="btn-row">
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={busy}
          >
            {busy ? "处理中…" : "上传头像"}
          </button>
          {user.avatar_url && (
            <button
              type="button"
              className="btn-outline"
              onClick={() => void remove()}
              disabled={busy}
            >
              移除
            </button>
          )}
        </div>
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          style={{ display: "none" }}
          onChange={(e) => void onFile(e)}
        />
      </div>
      {error && <p className="error">{error}</p>}
    </Section>
  );
}

function ProfileSection({
  user,
  onUser,
}: { user: User; onUser: (u: User) => void }) {
  const [displayName, setDisplayName] = useState(user.display_name ?? "");
  const [email, setEmail] = useState(user.email ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmedName = displayName.trim();
  const trimmedEmail = email.trim();
  const dirty =
    trimmedName !== (user.display_name ?? "") ||
    trimmedEmail !== (user.email ?? "");
  const canSave = dirty && trimmedName.length > 0 && !saving;

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const updated = await updateProfile({
        display_name: trimmedName,
        email: trimmedEmail, // empty clears the (nullable) email server-side
      });
      onUser(updated);
      setDisplayName(updated.display_name);
      setEmail(updated.email ?? "");
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败，请重试");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Section
      title="个人资料"
      note="显示名会展示给团队成员；邮箱用于后续找回密码（可选）。"
    >
      <div className="field">
        <span className="field-label">用户名</span>
        <input value={user.username} disabled />
      </div>
      <div className="field">
        <span className="field-label">显示名</span>
        <input
          value={displayName}
          maxLength={200}
          placeholder="你的显示名"
          onChange={(e) => setDisplayName(e.target.value)}
        />
      </div>
      <div className="field">
        <span className="field-label">邮箱（可选）</span>
        <input
          type="email"
          value={email}
          maxLength={255}
          placeholder="you@example.com"
          autoComplete="email"
          onChange={(e) => setEmail(e.target.value)}
        />
      </div>
      {error && <p className="error">{error}</p>}
      <div className="field-actions">
        <button type="button" disabled={!canSave} onClick={() => void save()}>
          {saving ? "保存中…" : "保存"}
        </button>
      </div>
    </Section>
  );
}

function PasswordSection() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const localError =
    next.length > 0 && next.length < 8
      ? "新密码至少需要 8 个字符"
      : confirm.length > 0 && next !== confirm
        ? "两次输入的新密码不一致"
        : null;
  const canSave =
    current.length > 0 && next.length >= 8 && next === confirm && !saving;

  async function save() {
    setSaving(true);
    setError(null);
    setDone(false);
    try {
      await changePassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      setDone(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "修改失败，请重试");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Section title="修改密码" note="修改后，除当前设备外的所有登录都会失效。">
      <div className="field">
        <span className="field-label">当前密码</span>
        <input
          type="password"
          value={current}
          autoComplete="current-password"
          onChange={(e) => setCurrent(e.target.value)}
        />
      </div>
      <div className="field">
        <span className="field-label">新密码（至少 8 位）</span>
        <input
          type="password"
          value={next}
          autoComplete="new-password"
          onChange={(e) => setNext(e.target.value)}
        />
      </div>
      <div className="field">
        <span className="field-label">确认新密码</span>
        <input
          type="password"
          value={confirm}
          autoComplete="new-password"
          onChange={(e) => setConfirm(e.target.value)}
        />
      </div>
      {(localError || error) && <p className="error">{localError ?? error}</p>}
      {done && (
        <p className="section-note" style={{ color: "var(--success)" }}>
          密码已更新，其他设备需重新登录。
        </p>
      )}
      <div className="field-actions">
        <button type="button" disabled={!canSave} onClick={() => void save()}>
          {saving ? "更新中…" : "更新密码"}
        </button>
      </div>
    </Section>
  );
}

function SessionsSection({ onSignedOut }: { onSignedOut: () => void }) {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [confirmOthers, setConfirmOthers] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listSessions();
      setSessions(res.data);
    } catch (e) {
      if (!getTokens()) {
        navigate("/login", { replace: true });
        return;
      }
      setError(e instanceof Error ? e.message : "加载登录设备失败");
      setSessions(null);
    } finally {
      setLoading(false);
    }
  }, [navigate]);

  useEffect(() => {
    void load();
  }, [load]);

  async function doRevoke(session: SessionSummary) {
    setBusyId(session.id);
    setActionError(null);
    try {
      await revokeSession(session.id);
      if (session.current) {
        onSignedOut();
        return;
      }
      setConfirmId(null);
      await load();
    } catch (e) {
      if (!getTokens()) {
        navigate("/login", { replace: true });
        return;
      }
      setActionError(e instanceof Error ? e.message : "退出设备失败");
    } finally {
      setBusyId(null);
    }
  }

  async function doRevokeOthers() {
    setBusyId("__others__");
    setActionError(null);
    try {
      await revokeOtherSessions();
      setConfirmOthers(false);
      await load();
    } catch (e) {
      if (!getTokens()) {
        navigate("/login", { replace: true });
        return;
      }
      setActionError(e instanceof Error ? e.message : "退出其他设备失败");
    } finally {
      setBusyId(null);
    }
  }

  const showOthers = (sessions?.length ?? 0) > 1;
  const busy = busyId !== null;

  return (
    <Section
      title="登录设备"
      note="查看当前活跃的登录会话，可退出不再使用的设备。"
    >
      {loading && sessions === null && <p className="muted hint">加载中…</p>}
      {error && (
        <div>
          <p className="error">{error}</p>
          <div className="field-actions">
            <button
              type="button"
              className="btn-outline"
              onClick={() => void load()}
              disabled={loading}
            >
              重试
            </button>
          </div>
        </div>
      )}
      {!error && sessions && sessions.length === 0 && (
        <p className="section-note">暂无活跃登录设备。</p>
      )}
      {sessions && sessions.length > 0 && (
        <div className="session-list">
          {sessions.map((s) => {
            const confirming = confirmId === s.id;
            return (
              <div key={s.id} className="session-row">
                <div className="session-head">
                  <span className="session-label">
                    {formatDeviceLabel(s.platform, s.user_agent)}
                  </span>
                  {s.current && <span className="session-badge">本机</span>}
                </div>
                <div className="session-meta">
                  {s.ip ? <span>IP {s.ip}</span> : <span>IP 未知</span>}
                  <span>最后活跃 {formatRelativeTime(s.last_used_at)}</span>
                </div>
                {!confirming ? (
                  <div className="session-actions">
                    <button
                      type="button"
                      className="btn-danger-outline btn-sm"
                      disabled={busy}
                      onClick={() => {
                        setConfirmOthers(false);
                        setConfirmId(s.id);
                        setActionError(null);
                      }}
                    >
                      退出
                    </button>
                  </div>
                ) : (
                  <>
                    <p className="section-note">
                      {s.current
                        ? "退出后需要重新登录本机。"
                        : "确认退出该设备？该设备上的登录将立即失效。"}
                    </p>
                    <div className="session-actions">
                      <button
                        type="button"
                        className="btn-outline btn-sm"
                        disabled={busy}
                        onClick={() => {
                          setConfirmId(null);
                          setActionError(null);
                        }}
                      >
                        取消
                      </button>
                      <button
                        type="button"
                        className="btn-danger btn-sm"
                        disabled={busy}
                        onClick={() => void doRevoke(s)}
                      >
                        {busyId === s.id ? "退出中…" : "确认退出"}
                      </button>
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}

      {showOthers &&
        (!confirmOthers ? (
          <div className="field-actions">
            <button
              type="button"
              className="btn-danger-outline"
              disabled={busy}
              onClick={() => {
                setConfirmId(null);
                setConfirmOthers(true);
                setActionError(null);
              }}
            >
              退出其他所有设备
            </button>
          </div>
        ) : (
          <>
            <p className="section-note">
              将退出除本机外的全部登录设备，那些设备需重新登录。
            </p>
            <div className="field-actions">
              <button
                type="button"
                className="btn-outline"
                disabled={busy}
                onClick={() => {
                  setConfirmOthers(false);
                  setActionError(null);
                }}
              >
                取消
              </button>
              <button
                type="button"
                className="btn-danger"
                disabled={busy}
                onClick={() => void doRevokeOthers()}
              >
                {busyId === "__others__" ? "处理中…" : "确认退出其他设备"}
              </button>
            </div>
          </>
        ))}

      {actionError && <p className="error">{actionError}</p>}
    </Section>
  );
}

function DangerSection({ onDeleted }: { onDeleted: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await deleteAccount(password);
      onDeleted();
    } catch (e) {
      setError(e instanceof Error ? e.message : "注销失败，请重试");
      setBusy(false);
    }
  }

  return (
    <Section
      title="危险区域"
      note="注销后账户将被停用并匿名化，且无法恢复。"
      danger
    >
      {!confirming ? (
        <div className="field-actions">
          <button
            type="button"
            className="btn-danger-outline"
            onClick={() => setConfirming(true)}
          >
            注销账户
          </button>
        </div>
      ) : (
        <>
          <p className="section-note">
            输入密码以确认注销，相关对话也会被删除。
          </p>
          <input
            type="password"
            value={password}
            placeholder="当前密码"
            autoComplete="current-password"
            onChange={(e) => {
              setError(null);
              setPassword(e.target.value);
            }}
          />
          {error && <p className="error">{error}</p>}
          <div className="field-actions">
            <button
              type="button"
              className="btn-outline"
              onClick={() => {
                setConfirming(false);
                setPassword("");
                setError(null);
              }}
              disabled={busy}
            >
              取消
            </button>
            <button
              type="button"
              className="btn-danger"
              disabled={busy || password.length === 0}
              onClick={() => void confirm()}
            >
              {busy ? "注销中…" : "确认注销"}
            </button>
          </div>
        </>
      )}
    </Section>
  );
}
