import { getRuntime } from "./selectors";
import { useConversationStore } from "./store";
import {
  type TurnPhase,
  type TurnTerminalOutcome,
  blocksStreamOpen,
} from "./turnPhase";

export function getTurnPhase(conversationId: string): TurnPhase {
  return getRuntime(conversationId).turnPhase;
}

export function beginTurnPreflight(conversationId: string): void {
  useConversationStore.getState().setTurnPhase("preflight", conversationId);
}

export function enterTurnStreaming(conversationId: string): void {
  if (blocksStreamOpen(getTurnPhase(conversationId))) return;
  useConversationStore.getState().setTurnPhase("streaming", conversationId);
}

export function completeTurnPhase(
  conversationId: string,
  outcome: TurnTerminalOutcome,
): void {
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
