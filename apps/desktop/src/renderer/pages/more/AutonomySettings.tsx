import { MANUAL_HELP, ManualHelpLink } from "@/components/ManualHelpLink";
import { notifyError, notifySuccess } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import {
  type AutonomyRecipe,
  RECIPE_LABELS,
  RECIPE_ORDER,
  confirmAutoCommandIfNeeded,
  recipeToAxes,
  setCachedDefaultRecipe,
} from "@/services/permissionAxes";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { SettingsHeader } from "./SettingsHeader";

/**
 * 新会话默认权限配方（/more/autonomy）— 用户级 AutonomyRecipe，
 * 仅影响新建会话的初始 permission_axes。
 */
export function AutonomySettings() {
  const [policy, setPolicy] = useState<AutonomyRecipe | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .get<{ policy: AutonomyRecipe }>("/v1/users/me/autonomy")
      .then((d) => {
        if (!alive) return;
        setPolicy(d.policy);
        setCachedDefaultRecipe(d.policy);
      })
      .catch((e) => {
        if (!alive) return;
        notifyError(e, "加载默认权限配方失败");
        setPolicy("write_code");
      });
    return () => {
      alive = false;
    };
  }, []);

  const onSelect = async (next: AutonomyRecipe) => {
    if (next === policy || pending) return;
    const currentAxes = recipeToAxes(policy ?? "write_code");
    const nextAxes = recipeToAxes(next);
    if (!confirmAutoCommandIfNeeded(currentAxes, nextAxes)) return;
    setPending(true);
    try {
      const d = await api.put<{ policy: AutonomyRecipe }>(
        "/v1/users/me/autonomy",
        { policy: next },
      );
      setPolicy(d.policy);
      setCachedDefaultRecipe(d.policy);
      notifySuccess(
        `新会话将默认「${RECIPE_LABELS[d.policy].short}」`,
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
        title="新会话默认权限配方"
        description="只影响之后新建的对话。已有会话请在对话内的权限徽章切换三轴或配方。"
        action={<ManualHelpLink to={MANUAL_HELP.autonomy} />}
      />

      <section className="mt-6 space-y-2">
        {policy === null ? (
          <Loader2
            size={16}
            className="animate-spin text-muted-foreground/50"
          />
        ) : (
          RECIPE_ORDER.map((id) => {
            const selected = id === policy;
            const meta = RECIPE_LABELS[id];
            return (
              <button
                type="button"
                key={id}
                aria-pressed={selected}
                disabled={pending}
                onClick={() => {
                  if (!pending) void onSelect(id);
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
                    {meta.short}
                    {id === "write_code" ? "（推荐）" : ""}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    新会话默认「{meta.short}」：{meta.description}
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
