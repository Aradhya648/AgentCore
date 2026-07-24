import { Gavel } from "lucide-react";

/**
 * 方案 C「一个焦点 + 一个入口」：冷交互卡（plan_review / team_preview）挂起态在
 * 时间线上的**单行极简标记**——只标注「这里停了、等你确认后才会继续」，完整上下文与操作面
 * 统一归下方 ResumePrompt（拍板中心）。resolved 留痕仍由各卡的 Resolved 形态承载。
 *
 * 用 primary 色强化可见性，避免长期挂起被误读成「图在跑 / 卡住」。
 */
export function PendingDecisionMarker({ label }: { label: string }) {
  return (
    <div
      data-testid="pending-decision-marker"
      className="mt-2 flex items-center gap-1.5 rounded-lg border border-primary/25 bg-primary/5 px-2 py-1.5 text-xs text-primary"
    >
      <Gavel size={13} className="shrink-0" aria-hidden />
      <span className="min-w-0 truncate font-medium">
        {label} · 入口在下方拍板卡
      </span>
    </div>
  );
}
