import type { Execution } from "@/stores/execution";
import { Gavel } from "lucide-react";
import { ModelBadge } from "../ModelBadge";
import type { DebateModel } from "../model";

/**
 * 主持人身份符号（贯穿全场）：法槌 + 「主持人」+ 可得时的模型徽章。
 * 终审舞台用更大标题变体（「主持人终审」），其余触点复用此壳，勿各造一套。
 */
export function ModeratorIdentity({
  model,
  gavelSize = 13,
  className = "",
}: {
  /** 模型 id；空 / null → 不渲染徽章（直播态渐进增强）。 */
  model?: string | null;
  gavelSize?: number;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-muted-foreground ${className}`}
    >
      <Gavel size={gavelSize} className="shrink-0" aria-hidden />
      <span className="font-medium text-foreground">主持人</span>
      <ModelBadge model={model} />
    </span>
  );
}

/** 与终审同一数据源：`moderatorRunId` → `execution.runs` → `model`。直播态 id 为空 → null。 */
export function resolveModeratorModel(
  debate: Pick<DebateModel, "moderatorRunId">,
  execution: Pick<Execution, "runs">,
): string | null {
  if (!debate.moderatorRunId) return null;
  const run = execution.runs.find((r) => r.id === debate.moderatorRunId);
  return run?.model ?? null;
}
