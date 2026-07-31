/**
 * Open-time attach/settle after message-window fetch (P4 unified hydrate).
 *
 * Decoupled from message-window adopt: warm reopen keeps the in-memory slice
 * (adopt skips overwrite) but still runs recovery-driven attach/settle so a
 * detached live / ghost running assistant is not left as fake "Replying".
 */
import { logEvent } from "@/lib/log";
import {
  type ConversationRecovery,
  shouldHydrateLocalRecovery,
} from "@/services/resume";
import { getRuntime } from "@/stores/conversation";
import { projectUnsyncedTurns } from "./projectUnsynced";
import { attachOnOpen, settleCloudRunningAssistant } from "./recovery";
import { attachSidecarTurn } from "./sidecarAttach";

export interface HydrateAttachSettleOptions {
  /** 切会话 / hydrate 取消时 abort（停 sidecar live 等待，释放 claim）。 */
  signal?: AbortSignal;
}

/**
 * Branch on recovery facts and rejoin / settle / project unsynced.
 *
 * Cloud path reads the **runtime** tail message (not the fetched window): after
 * a successful cold adopt they match; on warm reopen memory may already be newer.
 */
export async function runHydrateAttachSettle(
  conversationId: string,
  recovery: ConversationRecovery,
  opts?: HydrateAttachSettleOptions,
): Promise<"local" | "cloud"> {
  const useLocal = shouldHydrateLocalRecovery(recovery);
  logEvent("info", "conversation.hydrate", {
    conversation_id: conversationId,
    sidecar_live: recovery.sidecarLive,
    cloud_live: recovery.cloudLive,
    unsynced_count: recovery.unsynced.length,
    paused_count: recovery.pausedCount,
    branch: useLocal ? "local" : "cloud",
  });
  // Live pump already claimed (session abort set) — attach* is idempotent via
  // isGenerating; settle must not rejoin over it either. Cold hydrate sets
  // isGenerating from isStreaming overlay but leaves abort null until attach.
  if (getRuntime(conversationId).abort) {
    return useLocal ? "local" : "cloud";
  }
  if (useLocal) {
    projectUnsyncedTurns(conversationId, recovery.unsynced);
    if (recovery.sidecarLive && recovery.pausedCount === 0) {
      await attachSidecarTurn(conversationId, { signal: opts?.signal });
    }
    return "local";
  }
  const last = getRuntime(conversationId).messages.at(-1);
  if (last) {
    const canAttach = recovery.cloudLive && recovery.pausedCount === 0;
    if (last.role === "user" && canAttach) {
      void attachOnOpen(conversationId);
    } else if (last.role === "assistant" && last.status === "running") {
      await settleCloudRunningAssistant(conversationId, recovery);
    }
  }
  return "cloud";
}
