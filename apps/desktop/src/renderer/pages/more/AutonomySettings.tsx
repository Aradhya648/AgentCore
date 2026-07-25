import { MANUAL_HELP, ManualHelpLink } from "@/components/ManualHelpLink";
import { notifyError, notifySuccess } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import {
  PERMISSION_PRESET_LABELS,
  autonomyToPreset,
  setCachedDefaultPermissionPreset,
} from "@/services/permissionPreset";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { SettingsHeader } from "./SettingsHeader";

type AutonomyPolicy = "always_ask" | "first_grant" | "full_auto";

interface AutonomyOption {
  value: AutonomyPolicy;
  label: string;
  description: string;
}

const OPTIONS: AutonomyOption[] = [
  {
    value: "always_ask",
    label: PERMISSION_PRESET_LABELS.observe.short,
    description: `新会话默认「${PERMISSION_PRESET_LABELS.observe.short}」：${PERMISSION_PRESET_LABELS.observe.description}`,
  },
  {
    value: "first_grant",
    label: `${PERMISSION_PRESET_LABELS.workspace.short}（推荐）`,
    description: `新会话默认「${PERMISSION_PRESET_LABELS.workspace.short}」：${PERMISSION_PRESET_LABELS.workspace.description}`,
  },
  {
    value: "full_auto",
    label: PERMISSION_PRESET_LABELS.full_trust.short,
    description: `新会话默认「${PERMISSION_PRESET_LABELS.full_trust.short}」：${PERMISSION_PRESET_LABELS.full_trust.description}`,
  },
];

/**
 * 新会话默认权限模式（/more/autonomy）— 用户级 AutonomyPolicy 映射到
 * observe / workspace / full_trust，仅影响新建会话的初始 permission_preset。
 */
export function AutonomySettings() {
  const [policy, setPolicy] = useState<AutonomyPolicy | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .get<{ policy: AutonomyPolicy }>("/v1/users/me/autonomy")
      .then((d) => {
        if (!alive) return;
        setPolicy(d.policy);
        setCachedDefaultPermissionPreset(d.policy);
      })
      .catch((e) => {
        if (!alive) return;
        notifyError(e, "加载默认权限模式失败");
        setPolicy("first_grant");
      });
    return () => {
      alive = false;
    };
  }, []);

  const onSelect = async (next: AutonomyPolicy) => {
    if (next === policy || pending) return;
    if (
      next === "full_auto" &&
      !window.confirm(
        "将「完全信任」设为新会话默认后，新对话中 AI 将与你同权执行命令。确定？",
      )
    ) {
      return;
    }
    setPending(true);
    try {
      const d = await api.put<{ policy: AutonomyPolicy }>(
        "/v1/users/me/autonomy",
        { policy: next },
      );
      setPolicy(d.policy);
      setCachedDefaultPermissionPreset(d.policy);
      notifySuccess(
        `新会话将默认「${PERMISSION_PRESET_LABELS[autonomyToPreset(d.policy)].short}」`,
      );
    } catch (e) {
      notifyError(e, "设置失败");
    } finally {
      setPending(false);
    }
  };

  return (
    <div>
      <SettingsHeader
        title="新会话默认权限模式"
        description="只影响之后新建的对话。已有会话请在对话内的权限徽章或状态条切换。"
        action={<ManualHelpLink to={MANUAL_HELP.autonomy} />}
      />

      <section className="mt-6 space-y-2">
        {policy === null ? (
          <Loader2
            size={16}
            className="animate-spin text-muted-foreground/50"
          />
        ) : (
          OPTIONS.map((option) => {
            const selected = option.value === policy;
            return (
              <button
                type="button"
                key={option.value}
                aria-pressed={selected}
                disabled={pending}
                onClick={() => {
                  if (!pending) void onSelect(option.value);
                }}
                className={cn(
                  "flex w-full cursor-pointer items-start gap-3 rounded-xl border border-border bg-card px-4 py-3 text-left disabled:pointer-events-none disabled:opacity-60",
                  selected
                    ? "border-primary/40 bg-primary/5"
                    : "transition-colors hover:border-primary/40 hover:bg-accent/40",
                )}
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-foreground">
                    {option.label}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {option.description}
                  </p>
                </div>
              </button>
            );
          })
        )}
      </section>
    </div>
  );
}
