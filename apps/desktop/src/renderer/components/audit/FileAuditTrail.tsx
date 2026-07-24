import { Button } from "@/components/ui";
import { statusPillSoft } from "@/components/ui/tone-presets";
import type { FileAuditState } from "@/hooks/useFileAudit";
import { formatMessageTimeOfDay } from "@/lib/format";
import type { AgentAuditEvent } from "@/services/audit";
import { useSidePanelStore } from "@/stores/sidePanel";
import type { AuditOutcome } from "@agentcore/contract-rest-types/audit";
import { ChevronRight, History, Loader2 } from "lucide-react";

const OUTCOME_META: Record<AuditOutcome, { label: string; className: string }> =
  {
    ok: { label: "ok", className: statusPillSoft.success },
    denied: { label: "denied", className: statusPillSoft.muted },
    failed: { label: "failed", className: statusPillSoft.destructive },
    skipped: { label: "skipped", className: statusPillSoft.muted },
  };

function FileAuditEventRow({ event }: { event: AgentAuditEvent }) {
  const showRunDetail = useSidePanelStore((s) => s.showRunDetail);
  const outcome = OUTCOME_META[event.outcome] ?? OUTCOME_META.ok;
  const canNavigate = event.run_id != null && event.turn_id.length > 0;

  return (
    <div className="flex items-start gap-2 rounded-lg bg-muted px-2.5 py-1.5 text-xs">
      <span className="shrink-0 tabular-nums text-muted-foreground">
        {formatMessageTimeOfDay(event.created_at)}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <span className="rounded bg-background/60 px-1.5 py-0.5 font-mono text-foreground">
            {event.action}
          </span>
          <span
            className={`rounded-full px-1.5 py-0.5 font-mono ${outcome.className}`}
          >
            {outcome.label}
          </span>
        </span>
        {event.run_id && (
          <span className="mt-0.5 block truncate font-mono text-muted-foreground">
            run {event.run_id.slice(0, 8)}
          </span>
        )}
      </span>
      {canNavigate && (
        <Button
          variant="ghost"
          className="h-6 shrink-0 px-1.5 text-primary hover:bg-primary/10"
          onClick={() => {
            const runId = event.run_id;
            if (!runId) return;
            showRunDetail(event.turn_id, runId, event.action);
          }}
        >
          <span className="flex items-center gap-0.5">
            详情
            <ChevronRight size={12} />
          </span>
        </Button>
      )}
    </div>
  );
}

/**
 * 文件写入归因链：run / action / outcome / 时间，可跳转 run 详情 tab。
 */
export function FileAuditTrail({
  state,
  compact,
}: {
  state: FileAuditState;
  compact?: boolean;
}) {
  if (state.status === "idle" || state.status === "empty") {
    return (
      <p className="text-xs text-muted-foreground">
        {compact ? "暂无写入记录" : "暂无归因记录"}
      </p>
    );
  }

  if (state.status === "loading") {
    return (
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Loader2 size={12} className="animate-spin" />
        加载中…
      </p>
    );
  }

  return (
    <div className="space-y-1.5">
      {state.events.map((ev) => (
        <FileAuditEventRow key={ev.id} event={ev} />
      ))}
    </div>
  );
}

/** 带标题的归因区块（工作区预览 / 产物卡展开用）。 */
export function FileAuditSection({
  state,
  title = "写入归因",
}: {
  state: FileAuditState;
  title?: string;
}) {
  return (
    <section className="border-t border-border px-3 py-2.5">
      <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <History size={12} />
        {title}
      </p>
      <FileAuditTrail state={state} />
    </section>
  );
}
