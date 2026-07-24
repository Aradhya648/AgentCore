/**
 * Sidecar attach orchestration (本地引擎刷新恢复 D4).
 *
 * Subscribe → queue live → attach IPC → setActive → synthesize user row /
 * clear-then-fold (start) or incremental (resume) → replay → drain queue →
 * live tail. Does **not** reuse `rejoinLiveTurn` / `attachOnOpen` (those hang
 * the cloud SSE attach).
 */
import { logEvent } from "@/lib/log";
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

/**
 * Attach a live sidecar turn after refresh / reopen.
 *
 * @returns whether attach succeeded (false → recovery re-query already applied).
 */
export async function attachSidecarTurn(
  conversationId: string,
): Promise<boolean> {
  const store = useConversationStore.getState();
  // Same-session guard: original runSidecarTurn invoke still alive → skip.
  if (getRuntime(conversationId).isGenerating) return true;

  const liveQueue: SSEEvent[] = [];
  let draining = false;
  let finished = false;
  let activeTurnId: string | undefined;
  let activeRootId: string | undefined;
  let activeSubpath: string | undefined;
  let anchorUserMessageId: string | undefined;

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

  const unsubscribe = window.sidecarApi.onEvent((push: SidecarEventPush) => {
    if (push.conversationId !== conversationId) return;
    if (activeTurnId && push.turnId !== activeTurnId) return;
    if (draining) {
      foldEvent(push.event as SSEEvent);
      return;
    }
    liveQueue.push(push.event as SSEEvent);
  });

  const ac = new AbortController();
  store.setAbort(ac, conversationId);
  beginTurnPreflight(conversationId);

  const onAbort = (): void => {
    if (!activeRootId || !activeTurnId) return;
    void window.sidecarApi.cancel({
      rootId: activeRootId,
      subpath: activeSubpath,
      turnId: activeTurnId,
    });
    resolveDone();
  };
  ac.signal.addEventListener("abort", onAbort, { once: true });

  try {
    const res: SidecarAttachResponse = await window.sidecarApi.attach({
      conversationId,
    });
    if (!res.attached || !res.turnId || !res.rootId) {
      // Race: turn settled between recovery and attach — re-query, never hang.
      unsubscribe();
      store.setAbort(null, conversationId);
      ac.signal.removeEventListener("abort", onAbort);
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
    activeRootId = res.rootId;
    activeSubpath = res.subpath ?? "";
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
    for (const event of res.events ?? []) {
      foldEvent(event as SSEEvent);
    }
    while (liveQueue.length > 0) {
      const next = liveQueue.shift();
      if (next) foldEvent(next);
    }

    if (!finished && !ac.signal.aborted) {
      await done;
    }

    teardownAttachedTurn(
      conversationId,
      activeTurnId,
      anchorUserMessageId,
      unsubscribe,
      ac,
      onAbort,
    );
    return true;
  } catch (err) {
    teardownAttachedTurn(
      conversationId,
      activeTurnId,
      anchorUserMessageId,
      unsubscribe,
      ac,
      onAbort,
    );
    throw err;
  }
}

function teardownAttachedTurn(
  conversationId: string,
  turnId: string | undefined,
  userMessageId: string | undefined,
  unsubscribe: () => void,
  ac: AbortController,
  onAbort: () => void,
): void {
  clearActiveSidecarTurn(conversationId, turnId);
  unsubscribe();
  ac.signal.removeEventListener("abort", onAbort);
  const store = useConversationStore.getState();
  store.setAbort(null, conversationId);
  if (userMessageId) {
    store.setTurnSyncStatus(userMessageId, "synced_pending", conversationId);
  }
  if (getRuntime(conversationId).isGenerating && ac.signal.aborted) {
    store.setGenerating(false, conversationId);
  }
}
