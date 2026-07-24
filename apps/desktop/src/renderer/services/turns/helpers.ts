import { StreamError } from "@/lib/errors";
import {
  type Message,
  getActiveRuntime,
  getRuntime,
  useConversationStore,
} from "@/stores/conversation";

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
