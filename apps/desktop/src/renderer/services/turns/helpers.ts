import { StreamError } from "@/lib/errors";
import {
  type Message,
  getActiveRuntime,
  getRuntime,
  useConversationStore,
} from "@/stores/conversation";
import { usePausedTurnStore } from "@/stores/pausedTurns";

/** The user's explicit stop (abort button) — never surfaced as an error. */
export function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

/**
 * Clear composer lock when a turn path dies while still marked generating.
 * Shared by runSend / regenerate / stage-card resolve — same catch/abort 收口.
 */
export function finalizeGeneratingIfNeeded(conversationId: string): void {
  if (getRuntime(conversationId).isGenerating) {
    useConversationStore.getState().finalizeLastMessage(conversationId);
  }
}

/**
 * Cold pending pause card ⇒ conversation must not look「仍在生成」.
 * Clears isGenerating + closes the tail assistant stream (stamp finishReason=paused
 * when the active slice can be patched). Call after painting/merging cold cards
 * (loadRecovery / surfaceResume) or on settle hold (paused≥1).
 *
 * @param force — settle hold already knows paused≥1 from recovery snap; clear even
 *   if pausedTurns is not hydrated yet (stale-empty race).
 */
export function finalizeGeneratingForPausedConversation(
  conversationId: string,
  options?: { force?: boolean },
): void {
  const hasPaused = usePausedTurnStore
    .getState()
    .pending.some((p) => p.conversationId === conversationId);
  if (!options?.force && !hasPaused) return;

  const store = useConversationStore.getState();
  const rt = getRuntime(conversationId);
  const last = rt.messages.at(-1);
  if (rt.isGenerating || last?.isStreaming) {
    store.finalizeLastMessage(conversationId);
  }

  // Stamp paused on the tail assistant (hydrate-equivalent close). updateMessage
  // is active-slice only — generating lock above is conversation-scoped either way.
  if (store.currentConversationId !== conversationId) return;
  const tail = getRuntime(conversationId).messages.at(-1);
  if (
    !tail ||
    tail.role !== "assistant" ||
    tail.finishReason === "paused" ||
    tail.finishReason === "interrupted"
  ) {
    return;
  }
  store.updateMessage(tail.id, {
    isStreaming: false,
    finishReason: "paused",
    runs: tail.runs ? { ...tail.runs, finishReason: "paused" } : tail.runs,
  });
}

/** A mid-stream transport drop (socket died), as opposed to a backend refusal
 * (quota / rate limit / missing key, which never started a run). Only a drop
 * warrants RECONNECT — since 执行与请求解耦 (C1 · slice 1a) the turn keeps running
 * detached, so the right recovery is to rejoin it (1b), not resend it. */
export function isTransportDrop(err: unknown): boolean {
  return err instanceof StreamError && err.kind === "network";
}

/** zh banner for a reconnect that could not be held — the run is still alive in
 * the background, so the action reconnects rather than resends. */
export const RECONNECT_BANNER =
  "连接中断，回合仍在后台继续。点击「重连」继续查看。";

/** The latest user message of a conversation's slice, or null. */
export function lastUserMessageOf(conversationId: string): Message | null {
  const msgs = getRuntime(conversationId).messages;
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === "user") return msgs[i];
  }
  return null;
}

/** The most recent user message in the open conversation, or null. Backs the
 * task card's retry / adjust-instruction / replan actions. */
export function lastUserMessage(): Message | null {
  const msgs = getActiveRuntime().messages;
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === "user") return msgs[i];
  }
  return null;
}

/** Id of {@link lastUserMessage}, or null. */
export function lastUserMessageId(): string | null {
  return lastUserMessage()?.id ?? null;
}
