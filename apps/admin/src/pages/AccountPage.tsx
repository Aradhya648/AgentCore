import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Spinner } from "@/components/ui/Spinner";
import { ApiError } from "@/services/api";
import { changePassword, updateProfile } from "@/services/auth";
import { useAuthStore } from "@/stores/auth";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";

function errMsg(e: unknown, fallback: string): string {
  return e instanceof ApiError ? (e.serverMessage ?? fallback) : fallback;
}

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
      <h2 className="text-base font-semibold text-foreground">{title}</h2>
      {description && (
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      )}
      <div className="mt-3 rounded-xl border border-border bg-card p-4">
        {children}
      </div>
    </section>
  );
}

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
        email: trimmedEmail || null,
      });
      setAuthenticated(updated);
      setDisplayName(updated.displayName);
      setEmail(updated.email ?? "");
      toast.success("资料已更新");
    } catch (e) {
      setError(errMsg(e, "保存失败，请重试"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Section
      title="个人资料"
      description="显示名会展示在侧栏；邮箱用于后续找回密码（可选）。"
    >
      <div className="flex max-w-md flex-col gap-3">
        <label className="block">
          <span className="mb-1 block text-xs text-muted-foreground">
            用户名
          </span>
          <Input value={user?.username ?? ""} disabled className="opacity-60" />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-muted-foreground">
            显示名
          </span>
          <Input
            value={displayName}
            maxLength={200}
            placeholder="你的显示名"
            onChange={(e) => setDisplayName(e.target.value)}
            disabled={saving}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-muted-foreground">
            邮箱（可选）
          </span>
          <Input
            type="email"
            value={email}
            maxLength={255}
            placeholder="you@example.com"
            autoComplete="email"
            onChange={(e) => setEmail(e.target.value)}
            disabled={saving}
          />
        </label>
        {error && <p className="text-xs text-destructive">{error}</p>}
        <div className="flex justify-end">
          <Button size="sm" disabled={!canSave} onClick={() => void save()}>
            {saving && <Spinner />}
            保存
          </Button>
        </div>
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

  const reset = () => {
    setCurrent("");
    setNext("");
    setConfirm("");
  };

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
      toast.success("密码已更新，其他设备需重新登录");
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
      <div className="flex max-w-md flex-col gap-3">
        <label className="block">
          <span className="mb-1 block text-xs text-muted-foreground">
            当前密码
          </span>
          <Input
            type="password"
            value={current}
            autoComplete="current-password"
            onChange={(e) => setCurrent(e.target.value)}
            disabled={saving}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-muted-foreground">
            新密码（至少 8 位）
          </span>
          <Input
            type="password"
            value={next}
            autoComplete="new-password"
            onChange={(e) => setNext(e.target.value)}
            disabled={saving}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-muted-foreground">
            确认新密码
          </span>
          <Input
            type="password"
            value={confirm}
            autoComplete="new-password"
            onChange={(e) => setConfirm(e.target.value)}
            disabled={saving}
          />
        </label>
        {(localError || error) && (
          <p className="text-xs text-destructive">{localError ?? error}</p>
        )}
        <div className="flex justify-end">
          <Button size="sm" disabled={!canSave} onClick={() => void save()}>
            {saving && <Spinner />}
            更新密码
          </Button>
        </div>
      </div>
    </Section>
  );
}

export function AccountPage() {
  return (
    <div className="px-6 py-8">
      <div className="mx-auto max-w-4xl">
        <h1 className="text-xl font-semibold text-foreground">账户设置</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          管理你的个人资料与登录密码。
        </p>
        <div className="mt-8 space-y-8">
          <ProfileSection />
          <PasswordSection />
        </div>
      </div>
    </div>
  );
}
