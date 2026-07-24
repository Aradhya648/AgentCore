import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Spinner } from "@/components/ui/Spinner";
import { errorMessage } from "@/services/api";
import {
  type AdminUpdateUserRequest,
  type AdminUser,
  updateUser,
} from "@/services/adminUsers";
import { X } from "lucide-react";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";

// Empty input = clear the override (inherit the global config). A value sets the
// override (0 = unlimited for that dimension). This dialog shows the full quota
// state, so it sends every field on save (the route's tri-state maps empty→null).
function numOrNull(s: string): number | null {
  const t = s.trim();
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

function initial(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

export function QuotaDialog({
  user,
  onClose,
  onSaved,
}: {
  user: AdminUser;
  onClose: () => void;
  onSaved: (updated: AdminUser) => void;
}) {
  const [unlimited, setUnlimited] = useState(user.is_unlimited);
  const [dailyTokens, setDailyTokens] = useState(
    initial(user.quota_daily_tokens),
  );
  const [monthlyCost, setMonthlyCost] = useState(
    initial(user.quota_monthly_cost_usd),
  );
  const [dailyCost, setDailyCost] = useState(
    initial(user.quota_daily_cost_usd),
  );
  const [dailyRequests, setDailyRequests] = useState(
    initial(user.quota_daily_requests),
  );
  const [saving, setSaving] = useState(false);

  const handleSave = async (e: FormEvent) => {
    e.preventDefault();
    if (saving) return;
    setSaving(true);
    const patch: AdminUpdateUserRequest = {
      is_unlimited: unlimited,
      quota_daily_tokens: numOrNull(dailyTokens),
      quota_monthly_cost_usd: numOrNull(monthlyCost),
      quota_daily_cost_usd: numOrNull(dailyCost),
      quota_daily_requests: numOrNull(dailyRequests),
    };
    try {
      const updated = await updateUser(user.id, patch);
      toast.success("配额已更新");
      onSaved(updated);
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
            <h2 className="text-base font-semibold text-foreground">编辑配额</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {user.username} · 留空 = 继承全局，0 = 该维度不限
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

        <form onSubmit={handleSave} className="flex flex-col gap-4">
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              checked={unlimited}
              onChange={(e) => setUnlimited(e.target.checked)}
              className="size-4 accent-primary"
            />
            无限额（跳过全部配额检查）
          </label>

          <div className="flex flex-col gap-3" aria-disabled={unlimited}>
            <Field label="日 token 上限">
              <Input
                type="number"
                min={0}
                inputMode="numeric"
                placeholder="继承全局"
                value={dailyTokens}
                onChange={(e) => setDailyTokens(e.target.value)}
                disabled={unlimited}
              />
            </Field>
            <Field label="月成本上限（USD）">
              <Input
                type="number"
                min={0}
                step="0.01"
                inputMode="decimal"
                placeholder="继承全局"
                value={monthlyCost}
                onChange={(e) => setMonthlyCost(e.target.value)}
                disabled={unlimited}
              />
            </Field>
            <Field label="日成本上限（USD / 日）">
              <Input
                type="number"
                min={0}
                step="0.01"
                inputMode="decimal"
                placeholder="继承全局"
                value={dailyCost}
                onChange={(e) => setDailyCost(e.target.value)}
                disabled={unlimited}
              />
            </Field>
            <Field label="日请求数上限">
              <Input
                type="number"
                min={0}
                inputMode="numeric"
                placeholder="继承全局"
                value={dailyRequests}
                onChange={(e) => setDailyRequests(e.target.value)}
                disabled={unlimited}
              />
            </Field>
          </div>

          <div className="mt-1 flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={onClose}>
              取消
            </Button>
            <Button type="submit" size="sm" disabled={saving}>
              {saving && <Spinner />}
              保存
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}
