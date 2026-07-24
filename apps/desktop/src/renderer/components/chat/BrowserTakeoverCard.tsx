import { formatMemoryTime } from "@/components/memory/MemoryUpdateItemRow";
import { Card } from "@/components/ui";
import { statusCardChrome } from "@/components/ui/tone-presets";
import { formatTakeoverDuration } from "@/services/browserTakeover";
import type { BrowserTakeover } from "@/stores/browserTakeover";
import { Hand } from "lucide-react";

/**
 * L3「团队浏览器」M2 接管标记卡（提案 D17）——时间线上的小型只读留档。
 *
 * 完全仿「记忆更新卡」的 episodic 轻提示：一行「用户接管了浏览器 · N分M秒」+ 起始时刻。
 * 接管期间零帧落盘（帧可能含明文凭据），只落起止两条 DURABLE 标记；本卡即其可视化，聊天流
 * 可见、刷新/回放可重建（数据在表里，见 {@link import("@/stores/browserTakeover")}）。
 * `endedAt` 为空（异常未归还）时退化为无时长文案。
 */
export function BrowserTakeoverCard({
  takeover,
}: {
  takeover: BrowserTakeover;
}) {
  const chrome = statusCardChrome("muted");
  const durationText =
    takeover.endedAt != null
      ? ` · ${formatTakeoverDuration(
          Date.parse(takeover.endedAt) - Date.parse(takeover.startedAt),
        )}`
      : "";
  return (
    <Card
      className={`animate-task-card-enter ${chrome.border} ${chrome.surface}`}
    >
      <div className="flex w-full items-center gap-2 px-3 py-2 text-left">
        <Hand size={16} className={`shrink-0 ${chrome.accent}`} />
        <span className={`text-xs font-medium ${chrome.accent}`}>
          {`用户接管了浏览器${durationText}`}
        </span>
        <span className="ml-auto shrink-0 text-xs text-muted-foreground">
          {formatMemoryTime(takeover.startedAt)}
        </span>
      </div>
    </Card>
  );
}
