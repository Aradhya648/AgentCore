import { getConversations } from "@/hooks/useConversations";
import { showNativeNotification } from "@/lib/nativeNotification";
import {
  conversationIdFromHash,
  isTransientRoute,
  runtimeHasError,
} from "@/lib/teamActivity";
import { notifyInfo } from "@/lib/toast";
import { DRAFT_KEY, useConversationStore } from "@/stores/conversation";
import { useInteractionStore } from "@/stores/interactions";
import { usePausedTurnStore } from "@/stores/pausedTurns";

/**
 * 跨对话完成通知 (前端UX设计.md §一 全局协作感知)：只读订阅对话生成态 + 审批态 + 挂起态，当用户**不在**某对话
 * 页面时，该对话的关键事件（回合完成 / 失败 / 需要审批 / 挂起等拍板）弹一条带「跳转」action 的 notifyInfo。
 * 纯前端感知层——不碰 SSE 契约 / 协议 fold，不新增事件；接线一次于 AppShell（与 realtime /
 * updates 同处），随会话常驻。
 *
 * 挂起收口（finish_reason=paused → isGenerating↓）不是「已完成」：完成通道跳过仍有
 * pausedTurns 的对话；挂起感知统一走 pausedTurns 订阅（team_preview → 等待确认后开工；
 * ask_user / plan_review → 等待确认后继续）。
 *
 * 幕终推进卡（stage_card pending，非冷挂起）：完成通道同样跳过「已完成」，感知走
 * InteractionStore 订阅（「需要你确认推进」）。
 */

/** 从会话缓存解析标题（非 React 调用）——缺（未加载 / 已删）时返回 null，调用方据此静默。 */
function titleOf(id: string): string | null {
  return getConversations().find((c) => c.id === id)?.title ?? null;
}

/** 跳转到某对话：先同步切当前会话（即时反馈），再驱动 hash 路由（等同点 <Link>）。 */
function jumpTo(conversationId: string): void {
  useConversationStore.getState().switchConversation(conversationId);
  window.location.hash = `/conversations/${conversationId}`;
}

/** 该对话不是当前正看的、也不在开发回放态 → 值得弹通知。 */
function shouldNotify(conversationId: string): boolean {
  const hash = window.location.hash;
  if (isTransientRoute(hash)) return false;
  return conversationIdFromHash(hash) !== conversationId;
}

function notifyTurnEnd(conversationId: string, failed: boolean): void {
  if (!shouldNotify(conversationId)) return;
  const title = titleOf(conversationId);
  if (!title) return;
  const message = failed ? `「${title}」执行失败` : `「${title}」已完成`;
  notifyInfo(message, {
    action: { label: "查看", onClick: () => jumpTo(conversationId) },
  });
  void showNativeNotification("AgentCore", message, { conversationId });
}

function notifyApproval(conversationId: string): void {
  if (!shouldNotify(conversationId)) return;
  const title = titleOf(conversationId);
  if (!title) return;
  const message = `「${title}」需要审批`;
  notifyInfo(message, {
    action: { label: "去处理", onClick: () => jumpTo(conversationId) },
  });
  void showNativeNotification("AgentCore", message, { conversationId });
}

function notifyKickoff(conversationId: string): void {
  if (!shouldNotify(conversationId)) return;
  const title = titleOf(conversationId);
  if (!title) return;
  const message = `「${title}」等待你确认后才会开工`;
  notifyInfo(message, {
    action: { label: "去处理", onClick: () => jumpTo(conversationId) },
  });
  void showNativeNotification("AgentCore", message, { conversationId });
}

/** ask_user / plan_review 挂起：与 team_preview 同通道，文案区分「开工」vs「拍板」。 */
function notifyAwaitingDecision(conversationId: string): void {
  if (!shouldNotify(conversationId)) return;
  const title = titleOf(conversationId);
  if (!title) return;
  const message = `「${title}」等待你确认后才会继续`;
  notifyInfo(message, {
    action: { label: "去处理", onClick: () => jumpTo(conversationId) },
  });
  void showNativeNotification("AgentCore", message, { conversationId });
}

/** 幕终阶段推进卡：对齐 approval / kickoff 通道。 */
function notifyStageAdvance(conversationId: string): void {
  if (!shouldNotify(conversationId)) return;
  const title = titleOf(conversationId);
  if (!title) return;
  const message = `「${title}」需要你确认推进`;
  notifyInfo(message, {
    action: { label: "去处理", onClick: () => jumpTo(conversationId) },
  });
  void showNativeNotification("AgentCore", message, { conversationId });
}

function pendingApprovalIds(): string[] {
  const out: string[] = [];
  for (const e of useInteractionStore.getState().byId.values()) {
    if (
      e.kind === "approval" &&
      (e.status === "pending" || e.status === "submitting")
    ) {
      out.push(e.id);
    }
  }
  return out;
}

function pendingStageCardIds(): string[] {
  const out: string[] = [];
  for (const e of useInteractionStore.getState().byId.values()) {
    if (
      e.kind === "stage_card" &&
      (e.status === "pending" || e.status === "submitting")
    ) {
      out.push(e.id);
    }
  }
  return out;
}

/** All durable pause frames (any SuspensionKind) — seed + live dedup keys. */
function pendingPauseIds(): string[] {
  return usePausedTurnStore.getState().pending.map((p) => p.checkpointId);
}

function conversationHasPausedTurn(conversationId: string): boolean {
  return usePausedTurnStore
    .getState()
    .pending.some((p) => p.conversationId === conversationId);
}

function conversationHasPendingStageCard(conversationId: string): boolean {
  for (const e of useInteractionStore.getState().byId.values()) {
    if (
      e.conversationId === conversationId &&
      e.kind === "stage_card" &&
      (e.status === "pending" || e.status === "submitting")
    ) {
      return true;
    }
  }
  return false;
}

/**
 * Start the ambient cross-conversation notifier. Returns an unsubscribe fn (AppShell
 * calls it on unmount). Idempotent per call — each invocation owns its own subscriptions.
 */
export function startTeamActivityNotifications(): () => void {
  // Seed with approvals / stage cards / pauses already pending at startup so a
  // reconnect replay doesn't re-toast prompts the user already knows about.
  const notifiedApprovals = new Set<string>(pendingApprovalIds());
  const notifiedStageCards = new Set<string>(pendingStageCardIds());
  const notifiedPauses = new Set<string>(pendingPauseIds());

  const unsubConversation = useConversationStore.subscribe((state, prev) => {
    for (const [id, prevRt] of Object.entries(prev.byId)) {
      if (id === DRAFT_KEY || !prevRt.isGenerating) continue;
      const nextRt = state.byId[id];
      if (nextRt?.isGenerating) continue; // still streaming — not a turn boundary
      const failedAtBoundary = nextRt
        ? runtimeHasError(nextRt)
        : runtimeHasError(prevRt);
      queueMicrotask(() => {
        // Durable pause close lands pausedTurns in the same sync turn as
        // finalizeLastMessage; by this microtask the frame is already there.
        // Skip「已完成」— pause perception is the pausedTurns channel only.
        if (conversationHasPausedTurn(id)) return;
        // 幕终推进卡：turn 正常收口但仍待用户确认推进——勿误报「已完成」。
        if (conversationHasPendingStageCard(id)) return;
        const latest = useConversationStore.getState().byId[id];
        const failed = latest ? runtimeHasError(latest) : failedAtBoundary;
        notifyTurnEnd(id, failed);
      });
    }
  });

  const unsubInteractions = useInteractionStore.subscribe((state) => {
    for (const e of state.byId.values()) {
      if (e.status !== "pending" && e.status !== "submitting") continue;
      if (e.kind === "approval") {
        if (notifiedApprovals.has(e.id)) continue;
        notifiedApprovals.add(e.id);
        notifyApproval(e.conversationId);
      } else if (e.kind === "stage_card") {
        if (notifiedStageCards.has(e.id)) continue;
        notifiedStageCards.add(e.id);
        notifyStageAdvance(e.conversationId);
      }
    }
    // Prune settled ids so the dedup sets track only live prompts (stay bounded).
    const liveApprovals = new Set(pendingApprovalIds());
    for (const seen of notifiedApprovals) {
      if (!liveApprovals.has(seen)) notifiedApprovals.delete(seen);
    }
    const liveStageCards = new Set(pendingStageCardIds());
    for (const seen of notifiedStageCards) {
      if (!liveStageCards.has(seen)) notifiedStageCards.delete(seen);
    }
  });

  const unsubPaused = usePausedTurnStore.subscribe((state) => {
    for (const p of state.pending) {
      if (notifiedPauses.has(p.checkpointId)) continue;
      notifiedPauses.add(p.checkpointId);
      if (p.kind === "team_preview") {
        notifyKickoff(p.conversationId);
      } else {
        // ask_user | plan_review
        notifyAwaitingDecision(p.conversationId);
      }
    }
    const live = new Set(pendingPauseIds());
    for (const seen of notifiedPauses) {
      if (!live.has(seen)) notifiedPauses.delete(seen);
    }
  });

  return () => {
    unsubConversation();
    unsubInteractions();
    unsubPaused();
  };
}

/** OS 通知点击 → 跳转到对应对话（与 toast action 同路由）。 */
export function startNativeNotificationRouting(): () => void {
  const api =
    typeof window !== "undefined" ? window.notificationApi : undefined;
  if (!api?.onClicked) return () => {};
  return api.onClicked(({ conversationId }) => {
    if (conversationId) jumpTo(conversationId);
  });
}
