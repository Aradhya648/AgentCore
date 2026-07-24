import { getRuntime } from "./selectors";
import { useConversationStore } from "./store";
import {
  type TurnPhase,
  type TurnTerminalOutcome,
  armStopConfirmTimeout,
  blocksStreamOpen,
  clearStopConfirmTimeout,
  isTerminalPhase,
} from "./turnPhase";

export function getTurnPhase(conversationId: string): TurnPhase {
  return getRuntime(conversationId).turnPhase;
}

export function beginTurnPreflight(conversationId: string): void {
  clearStopConfirmTimeout(conversationId);
  useConversationStore.getState().setTurnPhase("preflight", conversationId);
}

export function enterTurnStreaming(conversationId: string): void {
  if (blocksStreamOpen(getTurnPhase(conversationId))) return;
  useConversationStore.getState().setTurnPhase("streaming", conversationId);
}

/**
 * Enter the honest「停止中」transition. Does not forge a terminal phase on
 * timeout — caller supplies `onUnconfirmed` (banner / toast + retry).
 */
export function beginTurnStopping(
  conversationId: string,
  onUnconfirmed?: () => void,
): void {
  const phase = getTurnPhase(conversationId);
  if (phase === "stopping" || isTerminalPhase(phase)) return;
  useConversationStore.getState().setTurnPhase("stopping", conversationId);
  armStopConfirmTimeout(conversationId, () => {
    if (getTurnPhase(conversationId) === "stopping") {
      onUnconfirmed?.();
    }
  });
}

export function completeTurnPhase(
  conversationId: string,
  outcome: TurnTerminalOutcome,
): void {
  clearStopConfirmTimeout(conversationId);
  useConversationStore.getState().setTurnPhase(outcome, conversationId);
}

/** 开流门禁：已 abort 或 phase 为 stopping/terminal → 抛 AbortError，不启动。 */
export function throwIfCannotOpenStream(
  conversationId: string,
  signal?: AbortSignal,
): void {
  if (signal?.aborted || blocksStreamOpen(getTurnPhase(conversationId))) {
    throw new DOMException("Aborted", "AbortError");
  }
}
