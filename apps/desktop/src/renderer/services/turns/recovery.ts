import { describeStreamError, streamErrorAction } from "@/lib/errors";
import { loadLatestWindow } from "@/services/messages";
import { type ConversationRecovery, loadRecovery } from "@/services/resume";
import { attachConversation } from "@/services/streamConversation";
import { getRuntime, useConversationStore } from "@/stores/conversation";
import { beginTurnPreflight } from "@/stores/conversation/turnPhaseActions";
import { useExecutionStore } from "@/stores/execution";
import { clearInteractionPrompts } from "@/stores/interactionPrompts";
import {
  RECONNECT_BANNER,
  isAbort,
  isTransportDrop,
  lastUserMessageOf,
} from "./helpers";

/**
 * Clear-then-fold prep: drop every assistant after ``userMessageId`` from the
 * conversation slice **and** wipe their process/execution slots so a full journal
 * replay cannot double-fold tools / team graph (流式回复持久化 §3.6).
 */
function clearAfterUserForReplay(
  conversationId: string,
  userMessageId: string,
): void {
  const rt = getRuntime(conversationId);
  const idx = rt.messages.findIndex((m) => m.id === userMessageId);
  if (idx === -1) return;
  const exec = useExecutionStore.getState();
  for (const m of rt.messages.slice(idx + 1)) {
    if (m.role !== "assistant") continue;
    exec.clearExecution(m.id);
    if (m.serverMessageId && m.serverMessageId !== m.id) {
      exec.clearExecution(m.serverMessageId);
    }
  }
  const store = useConversationStore.getState();
  store.truncateAfter(userMessageId, conversationId);
  store.createAssistantMessage(conversationId);
}

/**
 * Rejoin a turn whose live stream dropped mid-flight (实时重连续看 C1 · slice 1b).
 *
 * Post-decoupling (slice 1a) a dropped connection no longer kills a turn — it
 * runs detached + persists — so a transport drop must RECONNECT, not resend (a
 * resend / regenerate would double-run a turn that is still alive). Resets the
 * partial assistant bubble (the replay re-sends the full transcript-so-far, so
 * keeping the partial would double it), then attaches: replay + live tail. On
 * `"none"` the run already finished — reload the persisted transcript (its reply
 * is saved). If reconnect itself drops, surface a banner whose retry reconnects
 * again (never resends).
 *
 * Returns `true` when handled (reattached / reloaded a saved reply / banner shown);
 * `false` only when there is no turn to rejoin and nothing was persisted, so the
 * caller can fall back to its resend / regenerate banner.
 */
export async function rejoinLiveTurn(conversationId: string): Promise<boolean> {
  const lastUser = lastUserMessageOf(conversationId);
  if (!lastUser) return false;

  const store = useConversationStore.getState();
  store.clearError(conversationId);
  // Drop any partial assistant bubble + process/execution so the full journal
  // replay rebuilds cleanly (clear-then-fold · §3.6).
  clearAfterUserForReplay(conversationId, lastUser.id);

  const ac = new AbortController();
  store.setAbort(ac, conversationId);
  beginTurnPreflight(conversationId);
  try {
    const outcome = await attachConversation(conversationId, ac.signal);
    if (outcome === "attached") return true;
    // No live run — the detached turn already finished + persisted. Reload it so
    // the placeholder is replaced by the saved reply.
    await loadLatestWindow(conversationId);
    useConversationStore.getState().setGenerating(false, conversationId);
    const last = getRuntime(conversationId).messages.at(-1);
    // A persisted assistant reply means the detached turn delivered — handled.
    // Still ending on the user message means it produced nothing → let the caller
    // offer a resend.
    return last?.role === "assistant";
  } catch (err) {
    if (isAbort(err)) return true; // user stopped — handled
    const s = useConversationStore.getState();
    if (getRuntime(conversationId).isGenerating) {
      s.finalizeLastMessage(conversationId);
    }
    clearInteractionPrompts(conversationId);
    // A reconnect drop → manual「重连」(never resend); an auth failure stays silent
    // (the api layer already redirected to login).
    const msg = isTransportDrop(err)
      ? RECONNECT_BANNER
      : describeStreamError(err);
    if (msg) {
      s.setError(
        msg,
        () => void rejoinLiveTurn(conversationId),
        conversationId,
        streamErrorAction(err),
      );
    }
    return true;
  } finally {
    useConversationStore.getState().setAbort(null, conversationId);
  }
}

/**
 * Mark a dead-lease ghost (``usage.status=running`` but recovery has no live run
 * and no pause) as interrupted so the bubble stops spinning. Empty body → layer 1
 * recoverability (send a new turn / composer hint); no message-level retry row.
 */
export function markGhostInterrupted(conversationId: string): void {
  const store = useConversationStore.getState();
  const last = getRuntime(conversationId).messages.at(-1);
  if (!last || last.role !== "assistant" || last.status !== "running") return;
  store.updateMessage(last.id, {
    isStreaming: false,
    status: "incomplete",
    finishReason: "interrupted",
    runs: last.runs ? { ...last.runs, finishReason: "interrupted" } : last.runs,
  });
  useConversationStore.getState().setGenerating(false, conversationId);
  const exec = useExecutionStore.getState();
  exec.clearExecution(last.id);
  if (last.serverMessageId && last.serverMessageId !== last.id) {
    exec.clearExecution(last.serverMessageId);
  }
}

/**
 * Cloud-path settle for a last assistant with ``status===running``.
 *
 * Open-time hydrate races ``loadRecovery`` against ``fetchMessageWindow``;
 * recovery often finishes first. A cold pause that lands in between leaves a
 * stale empty snapshot (``!cloudLive ∧ pausedCount===0``) while the message
 * window still shows ``running`` — marking ghost then would wipe the pause
 * latch. Re-fetch once when the snapshot looks empty (sidecarAttach
 * ``attached:false`` precedent), then decide on the fresh facts:
 *
 * - live ∧ paused=0 → rejoin
 * - paused≥1 → leave alone (``loadRecovery`` already hydrated pause store)
 * - still !live ∧ paused=0 → real dead-lease / TTL degrade → ghost
 */
export async function settleCloudRunningAssistant(
  conversationId: string,
  recovery: ConversationRecovery,
): Promise<"rejoin" | "ghost" | "hold"> {
  let snap = recovery;
  if (!snap.cloudLive && snap.pausedCount === 0) {
    snap = await loadRecovery(conversationId);
  }
  if (snap.cloudLive && snap.pausedCount === 0) {
    void rejoinLiveTurn(conversationId);
    return "rejoin";
  }
  if (!snap.cloudLive && snap.pausedCount === 0) {
    markGhostInterrupted(conversationId);
    return "ghost";
  }
  return "hold";
}

/**
 * On opening a conversation, rejoin a live run or mark a dead ghost interrupted
 * (P4 unified hydrate · 实时重连续看 C1 · slice 1b). Empty interrupted → layer 1
 * (send new turn); not a resume affordance.
 *
 * - Last message is user + liveRunning → bare attach (``message_start`` opens bubble).
 * - Last message is running assistant + liveRunning → clear-then-fold rejoin (overlay
 *   partial already painted; attach replaces it without double-fold).
 * - Last message is running assistant but no live / pause → ghost → interrupted.
 */
export async function attachOnOpen(conversationId: string): Promise<void> {
  const store = useConversationStore.getState();
  if (getRuntime(conversationId).isGenerating) return; // already streaming locally

  const ac = new AbortController();
  store.setAbort(ac, conversationId);
  beginTurnPreflight(conversationId);
  try {
    await attachConversation(conversationId, ac.signal);
  } catch (err) {
    if (isAbort(err)) return;
    const s = useConversationStore.getState();
    // Only surface a reconnect banner if a bubble actually opened (a run was live
    // and we lost it); a pre-event drop / 204 stays silent.
    if (getRuntime(conversationId).isGenerating) {
      s.finalizeLastMessage(conversationId);
      s.setError(
        RECONNECT_BANNER,
        () => void rejoinLiveTurn(conversationId),
        conversationId,
        null,
      );
    }
  } finally {
    useConversationStore.getState().setAbort(null, conversationId);
  }
}
