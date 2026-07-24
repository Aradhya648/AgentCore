import { MANUAL_HELP, ManualHelpLink } from "@/components/ManualHelpLink";
import { IconButton } from "@/components/ui";
import { SimpleTooltip } from "@/components/ui/tooltip";
import type { GraphLayout } from "@/stores/graph";
import { GitBranch } from "lucide-react";
import { LAYOUT_OPTIONS } from "./constants";

interface GraphToolbarProps {
  layoutKind: GraphLayout;
  onLayoutKindChange: (kind: GraphLayout) => void;
  /** Scheduling summary from `batch_metrics` — shown when the turn has parallel workers. */
  metricsSummary?: string | null;
  /** Team turn with audit inject paths available (`planCapabilities.auditInject`). */
  injectFlowAvailable?: boolean;
  showAuditInjectFlow?: boolean;
  onShowAuditInjectFlowChange?: (on: boolean) => void;
}

/**
 * Layout selector (top-right). Zoom + fit live in
 * {@link import("./CanvasZoomControls")} (bottom-left).
 * Dependency layouts only: 左右流 / 树形.
 */
export function GraphToolbar({
  layoutKind,
  onLayoutKindChange,
  metricsSummary,
  injectFlowAvailable = false,
  showAuditInjectFlow = false,
  onShowAuditInjectFlowChange,
}: GraphToolbarProps) {
  return (
    <div
      className="absolute right-3 top-3 z-10 flex items-center gap-2"
      onContextMenu={(e) => e.stopPropagation()}
    >
      {metricsSummary && (
        <SimpleTooltip label="调度摘要：峰值并发 · 总时长 · 串行化次数（详情见诊断「调度」块）">
          <span className="rounded-lg border border-border bg-card/90 px-2 py-1 text-xs text-muted-foreground shadow-sm backdrop-blur">
            {metricsSummary}
          </span>
        </SimpleTooltip>
      )}
      <div className="flex items-center gap-0.5 rounded-lg border border-border bg-card/90 p-1 shadow-sm backdrop-blur">
        {injectFlowAvailable && onShowAuditInjectFlowChange && (
          <SimpleTooltip label="始终显示审计数据流（默认仅在打开 run 详情时高亮）">
            <span className="inline-flex">
              <IconButton
                onClick={() =>
                  onShowAuditInjectFlowChange(!showAuditInjectFlow)
                }
                aria-label="显示审计数据流"
                aria-pressed={showAuditInjectFlow}
                className={
                  showAuditInjectFlow
                    ? "bg-accent text-foreground hover:bg-accent hover:text-foreground"
                    : undefined
                }
              >
                <GitBranch size={14} />
              </IconButton>
            </span>
          </SimpleTooltip>
        )}
        {LAYOUT_OPTIONS.map((opt) => (
          <SimpleTooltip key={opt.kind} label={opt.label}>
            <span className="inline-flex">
              <IconButton
                onClick={() => onLayoutKindChange(opt.kind)}
                aria-label={opt.label}
                aria-pressed={layoutKind === opt.kind}
                className={
                  layoutKind === opt.kind
                    ? "bg-accent text-foreground hover:bg-accent hover:text-foreground"
                    : undefined
                }
              >
                {opt.icon}
              </IconButton>
            </span>
          </SimpleTooltip>
        ))}
      </div>
      <ManualHelpLink
        to={MANUAL_HELP.legend}
        className="rounded-full border border-border bg-card/90 shadow-sm backdrop-blur"
      />
    </div>
  );
}
