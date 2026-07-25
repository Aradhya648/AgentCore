import { Button, Card, Input } from "@/components/ui";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { notifySuccess } from "@/lib/toast";
import { ApiError } from "@/services/api";
import {
  changePassword,
  deleteAccount,
  deleteAvatar,
  updateProfile,
  uploadAvatar,
} from "@/services/auth";
import { useAuthStore } from "@/stores/auth";
import { Loader2 } from "lucide-react";
import { useRef, useState } from "react";
import { LoginSessionsSection } from "./LoginSessionsSection";
import { SettingsHeader } from "./SettingsHeader";

// Mirror of the server's avatar_upload_max_bytes so an oversized pick fails fast,
// before a pointless round-trip.
const AVATAR_MAX_BYTES = 5 * 1024 * 1024;

/** Prefer the backend's user-facing message (`{error:{message}}`) over a generic
 *  fallback so the form echoes exactly why a request was rejected. */
function errMsg(e: unknown, fallback: string): string {
  return e instanceof ApiError ? (e.serverMessage ?? fallback) : fallback;
}

/**
 * 账户设置 (/more/account) — self-service identity management.
 *
 * Sections: 个人资料 / 修改密码 / 登录设备 / 危险区域 (注销).
 */
export function AccountSettings() {
  return (
    <div>
      <SettingsHeader
        title="账户设置"
        description="管理你的个人资料、登录密码、登录设备与账户。"
      />
      <div className="mt-6 space-y-8">
        <AvatarSection />
        <ProfileSection />
        <PasswordSection />
        <LoginSessionsSection />
        <DangerSection />
      </div>
    </div>
  );
}

/** A titled settings block: heading + body on the shared card surface. */
function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h2 className="text-sm font-semibold text-foreground">{title}</h2>
      {description && (
        <p className="mt-1 text-xs text-muted-foreground">{description}</p>
      )}
      <Card className="mt-3 p-4">{children}</Card>
    </section>
  );
}

/** 头像: preview + pick-a-file upload + remove. The backend re-encodes any image to
 *  a square WebP, so we only pre-check type + size (mirroring the server) to fail
 *  fast; on success the refreshed user (cache-busted avatarUrl) syncs the store. */
function AvatarSection() {
  const user = useAuthStore((s) => s.user);
  const setAuthenticated = useAuthStore((s) => s.setAuthenticated);
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const initial = (user?.displayName || user?.username || "?")
    .charAt(0)
    .toUpperCase();

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
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
      setAuthenticated(await uploadAvatar(file));
      notifySuccess("头像已更新");
    } catch (err) {
      setError(errMsg(err, "上传失败，请重试"));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      setAuthenticated(await deleteAvatar());
      notifySuccess("已恢复默认头像");
    } catch (err) {
      setError(errMsg(err, "操作失败，请重试"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section
      title="头像"
      description="点击上传新头像，建议使用清晰的正方形图片。"
    >
      <div className="flex items-center gap-4">
        <div className="flex size-16 shrink-0 items-center justify-center overflow-hidden rounded-full bg-muted text-xl font-medium text-muted-foreground">
          {user?.avatarUrl ? (
            <img
              src={user.avatarUrl}
              alt="头像"
              className="size-16 object-cover"
            />
          ) : (
            initial
          )}
        </div>
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <Button
              size="md"
              disabled={busy}
              icon={
                busy ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : undefined
              }
              onClick={() => inputRef.current?.click()}
            >
              上传头像
            </Button>
            {user?.avatarUrl && (
              <Button
                variant="neutral"
                size="md"
                disabled={busy}
                onClick={() => void remove()}
              >
                移除
              </Button>
            )}
          </div>
          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => void onFile(e)}
        />
      </div>
    </Section>
  );
}

/** 个人资料: edit display name + email; on save, refresh the auth store. */
function ProfileSection() {
  const user = useAuthStore((s) => s.user);
  const setAuthenticated = useAuthStore((s) => s.setAuthenticated);
  const [displayName, setDisplayName] = useState(user?.displayName ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmedName = displayName.trim();
  const trimmedEmail = email.trim();
  const dirty =
    trimmedName !== (user?.displayName ?? "") ||
    trimmedEmail !== (user?.email ?? "");
  const canSave = dirty && trimmedName.length > 0 && !saving;

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = await updateProfile({
        displayName: trimmedName,
        // empty clears the (nullable) email server-side
        email: trimmedEmail,
      });
      setAuthenticated(updated);
      setDisplayName(updated.displayName);
      setEmail(updated.email ?? "");
      notifySuccess("资料已更新");
    } catch (e) {
      setError(errMsg(e, "保存失败，请重试"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Section
      title="个人资料"
      description="显示名会展示给团队成员；邮箱用于后续找回密码（可选）。"
    >
      <div className="space-y-3">
        <label className="block" htmlFor="account-profile-username">
          <span className="mb-1 block text-xs text-muted-foreground">
            用户名
          </span>
          <Input
            id="account-profile-username"
            className="w-full opacity-60"
            value={user?.username ?? ""}
            disabled
          />
        </label>
        <label className="block" htmlFor="account-profile-display-name">
          <span className="mb-1 block text-xs text-muted-foreground">
            显示名
          </span>
          <Input
            id="account-profile-display-name"
            className="w-full"
            value={displayName}
            maxLength={200}
            placeholder="你的显示名"
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </label>
        <label className="block" htmlFor="account-profile-email">
          <span className="mb-1 block text-xs text-muted-foreground">
            邮箱（可选）
          </span>
          <Input
            id="account-profile-email"
            className="w-full"
            type="email"
            value={email}
            maxLength={255}
            placeholder="you@example.com"
            autoComplete="email"
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        {error && <p className="text-xs text-destructive">{error}</p>}
        <div className="flex justify-end">
          <Button
            size="md"
            disabled={!canSave}
            icon={
              saving ? (
                <Loader2 size={14} className="animate-spin" />
              ) : undefined
            }
            onClick={() => void save()}
          >
            保存
          </Button>
        </div>
      </div>
    </Section>
  );
}

/** 修改密码: current + new + confirm; the backend keeps this session alive. */
function PasswordSection() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setCurrent("");
    setNext("");
    setConfirm("");
  };

  // Client-side mirror of the server policy, so obvious mistakes never round-trip.
  const localError =
    next.length > 0 && next.length < 8
      ? "新密码至少需要 8 个字符"
      : confirm.length > 0 && next !== confirm
        ? "两次输入的新密码不一致"
        : null;
  const canSave =
    current.length > 0 && next.length >= 8 && next === confirm && !saving;

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await changePassword(current, next);
      reset();
      notifySuccess("密码已更新，其他设备需重新登录");
    } catch (e) {
      setError(errMsg(e, "修改失败，请重试"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Section
      title="修改密码"
      description="修改后，除当前设备外的所有登录都会失效。"
    >
      <div className="space-y-3">
        <label className="block" htmlFor="account-password-current">
          <span className="mb-1 block text-xs text-muted-foreground">
            当前密码
          </span>
          <Input
            id="account-password-current"
            className="w-full"
            type="password"
            value={current}
            autoComplete="current-password"
            onChange={(e) => setCurrent(e.target.value)}
          />
        </label>
        <label className="block" htmlFor="account-password-new">
          <span className="mb-1 block text-xs text-muted-foreground">
            新密码（至少 8 位）
          </span>
          <Input
            id="account-password-new"
            className="w-full"
            type="password"
            value={next}
            autoComplete="new-password"
            onChange={(e) => setNext(e.target.value)}
          />
        </label>
        <label className="block" htmlFor="account-password-confirm">
          <span className="mb-1 block text-xs text-muted-foreground">
            确认新密码
          </span>
          <Input
            id="account-password-confirm"
            className="w-full"
            type="password"
            value={confirm}
            autoComplete="new-password"
            onChange={(e) => setConfirm(e.target.value)}
          />
        </label>
        {(localError || error) && (
          <p className="text-xs text-destructive">{localError ?? error}</p>
        )}
        <div className="flex justify-end">
          <Button
            size="md"
            disabled={!canSave}
            icon={
              saving ? (
                <Loader2 size={14} className="animate-spin" />
              ) : undefined
            }
            onClick={() => void save()}
          >
            更新密码
          </Button>
        </div>
      </div>
    </Section>
  );
}

/** 危险区域: irreversible account deletion behind a password-confirm dialog. */
function DangerSection() {
  const [open, setOpen] = useState(false);

  return (
    <section>
      <h2 className="text-sm font-semibold text-destructive">危险区域</h2>
      <p className="mt-1 text-xs text-muted-foreground">
        注销后账户将被停用并匿名化，且无法恢复。
      </p>
      <Card className="mt-3 flex items-center justify-between gap-4 border-destructive/40 bg-destructive/5 p-4">
        <div className="min-w-0">
          <p className="text-sm text-foreground">注销账户</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            永久停用此账户，并释放用户名以供重新注册。
          </p>
        </div>
        <Button
          variant="danger"
          size="md"
          className="shrink-0"
          onClick={() => setOpen(true)}
        >
          注销账户
        </Button>
      </Card>
      <DeleteAccountDialog open={open} onOpenChange={setOpen} />
    </section>
  );
}

/** Password-confirm modal for注销; on success drops the app back to login. */
function DeleteAccountDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    if (busy) return;
    setPassword("");
    setError(null);
    onOpenChange(false);
  };

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await deleteAccount(password);
      // Account gone → drop to the login screen (AuthGate renders it on this).
      useAuthStore.getState().setUnauthenticated();
    } catch (e) {
      setError(errMsg(e, "注销失败，请重试"));
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => (o ? onOpenChange(true) : close())}
    >
      <DialogContent showClose={!busy}>
        <DialogHeader>
          <DialogTitle>确认注销账户</DialogTitle>
          <DialogDescription>
            此操作不可撤销。账户将被永久停用并匿名化，相关对话也会被删除。请输入密码以确认。
          </DialogDescription>
        </DialogHeader>
        <div className="px-5">
          <Input
            className="w-full"
            type="password"
            value={password}
            placeholder="当前密码"
            autoComplete="current-password"
            onChange={(e) => {
              setError(null);
              setPassword(e.target.value);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && password && !busy) void confirm();
            }}
          />
          {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button
            variant="neutral"
            className="h-9 px-4"
            disabled={busy}
            onClick={close}
          >
            取消
          </Button>
          <Button
            variant="destructive"
            className="h-9 px-4"
            disabled={busy || password.length === 0}
            icon={
              busy ? <Loader2 size={14} className="animate-spin" /> : undefined
            }
            onClick={() => void confirm()}
          >
            确认注销
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
