/**
 * Sidecar attach orchestration (本地引擎刷新恢复 D4).
 *
 * Subscribe → queue live → attach IPC → setActive → synthesize user row /
 * clear-then-fold (start) or incremental (resume) → replay → drain queue →
 * live tail. Does **not** reuse `rejoinLiveTurn` / `attachOnOpen` (those hang
 * the cloud SSE attach).
 *
 * Event ownership: claim via `sidecarEventPump` (App-lifetime single
 * `sidecar:event` subscription). Concurrent attach coalesces; a later claim
 * revokes the prior owner. Do not call `sidecarApi.onEvent` here.
 *
 * Viewer vs engine (C1)：AbortSignal / 切会话 / hydrate cleanup 只卸观察（release
 * claim），**禁止** ``sidecarApi.cancel``——停引擎只走 ``stopConversation``。
 */
import { logEvent } from "@/lib/log";
import {
  type SidecarTurnClaim,
  claimSidecarTurnSink,
} from "@/services/sidecarEventPump";
import {
  clearActiveSidecarTurn,
  setActiveSidecarTurn,
} from "@/services/sidecarRouting";
import { dispatchSSEEvent } from "@/services/streamConversation";
import { getRuntime, useConversationStore } from "@/stores/conversation";
import { beginTurnPreflight } from "@/stores/conversation/turnPhaseActions";
import { useExecutionStore } from "@/stores/execution";
import type { SSEEvent } from "@/types/events";
import type {
  SidecarAttachResponse,
  SidecarEventPush,
} from "@shared/sidecar-contract";
import { loadRecovery } from "../resume";
import { projectUnsyncedTurns } from "./projectUnsynced";
import { markGhostInterrupted } from "./recovery";

/** In-flight attach per conversation — hydrate 两次 coalesce 到同一 Promise。 */
const attachInFlight = new Map<string, Promise<boolean>>();

function isTerminalEvent(type: string): boolean {
  return type === "message_end" || type === "error";
}

/**
 * Clear assistants after ``userMessageId`` and open a fresh streaming placeholder
 * (sidecar-specific; anchor is the attach response id, never `lastUserMessageOf`).
 */
function clearAfterUserForSidecarReplay(
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

function ensureUserRow(
  conversationId: string,
  userMessageId: string,
  userMessage: string,
  traceId?: string,
): void {
  const rt = getRuntime(conversationId);
  if (rt.messages.some((m) => m.id === userMessageId)) return;
  useConversationStore.getState().addMessage(
    {
      id: userMessageId,
      role: "user",
      content: userMessage,
      createdAt: new Date().toISOString(),
      executionId: null,
      isStreaming: false,
      ...(traceId ? { traceId } : {}),
    },
    conversationId,
  );
}

export interface AttachSidecarTurnOptions {
  /** 切会话 / hydrate 取消时 abort（只停 live 等待并释放 claim，不 cancel 引擎）。 */
  signal?: AbortSignal;
}

/** Yield to the event loop every N folded snapshot events (大缓冲回放防假死). */
const ATTACH_REPLAY_YIELD_EVERY = 64;

/**
 * Attach a live sidecar turn after refresh / reopen.
 *
 * @returns whether attach succeeded (false → recovery re-query already applied).
 */
export async function attachSidecarTurn(
  conversationId: string,
  opts?: AttachSidecarTurnOptions,
): Promise<boolean> {
  const existing = attachInFlight.get(conversationId);
  if (existing) return existing;

  // Same-session guard: original runSidecarTurn invoke still alive → skip.
  if (getRuntime(conversationId).isGenerating) return true;

  const p = attachSidecarTurnExclusive(conversationId, opts).finally(() => {
    if (attachInFlight.get(conversationId) === p) {
      attachInFlight.delete(conversationId);
    }
  });
  attachInFlight.set(conversationId, p);
  return p;
}

/** 测试隔离：清空 in-flight latch。 */
export function resetSidecarAttachInFlightForTests(): void {
  attachInFlight.clear();
}

async function attachSidecarTurnExclusive(
  conversationId: string,
  opts?: AttachSidecarTurnOptions,
): Promise<boolean> {
  const store = useConversationStore.getState();

  const liveQueue: SSEEvent[] = [];
  let draining = false;
  let finished = false;
  let activeTurnId: string | undefined;
  let anchorUserMessageId: string | undefined;
  let claim: SidecarTurnClaim | null = null;

  let resolveDone!: () => void;
  const done = new Promise<void>((resolve) => {
    resolveDone = resolve;
  });

  const foldEvent = (event: SSEEvent): void => {
    dispatchSSEEvent(event, { conversationId, source: "sidecar" });
    if (isTerminalEvent(event.type)) {
      finished = true;
      resolveDone();
    }
  };

  const onLivePush = (push: SidecarEventPush): void => {
    if (draining) {
      foldEvent(push.event as SSEEvent);
      return;
    }
    liveQueue.push(push.event as SSEEvent);
  };

  // Claim before any await — concurrent attach coalesces above; a later exclusive
  // claim (after prior settled) revokes this owner via onRevoked.
  claim = claimSidecarTurnSink(conversationId, null, onLivePush, {
    onRevoked: () => {
      finished = true;
      resolveDone();
    },
  });

  const ac = new AbortController();
  store.setAbort(ac, conversationId);
  beginTurnPreflight(conversationId);

  // Viewer detach only — never cancel the in-flight sidecar turn (断连 ≠ 取消).
  const onAbort = (): void => {
    logEvent("info", "sidecar.attach_detach", {
      conversation_id: conversationId,
      turn_id: activeTurnId ?? null,
      reason: "viewer_abort",
    });
    resolveDone();
  };
  ac.signal.addEventListener("abort", onAbort, { once: true });

  const onExternalAbort = (): void => {
    ac.abort();
  };
  if (opts?.signal) {
    if (opts.signal.aborted) {
      ac.abort();
    } else {
      opts.signal.addEventListener("abort", onExternalAbort, { once: true });
    }
  }

  try {
    if (ac.signal.aborted) {
      teardownAttachedTurn(
        conversationId,
        activeTurnId,
        anchorUserMessageId,
        claim,
        ac,
        onAbort,
        opts?.signal,
        onExternalAbort,
      );
      return false;
    }

    const res: SidecarAttachResponse = await window.sidecarApi.attach({
      conversationId,
    });
    if (!claim.isOwner()) {
      teardownAttachedTurn(
        conversationId,
        activeTurnId,
        anchorUserMessageId,
        claim,
        ac,
        onAbort,
        opts?.signal,
        onExternalAbort,
      );
      return false;
    }
    if (!res.attached || !res.turnId || !res.rootId) {
      // Race: turn settled between recovery and attach — re-query, never hang.
      teardownAttachedTurn(
        conversationId,
        activeTurnId,
        anchorUserMessageId,
        claim,
        ac,
        onAbort,
        opts?.signal,
        onExternalAbort,
      );
      logEvent("info", "sidecar.attach", {
        conversation_id: conversationId,
        attached: false,
        event_count: 0,
      });
      const again = await loadRecovery(conversationId);
      projectUnsyncedTurns(conversationId, again.unsynced);
      if (!again.sidecarLive && again.pausedCount === 0) {
        markGhostInterrupted(conversationId);
      }
      return false;
    }

    logEvent("info", "sidecar.attach", {
      conversation_id: conversationId,
      attached: true,
      turn_id: res.turnId,
      event_count: res.events?.length ?? 0,
    });

    activeTurnId = res.turnId;
    claim.setTurnId(res.turnId);
    // D4 step 3: setActive BEFORE any event fold (interaction respond routing).
    setActiveSidecarTurn(
      conversationId,
      res.rootId,
      res.subpath ?? "",
      res.turnId,
    );
    store.setGenerating(true, conversationId);

    if (res.kind === "resume" && res.messageId) {
      // Resume does not re-emit pre-pause facts — keep cloud-window rows, fold
      // incremental buffer only (D4 resume 核实结论).
      const rt = getRuntime(conversationId);
      const assistant = rt.messages.find(
        (m) =>
          m.role === "assistant" &&
          (m.id === res.messageId || m.serverMessageId === res.messageId),
      );
      if (assistant) {
        store.updateMessage(assistant.id, {
          isStreaming: true,
          status: "running",
          ...(res.messageId !== assistant.id
            ? { serverMessageId: res.messageId }
            : {}),
        });
      } else {
        store.createAssistantMessage(conversationId);
        const last = getRuntime(conversationId).messages.at(-1);
        if (last && res.messageId) {
          store.updateMessage(last.id, { serverMessageId: res.messageId });
        }
      }
      anchorUserMessageId = res.userMessageId;
    } else {
      const userMessageId = res.userMessageId;
      if (!userMessageId) {
        throw new Error("sidecar attach missing userMessageId");
      }
      ensureUserRow(
        conversationId,
        userMessageId,
        res.userMessage ?? "",
        res.traceId,
      );
      clearAfterUserForSidecarReplay(conversationId, userMessageId);
      anchorUserMessageId = userMessageId;
    }

    draining = true;
    const snapshot = res.events ?? [];
    for (let i = 0; i < snapshot.length; i++) {
      if (ac.signal.aborted) break;
      foldEvent(snapshot[i] as SSEEvent);
      if (i > 0 && i % ATTACH_REPLAY_YIELD_EVERY === 0) {
        await new Promise<void>((r) => setTimeout(r, 0));
      }
    }
    while (!ac.signal.aborted && liveQueue.length > 0) {
      const next = liveQueue.shift();
      if (next) foldEvent(next);
    }

    if (!finished && !ac.signal.aborted && claim.isOwner()) {
      await done;
    }

    teardownAttachedTurn(
      conversationId,
      activeTurnId,
      anchorUserMessageId,
      claim,
      ac,
      onAbort,
      opts?.signal,
      onExternalAbort,
    );
    return true;
  } catch (err) {
    teardownAttachedTurn(
      conversationId,
      activeTurnId,
      anchorUserMessageId,
      claim,
      ac,
      onAbort,
      opts?.signal,
      onExternalAbort,
    );
    throw err;
  }
}

function teardownAttachedTurn(
  conversationId: string,
  turnId: string | undefined,
  userMessageId: string | undefined,
  claim: SidecarTurnClaim | null,
  ac: AbortController,
  onAbort: () => void,
  externalSignal: AbortSignal | undefined,
  onExternalAbort: () => void,
): void {
  clearActiveSidecarTurn(conversationId, turnId);
  claim?.release();
  ac.signal.removeEventListener("abort", onAbort);
  externalSignal?.removeEventListener("abort", onExternalAbort);
  const store = useConversationStore.getState();
  store.setAbort(null, conversationId);
  // Viewer abort: clear generating so reopen hydrate can attach again (engine may
  // still be live — recovery.sidecarLive drives the next attach). Natural end
  // already folded message_end; only mark outbox when we were not yanked away.
  if (ac.signal.aborted) {
    if (getRuntime(conversationId).isGenerating) {
      store.setGenerating(false, conversationId);
    }
    return;
  }
  if (userMessageId) {
    store.setTurnSyncStatus(userMessageId, "synced_pending", conversationId);
  }
}
