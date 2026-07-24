import {
  HARVEST_SYSTEM_CHIP_LABEL,
  isExecutionHarvestMessage,
} from "@/lib/executionHarvest";
import type { Message } from "@/stores/conversation";

/**
 * 收口合成用户消息：居中系统芯片，不渲染用户气泡。
 * 文案固定产品句，不展示后端提示词全文。
 */
export function HarvestSystemChip({ message }: { message: Message }) {
  if (!isExecutionHarvestMessage(message)) return null;
  return (
    <div
      className="flex items-center gap-2 text-xs text-muted-foreground"
      data-testid="harvest-system-chip"
    >
      <span className="h-px flex-1 bg-border" />
      <span className="inline-flex shrink-0 items-center gap-1.5">
        {HARVEST_SYSTEM_CHIP_LABEL}
      </span>
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}
