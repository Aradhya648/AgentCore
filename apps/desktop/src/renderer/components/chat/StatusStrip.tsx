import { GraphTeamPreview } from "@/components/chat/TeamPreviewCard";
import { TeamSynthesisPreviewLine } from "@/components/chat/TeamSynthesisPreviewLine";
import { debatePreviewSubtitle } from "@/components/chat/debate/debateEntryCopy";
import {
  isTeamSynthesizing,
  teamSynthesisPhaseLabel,
  workerProgress,
} from "@/components/chat/teamSynthesisPhase";
import { useCoordinationWaitChrome } from "@/components/chat/useCoordinationWaitChrome";
import { Badge, Button, IconButton as UiIconButton } from "@/components/ui";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { hasUnpricedUsage, resolveTurnDisplayMoney } from "@/lib/cost";
import {
  COST_UNPRICED_LABEL,
  formatCostCaption,
  formatDuration,
} from "@/lib/format";
import {
  type TeamPreviewDisplay,
  isTerminalPhase,
  useActiveTurnPhase,
  useConversationStore,
} from "@/stores/conversation";
import {
  type Execution,
  elapsedMs,
  isDebate,
  useActiveExecField,
} from "@/stores/execution";
import type { ExecutionDetachedPayload } from "@/types/events";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  History,
  Loader2,
  Maximize2,
  MessagesSquare,
  Pause,
  Play,
  Square,
} from "lucide-react";

/** Props every lifecycle strip shares: projection + strip controls. */
export interface StatusStripProps {
  execution: Execution;
  expanded: boolean;
  onToggle: () => void;
  onMaximize: () => void;
  onReplay: () => void;
  /** 定向唤回「修订 vN」的回合：聊天正文不再内联版本对比大卡，改由状态条「改了 N 版」信号 chip
   *  深链画布放大态统一「对比」视图（前端UX设计.md §4.2/§6.4）。无修订 / 未提供则不出 chip。 */
  onOpenRevisions?: () => void;
  /** 协作质量轻信号（message_end.collab）；有非零才显。 */
  collabSummary?: string | null;
  /** Resolved 辩题/分工 preview — secondary Popover in StripControls (inline graph only). */
  teamPreview?: TeamPreviewDisplay | null;
  /** Incremental kickoff: overlay「新批次待确认」on the running strip. */
  pendingBatchBadge?: boolean;
}

/** First batch still actively running (incremental kickoff overlay gate).
 * Pending-only (next wave queued, nothing spinning) keeps the static pause strip. */
function hasActiveRunningRuns(execution: Execution): boolean {
  return execution.runs.some((r) => r.status === "running");
}

/**
 * Lifecycle header row above the collaboration graph (前端UX设计.md §三).
 * Dispatches to running / paused / completed / cancelled / failed variants.
 *
 * Incremental kickoff (`paused` while first batch still running): keep the
 * running strip scrolling and overlay a「新批次待确认」badge — do not replace
 * the whole strip with the static pause chrome.
 */
export function StatusStrip(props: StatusStripProps) {
  switch (props.execution.status) {
    case "completed":
      return <CompletedStrip {...props} />;
    case "cancelled":
      return <CompletedStrip {...props} stopped />;
    case "failed":
      return <FailureStrip {...props} />;
    case "paused":
      if (hasActiveRunningRuns(props.execution)) {
        return <RunningStrip {...props} pendingBatchBadge />;
      }
      return <PausedStrip {...props} />;
    default:
      return <RunningOrBackgroundStrip {...props} />;
  }
}

/** running：有 execution_detached → 静态后台条；否则原 RunningStrip（含旧 hold 转圈）。
 * 停止中优先走 RunningStrip，保留「停止中…」诚实过渡，不回退。 */
function RunningOrBackgroundStrip(props: StatusStripProps) {
  const turnPhase = useActiveTurnPhase();
  const detached = useActiveExecField((rt) => rt.executionDetached);
  if (turnPhase === "stopping") {
    return <RunningStrip {...props} />;
  }
  if (detached) {
    return <BackgroundRunningStrip {...props} detached={detached} />;
  }
  return <RunningStrip {...props} />;
}

function DebateTag() {
  return (
    <Badge tone="primary" pill className="mr-1.5 align-middle font-medium">
      辩论
    </Badge>
  );
}

function StripIconButton({
  icon,
  title,
  onClick,
  onContextMenu,
}: {
  icon: React.ReactNode;
  title: string;
  onClick: () => void;
  onContextMenu?: (e: React.MouseEvent) => void;
}) {
  return (
    <SimpleTooltip label={title}>
      <UiIconButton
        type="button"
        onClick={onClick}
        onContextMenu={onContextMenu}
        aria-label={title}
      >
        {icon}
      </UiIconButton>
    </SimpleTooltip>
  );
}

function StripControls({
  execution,
  expanded,
  onToggle,
  onMaximize,
  onReplay,
  onOpenRevisions,
  collabSummary,
  teamPreview,
}: StatusStripProps) {
  const turnPhase = useActiveTurnPhase();
  const stopping = turnPhase === "stopping";
  // paused+running keeps the running chrome (badge overlay); stop still available.
  const canStop =
    execution.status === "running" ||
    (execution.status === "paused" && hasActiveRunningRuns(execution));
  const canReplay =
    execution.status === "completed" || execution.status === "cancelled";
  const debate = isDebate(execution);
  // 「接续 N 次」仅计同人续派 / 热修；辩论 continue_run（陈词/质询/结辩）不是接续计数。
  const continuationCount = debate
    ? 0
    : execution.runs.filter((r) => r.continuesRunId != null).length;

  return (
    <>
      {canStop && (
        <StripIconButton
          icon={<Square size={15} />}
          title={stopping ? "停止中…" : "停止任务"}
          onClick={() => useConversationStore.getState().stopGeneration()}
        />
      )}
      {canReplay && (
        <StripIconButton
          icon={<Play size={15} />}
          title="回放协作过程"
          onClick={onReplay}
        />
      )}
      <StripIconButton
        icon={expanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
        title={expanded ? "收起协作图" : "展开协作图"}
        onClick={onToggle}
      />
      {/* 「改了 N 版」信号：本回合有定向唤回续写时，正文不再内联版本对比大卡，改为一枚 chip →
          深链画布放大态统一「对比」视图并排比对（前端UX设计.md §4.2/§6.4）。 */}
      {continuationCount > 0 && onOpenRevisions && (
        <SimpleTooltip label="查看接续链上各次产出并排对比（在画布）">
          <Button
            variant="ghost"
            className="ml-0.5 shrink-0 text-muted-foreground hover:text-foreground"
            icon={<History size={13} />}
            onClick={onOpenRevisions}
          >
            接续 {continuationCount} 次
          </Button>
        </SimpleTooltip>
      )}
      {collabSummary && (
        <SimpleTooltip label="本回合协作质量信号（明细见诊断）">
          <span className="ml-0.5 max-w-[14rem] truncate text-xs text-muted-foreground">
            {collabSummary}
          </span>
        </SimpleTooltip>
      )}
      {/* 辩题/分工：次要 ghost，主 CTA 左侧；内容走 Popover，不抢「打开辩论室 / 在画布打开」。 */}
      {teamPreview && <GraphTeamPreview preview={teamPreview} />}
      {/* 入口：辩论回合给醒目「打开辩论室」CTA（更可发现、直达群聊主视图），其余给通用「在画布打开」；
          二者同去处（放大态 Route A），辩论默认落群聊、回放走同一去处 + 自动播放。 */}
      <Button
        variant="ghost"
        className="ml-0.5 shrink-0 bg-primary/10 text-primary hover:bg-primary/20"
        icon={debate ? <MessagesSquare size={13} /> : <Maximize2 size={13} />}
        onClick={onMaximize}
      >
        {debate ? "打开辩论室" : "在画布打开"}
      </Button>
    </>
  );
}

function RunningStrip({
  execution,
  expanded,
  onToggle,
  onMaximize,
  onReplay,
  onOpenRevisions,
  collabSummary,
  teamPreview,
  pendingBatchBadge,
}: StatusStripProps) {
  const turnPhase = useActiveTurnPhase();
  const stopping = turnPhase === "stopping";
  const { completed, total } = execution.progress;
  const workers = workerProgress(execution);
  const { wait: coordinationWait, waitLabel } =
    useCoordinationWaitChrome(execution);
  const synthesizing =
    !isDebate(execution) &&
    !waitLabel &&
    isTeamSynthesizing(execution, {
      turnTerminal: isTerminalPhase(turnPhase),
    });
  const runningTitle = stopping
    ? "停止中…"
    : isDebate(execution)
      ? debatePreviewSubtitle(execution)
      : waitLabel
        ? waitLabel
        : synthesizing
          ? teamSynthesisPhaseLabel(execution)
          : execution.taskSummary;
  const waitCompleted = coordinationWait?.completed ?? 0;
  const waitTotal = coordinationWait?.total ?? 0;
  const progressLabel = waitLabel
    ? `${waitCompleted}/${waitTotal}`
    : synthesizing
      ? `${workers.completed}/${workers.total}`
      : `${completed}/${total}`;
  const highlightPhase = Boolean(waitLabel || synthesizing) && !stopping;

  return (
    <div
      className="px-4 py-3"
      data-testid={
        stopping
          ? "status-strip-stopping"
          : pendingBatchBadge
            ? "status-strip-pending-batch"
            : waitLabel
              ? "status-strip-coordination-wait"
              : synthesizing
                ? "status-strip-synthesizing"
                : undefined
      }
    >
      <div className="flex items-center gap-2">
        <Loader2 size={15} className="shrink-0 animate-spin text-primary" />
        <span
          className={`flex flex-1 items-center truncate text-sm font-medium ${
            highlightPhase || stopping ? "text-primary" : "text-foreground"
          }`}
        >
          {isDebate(execution) && <DebateTag />}
          <span className="truncate" data-testid="status-strip-running-title">
            {runningTitle}
          </span>
          {pendingBatchBadge ? (
            <Badge
              tone="primary"
              pill
              className="ml-2 shrink-0 font-medium"
              data-testid="status-strip-pending-batch-badge"
            >
              新批次待确认
            </Badge>
          ) : null}
          {highlightPhase ? (
            <span
              className="ml-2 size-1.5 shrink-0 animate-pulse rounded-full bg-primary motion-reduce:animate-none"
              aria-hidden
            />
          ) : null}
        </span>
        {!isDebate(execution) && (
          <span
            className={`shrink-0 text-xs ${
              highlightPhase
                ? "font-medium text-primary"
                : "text-muted-foreground"
            }`}
          >
            {progressLabel}
          </span>
        )}
        <StripControls
          execution={execution}
          expanded={expanded}
          onToggle={onToggle}
          onMaximize={onMaximize}
          onReplay={onReplay}
          onOpenRevisions={onOpenRevisions}
          collabSummary={collabSummary}
          teamPreview={teamPreview}
        />
      </div>
      <TeamSynthesisPreviewLine execution={execution} />
    </div>
  );
}

/**
 * Mid-turn pause (e.g. plan_review / team_preview gate) while the graph stays visible.
 * Static — no spinner — so「等待你确认」is not painted as「正在协作 / 卡住」。
 */
function PausedStrip({
  execution,
  expanded,
  onToggle,
  onMaximize,
  onReplay,
  onOpenRevisions,
  collabSummary,
  teamPreview,
}: StatusStripProps) {
  const { completed, total } = execution.progress;

  return (
    <div className="px-4 py-3" data-testid="status-strip-paused">
      <div className="flex items-center gap-2">
        <Pause size={15} className="shrink-0 text-primary" aria-hidden />
        <span className="flex flex-1 items-center truncate text-sm text-primary">
          {isDebate(execution) && <DebateTag />}
          <span className="truncate font-medium">
            已暂停 · 等待你确认后才会继续
          </span>
        </span>
        {!isDebate(execution) && (
          <span className="shrink-0 text-xs text-muted-foreground">
            {completed}/{total}
          </span>
        )}
        <StripControls
          execution={execution}
          expanded={expanded}
          onToggle={onToggle}
          onMaximize={onMaximize}
          onReplay={onReplay}
          onOpenRevisions={onOpenRevisions}
          collabSummary={collabSummary}
          teamPreview={teamPreview}
        />
      </div>
    </div>
  );
}

/**
 * 异步团队转后台：CEO 回合已收口，团队继续跑。
 * 静态（无转圈）——诚实呈现「后台运行中」，区别于 live RunningStrip。
 */
function BackgroundRunningStrip({
  execution,
  detached,
  expanded,
  onToggle,
  onMaximize,
  onReplay,
  onOpenRevisions,
  collabSummary,
  teamPreview,
}: StatusStripProps & { detached: ExecutionDetachedPayload }) {
  const completed = detached.completed;
  const total = detached.total;

  return (
    <div className="px-4 py-3" data-testid="status-strip-background">
      <div className="flex items-center gap-2">
        <Pause size={15} className="shrink-0 text-primary" aria-hidden />
        <span className="flex flex-1 items-center truncate text-sm font-medium text-foreground">
          {isDebate(execution) && <DebateTag />}
          <span
            className="truncate"
            data-testid="status-strip-background-title"
          >
            团队后台运行中
          </span>
        </span>
        {!isDebate(execution) && (
          <span className="shrink-0 text-xs text-muted-foreground">
            {completed}/{total}
          </span>
        )}
        <StripControls
          execution={execution}
          expanded={expanded}
          onToggle={onToggle}
          onMaximize={onMaximize}
          onReplay={onReplay}
          onOpenRevisions={onOpenRevisions}
          collabSummary={collabSummary}
          teamPreview={teamPreview}
        />
      </div>
    </div>
  );
}

function CompletedStrip({
  execution,
  stopped,
  expanded,
  onToggle,
  onMaximize,
  onReplay,
  onOpenRevisions,
  collabSummary,
  teamPreview,
}: StatusStripProps & { stopped?: boolean }) {
  const frames = useActiveExecField((rt) => rt.frames);
  // 交付对账（同 execution_id 保最新）：跑完 ≠ 交付过关。partial/blocked 时勿写单纯「团队完成」。
  const deliveryStatus = useActiveExecField((rt) => rt.deliveryStatus);
  const { completed, total } = execution.progress;
  const ms = elapsedMs(frames);
  const duration = ms > 0 ? formatDuration(ms) : "";

  // 子任务失败只靠 meta（n/m）+ 图节点色 + 右坞详情；完成/停止态不再挂红条复述。
  const deliveryUnmet =
    deliveryStatus?.state === "partial" || deliveryStatus?.state === "blocked";

  // 费用累计：以协作图上各 run.cost 之和为准（跨回合追加后仍覆盖全图），
  // 不再读「最新助手气泡」——追加回合的 message_end.cost 会盖掉宿主口径。
  const money = resolveTurnDisplayMoney(
    null,
    execution.runs.map((r) => r.cost),
  );
  // 未计价可见 (拍板 2026-07-20): BYOK 三层价卡全落空时有真实花费但无价可算——
  // 显式标注，不再静默省略费用段（读起来像「免费」）。金额位绝不冒充数字。
  const costSegment =
    money && money.nano > 0
      ? ` · ${stopped ? "已花 " : ""}${formatCostCaption(money.nano, money.estimated)}`
      : hasUnpricedUsage(execution.runs)
        ? ` · ${COST_UNPRICED_LABEL}`
        : "";

  return (
    <div className="px-4 py-3">
      <div className="flex items-center gap-2">
        {stopped ? (
          <Square size={15} className="shrink-0 text-muted-foreground" />
        ) : deliveryUnmet ? (
          <AlertTriangle
            size={15}
            className={
              deliveryStatus?.state === "blocked"
                ? "shrink-0 text-destructive"
                : "shrink-0 text-warning"
            }
            data-testid="status-strip-delivery-unmet-icon"
          />
        ) : (
          <CheckCircle2 size={15} className="shrink-0 text-success" />
        )}
        <span className="flex-1 text-sm text-foreground">
          {!stopped && isDebate(execution) && <DebateTag />}
          <span className="font-medium">
            {stopped
              ? "已停止"
              : isDebate(execution)
                ? debatePreviewSubtitle(execution)
                : deliveryUnmet
                  ? "已跑完 · 交付未过关"
                  : "团队完成"}
          </span>
          {/* 完成态 meta（Agent 数 / 子任务 / 用时 / ¥）辩论与多 Agent 同口径：
              ¥ 归状态条（前端成本呈现）；标题仍走辩论预告片文案。 */}
          <span className="text-muted-foreground">
            {` · ${execution.agents.length} 个 Agent · ${completed}/${total} 子任务${
              duration ? ` · 用时 ${duration}` : ""
            }${costSegment}`}
          </span>
        </span>
        <StripControls
          execution={execution}
          expanded={expanded}
          onToggle={onToggle}
          onMaximize={onMaximize}
          onReplay={onReplay}
          onOpenRevisions={onOpenRevisions}
          collabSummary={collabSummary}
          teamPreview={teamPreview}
        />
      </div>
    </div>
  );
}

function FailureStrip({
  execution,
  expanded,
  onToggle,
  onMaximize,
  onReplay,
  onOpenRevisions,
  collabSummary,
  teamPreview,
}: StatusStripProps) {
  const detached = useActiveExecField((rt) => rt.executionDetached);

  const failedRun = execution.runs.find((s) => s.status === "failed") ?? null;
  const failedAgent = failedRun
    ? (execution.agents.find((a) => a.id === failedRun.agentId) ?? null)
    : null;

  const money = resolveTurnDisplayMoney(
    null,
    execution.runs.map((r) => r.cost),
  );
  // 未计价可见 (拍板 2026-07-20)：无价可算时不写「已花」+ 数字，改挂未计价标注。
  const spentSegment =
    money != null && money.nano > 0
      ? ` · 已花 ${formatCostCaption(money.nano, money.estimated)}`
      : hasUnpricedUsage(execution.runs)
        ? ` · ${COST_UNPRICED_LABEL}`
        : null;

  return (
    <div className="px-4 py-3" data-testid="status-strip-failed">
      {detached ? (
        <div
          className="mb-2 flex items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-xs text-foreground"
          data-testid="status-strip-failed-detached"
        >
          <Pause size={13} className="shrink-0 text-primary" aria-hidden />
          <span className="font-medium">团队后台运行中</span>
          {!isDebate(execution) && (
            <span className="text-muted-foreground">
              {detached.completed}/{detached.total}
            </span>
          )}
          <span className="text-muted-foreground">
            · 对话已因错误收口，团队仍在继续
          </span>
        </div>
      ) : null}
      <div className="flex items-center gap-2">
        <AlertTriangle size={15} className="shrink-0 text-destructive" />
        <span className="flex-1 text-sm text-foreground">
          <span className="font-medium">任务失败</span>
          {spentSegment && (
            <span className="text-muted-foreground">{spentSegment}</span>
          )}
        </span>
        <StripControls
          execution={execution}
          expanded={expanded}
          onToggle={onToggle}
          onMaximize={onMaximize}
          onReplay={onReplay}
          onOpenRevisions={onOpenRevisions}
          collabSummary={collabSummary}
          teamPreview={teamPreview}
        />
      </div>

      <div className="mt-2 rounded-lg bg-muted/40 px-3 py-2 text-sm">
        {failedAgent || failedRun ? (
          <p className="text-foreground">
            {failedAgent && (
              <span className="font-medium">{failedAgent.role}</span>
            )}
            {failedRun && (
              <span className="text-muted-foreground"> · {failedRun.task}</span>
            )}
          </p>
        ) : (
          <p className="text-foreground">执行过程中出现错误</p>
        )}
        <p className="mt-1 whitespace-pre-wrap break-words text-xs text-destructive">
          {failedRun?.error ?? "未获取到具体错误信息。"}
        </p>
      </div>
    </div>
  );
}
