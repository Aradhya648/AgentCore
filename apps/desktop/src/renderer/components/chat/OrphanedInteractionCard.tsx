import { DecisionCard, DecisionCardIcon } from "@/components/ui";
import { Ban } from "lucide-react";

/** Unified 已失效灰态 for orphaned interactions (方案 §3.2). */
export function OrphanedInteractionCard({
  title,
  detail,
}: {
  title?: string;
  detail?: string;
}) {
  return (
    <DecisionCard tone="neutral" className="mx-0 opacity-70">
      <div className="flex items-start gap-2">
        <DecisionCardIcon tone="neutral">
          <Ban size={16} />
        </DecisionCardIcon>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-muted-foreground">
            {title ?? "已失效"}
          </p>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {detail ?? "该确认已不可答复（回合已结束或服务已重启）。"}
          </p>
        </div>
      </div>
    </DecisionCard>
  );
}

/** Caption for hot-path pending cards: infinite wait, no silent timeout. */
export function WaitingForDecisionHint() {
  return (
    <p className="mt-1 text-xs text-muted-foreground">等你拍板 · 不限时</p>
  );
}
