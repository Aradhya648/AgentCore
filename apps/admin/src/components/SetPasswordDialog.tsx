import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Spinner } from "@/components/ui/Spinner";
import { errorMessage } from "@/services/api";
import { setUserPassword } from "@/services/adminUsers";
import { X } from "lucide-react";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";

export function SetPasswordDialog({
  userId,
  username,
  onClose,
}: {
  userId: string;
  username: string;
  onClose: () => void;
}) {
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [forceChange, setForceChange] = useState(true);
  const [saving, setSaving] = useState(false);

  const localError =
    next.length > 0 && next.length < 8
      ? "新密码至少需要 8 个字符"
      : confirm.length > 0 && next !== confirm
        ? "两次输入的密码不一致"
        : null;
  const canSave = next.length >= 8 && next === confirm && !saving;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSave) return;
    setSaving(true);
    try {
      await setUserPassword(userId, {
        new_password: next,
        force_change: forceChange,
      });
      toast.success("密码已设置，该用户所有设备已登出");
      onClose();
    } catch (err) {
      toast.error(errorMessage(err));
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-overlay px-6"
      onMouseDown={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl border border-border bg-card p-5 shadow-lg"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-foreground">设置密码</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              为 @{username} 指定新密码
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="flex size-7 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-accent-foreground"
          >
            <X size={16} />
          </button>
        </div>

        <form onSubmit={(e) => void handleSubmit(e)} className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">
            将立即
            <span className="font-medium text-foreground">登出该用户所有设备</span>
            ，原密码作废。
          </p>

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

          <label className="flex items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              checked={forceChange}
              onChange={(e) => setForceChange(e.target.checked)}
              disabled={saving}
              className="size-4 accent-primary"
            />
            要求用户首次登录后修改密码
          </label>

          {localError && (
            <p className="text-xs text-destructive">{localError}</p>
          )}

          <div className="mt-1 flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onClose}
              disabled={saving}
            >
              取消
            </Button>
            <Button type="submit" size="sm" disabled={!canSave}>
              {saving && <Spinner />}
              确认设置
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
