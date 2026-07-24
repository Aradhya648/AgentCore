import { BackgroundTaskCard } from "@/components/chat/BackgroundTaskCard";
import { CheckpointCard } from "@/components/chat/CheckpointCard";
import { ConversationDecisionPrompts } from "@/components/chat/ConversationDecisionPrompts";
import { EscalationCards } from "@/components/chat/EscalationCard";
import { PlanReviewCard } from "@/components/chat/PlanReviewCard";
import { RetryBanner } from "@/components/chat/RetryBanner";
import { RecoveryActions } from "@/components/chat/StatusStrip";
import { isTurnRecoverable } from "@/lib/turnRecoverable";
import {
  useBackgroundTasks,
  useWorkspaceRootId,
} from "@/stores/backgroundTasks";
import { useCommandPanelStore } from "@/stores/commandPanel";
import {
  type Message,
  assistantProjectionId,
  useActiveError,
  useActiveMessages,
  useConversationStore,
} from "@/stores/conversation";
import {
  type Execution,
  ExecutionScopeContext,
  useMessageExecution,
} from "@/stores/execution";
import {
  messageCheckpoints,
  messagePlanReviews,
  messageTeamPreviews,
  useInteractionStore,
  useMessageInteractionCards,
} from "@/stores/interactions";
import { usePausedTurnStore } from "@/stores/pausedTurns";
import { useSidePanelStore } from "@/stores/sidePanel";
import { AlertTriangle } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";

/** Re-export for canvas consumers that historically imported from this module. */
export { isTurnRecoverable };

/**
 * 画布「图上指挥」指挥台 (前端UX设计.md §6.2). The boss powers散落在聊天流里
 * (前端UX设计.md §三): ask_user / plan_review / 工作者上报 (turn level) + 工具放行
 * approval / 待恢复续跑 resume + 救火 (conversation / turn level). On the canvas they
 * belong where they happen, but the actionable cards are sizable, so rather than
 * floating popovers over nodes — and rather than a SECOND right-hand dock競 the
 * unified side panel for width — the 指挥台 is a fixed second tab in that one side
 * panel (after 「工作区」, §十). It renders the SAME cards the chat surfaces do
 * ({@link CheckpointCard} / {@link PlanReviewCard} / {@link EscalationCards} /
 * {@link ApprovalPrompt} / {@link ResumePrompt} / {@link RetryBanner} /
 * {@link RecoveryActions} / {@link BackgroundTaskCard}), reused verbatim, so a
 * decision read / made / 救火 / 应用 here is identical to one in chat and folds
 * through the very same service + SSE (no second data path — 设计 §二 单一数据源).
 *
 * Why every scope lives here: in canvas mode `ChatView` + `InlineTeamGraph` +
 * `MessageList` are unmounted, so their conversation-level approval / resume /
 * transport-retry prompts, the team strip's 救火行, and the timeline's 后台云端任务
 * cards would be invisible (unactionable) without this. The turn-level cards +
 * recovery scope to the focused turn (`message` + projected `execution`); approval /
 * resume / RetryBanner / 后台任务 are self-contained (own store + active conversation)
 * so they ride along regardless of `message`. `interactive` is the focused turn's
 * live, non-terminal state; a reloaded / ended turn renders its cards as passive
 * records. {@link useCommandRegion} derives all of this live from stores (the canvas
 * only publishes `active` + the focused message id via {@link useCommandPanelStore})
 * and owns the auto-surface; 后台云端任务 是 非阻塞的「另一类」, so it renders last and
 * never inflates the 待你拍板 decision count.
 */

/** Count of UNANSWERED boss decisions on ONE turn — 工作者上报 (escalation) +, by default,
 * 交互式辩论的逐轮掌舵 (debate round), PLUS an inline ask_user / plan_review **only while the
 * turn is still live**. Turn-scoped: drives the focused node's「待你拍板」chip (counts debate,
 * so the overview still flags「zoom in to steer」), and is the turn-level summand of the host's
 * panel auto-surface (which also adds conversation-level approval / resume).
 *
 * 挂起即收口 (②, Phase 3): a finalized ask_user / plan_review (the normal path — SUSPEND→PAUSED)
 * renders inline as a passive record; its actionable surface is the conversation-level durable
 * resume (counted via `resumeCount` in the dock, and the node carries a `paused` status ring). So
 * we count an inline checkpoint ONLY while `message.isStreaming` (the rare §六-1 backend thin-net
 * wait); counting a terminal turn's inline pending would double-count it against that resume.
 *
 * `includeDebate=false` excludes debate round boundaries — the 指挥台 passes this because debate
 * 掌舵 now lives canvas-native in the 群聊 room ({@link import("../chat/debate/arena/DebateArena").DebateArena}
 * 的 SteeringBar), NOT in the dock; counting it there would pop an empty panel for a decision the
 * room already owns (群聊为唯一掌舵处, 前端UX设计.md §4.3). */
export function countPendingDecisions(
  message: Message | undefined,
  execution: Execution | null | undefined,
  opts: { includeDebate?: boolean; conversationId?: string | null } = {},
): number {
  const { includeDebate = true, conversationId } = opts;
  let n = 0;
  const convId = conversationId ?? "";
  // Inline ask_user / plan_review / team_preview count ONLY while the turn is live
  // (see docstring): once finalized, the action is the conversation-level resume,
  // not this now-passive inline card.
  if (message?.isStreaming && convId) {
    for (const c of messageCheckpoints(convId, message.id))
      if (c.status === "pending") n++;
    for (const p of messagePlanReviews(convId, message.id))
      if (p.status === "pending") n++;
    for (const t of messageTeamPreviews(convId, message.id))
      if (t.status === "pending") n++;
  }
  for (const r of execution?.runs ?? [])
    for (const e of r.escalations) if (e.status === "pending") n++;
  if (includeDebate && convId) {
    // ambient 掌舵不进 InteractionStore——指挥台对辩论恒传 includeDebate=false。
    void includeDebate;
    void convId;
  }
  return n;
}

/** Everything the 指挥台 tab renders / badges, derived live by {@link useCommandRegion}. */
export interface CommandRegionData {
  /**
   * Canvas mode is on — the fixed 指挥台 tab should appear in the strip (even with
   * nothing actionable yet; empty body is fine until a decision arrives).
   */
  show: boolean;
  /** Focused turn (turn-level cards + 救火 scope); absent for a no-team-turn focus. */
  message?: Message;
  /** Focused turn's projected execution — gates / describes the 救火行. */
  execution: Execution | null;
  conversationId: string | null;
  /** Focused turn is live & non-terminal — its cards are actionable vs passive records. */
  interactive: boolean;
  /** Pending DECISION count for the tab badge (turn-level + conversation-level approval/resume). */
  pending: number;
  /**
   * Tab-strip badge: decisions + 救火 + 后台任务 — anything that auto-surfaced the dock
   * but did not steal focus onto this tab.
   */
  badge: number;
}

/**
 * Drive the 指挥台 tab from stores. Turn focus is a canvas concept, so the host
 * {@link import("./ConversationCanvas")} publishes `active` + the focused message id
 * via {@link useCommandPanelStore}; everything else (the focused turn's message +
 * projected execution, the conversation-level approval / resume / 救火 / 后台云端任务
 * signals) is derived LIVE here — no snapshot copy, single data source. Owns the
 * auto-surface: a brand-new actionable item opens the dock (without switching the
 * active tab, so a run/workspace the user is reading stays put) and updates the
 * 指挥台 tab badge.
 */
export function useCommandRegion(): CommandRegionData {
  const active = useCommandPanelStore((s) => s.active);
  const focusedMessageId = useCommandPanelStore((s) => s.focusedMessageId);

  const conversationId = useConversationStore((s) => s.currentConversationId);
  const messages = useActiveMessages();
  const message = useMemo(
    () =>
      messages.find(
        (m) =>
          m.id === focusedMessageId || m.serverMessageId === focusedMessageId,
      ),
    [messages, focusedMessageId],
  );
  const execution = useMessageExecution(focusedMessageId);
  const convError = useActiveError();
  const approvalCount = useInteractionStore((s) => {
    if (!conversationId) return 0;
    let n = 0;
    for (const e of s.byId.values()) {
      if (
        e.conversationId === conversationId &&
        e.kind === "approval" &&
        (e.status === "pending" || e.status === "submitting")
      ) {
        n++;
      }
    }
    return n;
  });
  const resumeCount = usePausedTurnStore(
    (s) => s.pending.filter((p) => p.conversationId === conversationId).length,
  );
  const backgroundCount = useBackgroundTasks(conversationId).length;

  // 辩论逐轮掌舵不计入 dock（群聊 room 的 SteeringBar 是唯一掌舵处）；其提醒由总览焦点节点的
  // 「待你拍板」chip + 放大查看入口承载，dock 不为它弹面。
  const turnDecisions = countPendingDecisions(message, execution, {
    includeDebate: false,
    conversationId,
  });
  const pending = turnDecisions + approvalCount + resumeCount;
  const firefighting = !!convError || isTurnRecoverable(execution);
  // 后台云端任务 是 非阻塞的「另一类」: it keeps the region present but never inflates the
  // 待你拍板 badge (`pending`); the tab-strip badge (`badge`) includes it so the user
  // can still discover background work without being yanked onto 指挥台.
  const badge = pending + (firefighting ? 1 : 0) + backgroundCount;
  const show = active;

  // Auto-surface: a brand-new actionable item opens the dock — but never switches the
  // active tab, so a run/workspace the user is reading stays put; only the 指挥台 tab
  // badge updates. Baseline on canvas mount (first active tick) without opening —
  // re-entering canvas must not treat existing pending work as "new" just because chat
  // mode zeroed the ref on the way out.
  const prevActionable = useRef<number | null>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: conversationId is an intentional re-run key — reset the baseline when switching conversations.
  useEffect(() => {
    prevActionable.current = null;
  }, [conversationId]);
  useEffect(() => {
    if (!active) return;
    if (prevActionable.current === null) {
      prevActionable.current = badge;
      return;
    }
    if (badge > prevActionable.current) {
      const sp = useSidePanelStore.getState();
      const contextId = conversationId ? `command:${conversationId}` : null;
      if (contextId && sp.isAutoSurfaceDismissed(contextId)) {
        sp.incrementPendingBadge();
      } else {
        sp.openPanel();
      }
    }
    prevActionable.current = badge;
  }, [active, badge, conversationId]);

  return {
    show,
    message,
    execution,
    conversationId,
    interactive: message?.isStreaming ?? false,
    pending,
    badge,
  };
}

/**
 * 指挥台 tab body (前端UX设计.md §6.2 · §十): the boss's pending-decision / 救火 /
 * 后台云端任务 cards. Lives in its own tab so deep-reading a run and 拍板 stay on
 * different screens — the user switches tabs deliberately. Props come from
 * {@link useCommandRegion}.
 */
export function CommandPanelBody({
  message,
  execution,
  conversationId,
  interactive,
}: Pick<
  CommandRegionData,
  "message" | "execution" | "conversationId" | "interactive"
>) {
  // 统一投影键（时间线一期）：interaction entries key by `serverMessageId ?? id`
  // (execMessageId)，query must match or the dock's cards silently vanish.
  const { checkpoints, planReviews } = useMessageInteractionCards(
    conversationId,
    message ? assistantProjectionId(message) : "",
  );

  const recoverable = isTurnRecoverable(execution);
  const failedCount =
    execution?.runs.filter((r) => r.status === "failed").length ?? 0;
  const recoveryNotice =
    execution?.status === "cancelled"
      ? "本回合已停止。"
      : failedCount > 0
        ? `${failedCount} 个子任务失败。`
        : "本回合执行失败。";

  return (
    <div className="h-full overflow-y-auto py-3">
      {/* 救火 (firefighting): conversation-level transport error + focused turn's
          inline recovery link (retry-failed XOR regenerate). 「忽略」is implicit on
          the next user turn. RecoveryActions retries under this turn's ExecutionScope. */}
      <RetryBanner />
      {recoverable && message && (
        <ExecutionScopeContext.Provider value={assistantProjectionId(message)}>
          <div className="mx-4 mb-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2">
            <div className="flex items-start gap-2 text-xs text-destructive">
              <AlertTriangle size={13} className="mt-0.5 shrink-0" />
              <span>{recoveryNotice}</span>
            </div>
            <RecoveryActions
              hasFailedRuns={
                execution?.status === "completed" &&
                execution.runs.some((r) => r.status === "failed")
              }
            />
          </div>
        </ExecutionScopeContext.Provider>
      )}
      {/* Conversation-level decisions (self-contained: own store + active
          conversation). They bring their own mx-4 mb-2 gutter, so the turn-level
          cards below match with px-4 and the mb-2 supplies the inter-group gap. */}
      <ConversationDecisionPrompts />
      {/* Turn-level: scoped to the focused turn's message + execution. */}
      <div className="space-y-2 px-4">
        {checkpoints.map((cp) => (
          <CheckpointCard key={cp.id} checkpoint={cp} />
        ))}
        {planReviews.map((pr) => (
          <PlanReviewCard key={pr.id} review={pr} />
        ))}
        {message && (
          <EscalationCards
            messageId={assistantProjectionId(message)}
            conversationId={conversationId}
            interactive={interactive}
          />
        )}
        {/* 辩论逐轮掌舵不在此渲染：它是 canvas 原生的，归 群聊 room 的 SteeringBar
            （前端UX设计.md §4.3「群聊为唯一掌舵处」）。dock 只复活聊天面在画布态被卸载的卡。 */}
      </div>
      {/* 后台云端任务 (handoff jobs, 非阻塞 · 跨对话的另一类): last, below every
          blocking decision. */}
      <CanvasBackgroundTasks conversationId={conversationId} />
    </div>
  );
}

/**
 * Self-contained feed of this conversation's 后台云端任务 (handoff jobs, 双模式工作区
 * 交接「方案 B」). In chat mode these merge into the message timeline ({@link
 * import("../chat/MessageList")}); in canvas mode that timeline is unmounted, so the
 * 指挥台 is the only place they can be seen / 应用 (前端UX设计.md §6.2). The host {@link
 * import("./ConversationCanvas")} runs `useBackgroundTasksSync` (it stays mounted
 * while this panel may be closed, so the job list keeps polling); this just reads the
 * already-synced store + the bound local root id (which a succeeded job's inline
 * 评审 needs to write the result back). Renders nothing when there are no jobs. */
function CanvasBackgroundTasks({
  conversationId,
}: {
  conversationId: string | null;
}) {
  const tasks = useBackgroundTasks(conversationId);
  const rootId = useWorkspaceRootId(conversationId);
  if (tasks.length === 0) return null;
  return (
    <div className="mx-4 mt-2 space-y-2">
      {tasks.map((job) => (
        <BackgroundTaskCard key={job.id} job={job} rootId={rootId} />
      ))}
    </div>
  );
}
