import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { errorMessage } from "@/services/api";
import { resetUserPassword } from "@/services/adminUsers";
import { Check, Copy, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

// Two-phase: 确认 (the action signs the user out of every device) → 展示 the
// one-off password. The temp password is returned exactly once by the backend,
// so the 展示 phase is the only chance to capture it — no re-fetch path exists.
type Phase = "confirm" | "done";

export function ResetPasswordDialog({
  userId,
  username,
  onClose,
}: {
  userId: string;
  username: string;
  onClose: () => void;
}) {
  const [phase, setPhase] = useState<Phase>("confirm");
  const [saving, setSaving] = useState(false);
  const [temp, setTemp] = useState("");
  const [copied, setCopied] = useState(false);

  const handleReset = async () => {
    if (saving) return;
    setSaving(true);
    try {
      const res = await resetUserPassword(userId);
      setTemp(res.temporary_password);
      setPhase("done");
    } catch (err) {
      toast.error(errorMessage(err));
      setSaving(false);
    }
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(temp);
      setCopied(true);
      toast.success("临时密码已复制");
    } catch {
      toast.error("复制失败，请手动选择复制");
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
            <h2 className="text-base font-semibold text-foreground">重置密码</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {phase === "confirm"
                ? `为 @${username} 生成一个一次性临时密码`
                : "请立即复制并通过安全渠道转交用户"}
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

        {phase === "confirm" ? (
          <>
            <p className="text-sm text-muted-foreground">
              将为该账号生成新的临时密码，并
              <span className="font-medium text-foreground">
                立即登出其所有设备
              </span>
              。原密码作废，用户需用临时密码重新登录。
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={onClose}
                disabled={saving}
              >
                取消
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => void handleReset()}
                disabled={saving}
              >
                {saving && <Spinner />}
                确认重置
              </Button>
            </div>
          </>
        ) : (
          <>
            <div className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-warning text-xs">
              此密码仅显示这一次，关闭后无法再次查看。
            </div>
            <div className="mt-3 flex items-center gap-2">
              <code className="flex-1 select-all rounded-lg border border-border bg-muted/40 px-4 py-3 text-center font-mono text-base text-foreground">
                {temp}
              </code>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void handleCopy()}
                aria-label="复制临时密码"
              >
                {copied ? <Check size={14} /> : <Copy size={14} />}
              </Button>
            </div>
            <div className="mt-4 flex justify-end">
              <Button size="sm" onClick={onClose}>
                完成
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
