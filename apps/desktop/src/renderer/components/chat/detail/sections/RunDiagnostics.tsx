import { Button } from "@/components/ui";
import { usePersistentDisclosure } from "@/stores/disclosure";
import type { BatchMetricsSnapshot, RunNode } from "@/stores/execution";
import { ChevronDown, ChevronRight } from "lucide-react";
import { DiagRow } from "./shared";

/**
 * 诊断 / 开发者面板 (前端UX设计.md §十) — gated behind 诊断模式, never shown to 大众.
 * Surfaces the low-level identifiers that tie this run to the server journal + logs
 * (run / agent / execution / trace ids, the run's wire shape): noise for normal use,
 * but the first thing you reach for when inspecting a turn in-place. Display-only,
 * selectable mono text; one-click 排查包 copy lives on the bubble / error card
 * (always available, not behind this gate).
 */
export function DiagnosticSection({
  run,
  executionId,
  traceId,
  batches,
  collab,
  keyBase,
}: {
  run: RunNode;
  executionId: string;
  traceId: string | null;
  batches: BatchMetricsSnapshot[];
  collab?: import("@/types/events").TurnCollabMetrics | null;
  keyBase: string;
}) {
  const [expanded, setExpanded] = usePersistentDisclosure(
    `${keyBase}:diag`,
    false,
  );

  return (
    <section className="mb-4 last:mb-0">
      <Button
        variant="ghost"
        onClick={() => setExpanded((v) => !v)}
        className="h-auto w-full justify-start gap-1.5 px-0 py-0 hover:bg-transparent"
      >
        <span className="flex w-full items-center gap-1.5">
          {expanded ? (
            <ChevronDown size={14} className="shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight
              size={14}
              className="shrink-0 text-muted-foreground"
            />
          )}
          <span className="flex-1 text-left text-xs font-medium text-muted-foreground">
            诊断信息
          </span>
        </span>
      </Button>

      {expanded && (
        <div className="mt-2 select-text space-y-2 rounded-lg bg-muted p-3">
          <DiagRow label="运行 ID" value={run.id} />
          <DiagRow label="Agent ID" value={run.agentId} />
          <DiagRow label="类型" value={run.kind} />
          {run.parentRunId && (
            <DiagRow label="上级运行" value={run.parentRunId} />
          )}
          {run.dependsOn.length > 0 && (
            <DiagRow label="依赖" value={run.dependsOn.join(", ")} />
          )}
          {run.model && <DiagRow label="模型" value={run.model} />}
          <DiagRow label="执行 ID" value={executionId} />
          <DiagRow label="Trace ID" value={traceId ?? "—"} />
          {batches.length > 0 && <SchedulingDiag batches={batches} />}
          {collab != null && <CollabDiag collab={collab} />}
        </div>
      )}
    </section>
  );
}

/** 调度埋点量化 (深层诊断指标, §十): the turn's WaveScheduler snapshot(s), rendered inside
 * 诊断信息. Execution-level (not run-scoped) — it answers「这回合的并发真的发生了吗 / width 卡没卡
 * / 自我纠偏触发了几次」. Most turns carry one batch; a checkpoint/scope yield + resume adds more.
 * Exported for the render test (the panel is dev-gated, so the shoot harness never reaches it). */
export function SchedulingDiag({
  batches,
}: { batches: BatchMetricsSnapshot[] }) {
  return (
    <div className="mt-1 border-t border-border/60 pt-2">
      <p className="mb-1 text-xs font-medium text-muted-foreground">
        调度{batches.length > 1 ? ` · ${batches.length} 批` : ""}
      </p>
      {batches.map((b, i) => (
        <div
          key={`${b.wallMs}-${b.nodes}-${b.peakRunning}-${b.width}`}
          className="mb-2 space-y-1 last:mb-0"
        >
          {batches.length > 1 && (
            <p className="text-xs text-muted-foreground">批次 {i + 1}</p>
          )}
          <DiagRow
            label="节点 / 并发"
            value={`${b.nodes} · 上限 ${b.width} · 峰值 ${b.peakRunning}`}
          />
          <DiagRow
            label="平均并发 / 用时"
            value={`${b.wallMs > 0 ? (b.busyMs / b.wallMs).toFixed(2) : "—"} · ${b.wallMs}ms`}
          />
          <DiagRow label="结果" value={schedOutcome(b)} />
          {b.slotStarved > 0 && (
            <DiagRow label="槽位等待" value={`${b.slotStarved} 次`} />
          )}
          {(b.bindBoundaries > 0 ||
            b.scopeBoundaries > 0 ||
            b.checkpointBoundaries > 0) && (
            <DiagRow
              label="自我纠偏"
              value={`绑定 ${b.bindBoundaries} · 操舵 ${b.scopeBoundaries} · 复核 ${b.checkpointBoundaries}`}
            />
          )}
          {b.escalations > 0 && (
            <DiagRow
              label="队员上报"
              value={`${b.escalations}（scope ${b.scopeEscalations}）`}
            />
          )}
        </div>
      ))}
    </div>
  );
}

/** 协作质量 (深层诊断指标, §十五): turn-level orchestration signals from turn_metrics /
 * message_end — boundary yields / scope drift / revises / escalations. Execution-level
 * (not run-scoped); answers「这回合编排稳不稳 / 返工多不多」. */
export function CollabDiag({
  collab,
}: { collab: import("@/types/events").TurnCollabMetrics }) {
  const hasSignal =
    collab.boundary_yields > 0 ||
    collab.scope_signals > 0 ||
    collab.revises > 0 ||
    collab.escalations > 0 ||
    (collab.audit_drops ?? 0) > 0;
  if (!hasSignal) return null;

  return (
    <div className="mt-1 border-t border-border/60 pt-2">
      <p className="mb-1 text-xs font-medium text-muted-foreground">协作质量</p>
      {collab.boundary_yields > 0 && (
        <DiagRow label="自我纠偏让出" value={`${collab.boundary_yields} 次`} />
      )}
      {collab.scope_signals > 0 && (
        <DiagRow label="漂移信号" value={`${collab.scope_signals} 次`} />
      )}
      {collab.revises > 0 && (
        <DiagRow label="定向唤回" value={`${collab.revises} 次`} />
      )}
      {collab.escalations > 0 && (
        <DiagRow label="队员上报" value={`${collab.escalations} 次`} />
      )}
      {(collab.audit_drops ?? 0) > 0 && (
        <DiagRow label="审计采集降级" value={`${collab.audit_drops} 次`} />
      )}
    </div>
  );
}

/** 调度结果一行：完成数恒显，失败 / 跳过仅在 >0 时追加（无则不喧宾夺主）。 */
function schedOutcome(b: BatchMetricsSnapshot): string {
  const parts = [`完成 ${b.completed}`];
  if (b.failed > 0) parts.push(`失败 ${b.failed}`);
  if (b.skipped > 0) parts.push(`跳过 ${b.skipped}`);
  return parts.join(" · ");
}
