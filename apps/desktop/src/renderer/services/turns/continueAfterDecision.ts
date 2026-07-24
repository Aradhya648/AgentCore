/**
 * One-click continue for interrupted_after_decision (D2 · 方案 A).
 * Binds to sidecar ``continueAfterDecision`` — never continueTurn / regenerate.
 */
import { describeStreamError, streamErrorAction } from "@/lib/errors";
import { clearSidecarHealth, probeSidecar } from "@/services/sidecarHealth";
import { resolveSidecarRoot } from "@/services/sidecarRouting";
import { continueAfterDecisionViaSidecar } from "@/services/streamConversationViaSidecar";
import { getRuntime, useConversationStore } from "@/stores/conversation";
import { beginTurnPreflight } from "@/stores/conversation/turnPhaseActions";
import { clearInteractionPrompts } from "@/stores/interactionPrompts";
import { useInterruptedAfterDecisionStore } from "@/stores/interruptedAfterDecision";
import { isAbort, isTransportDrop } from "./helpers";
import { rejoinLiveTurn } from "./recovery";

export async function runContinueAfterDecision(
  messageId: string,
): Promise<void> {
  const store = useConversationStore.getState();
  const conversationId = store.currentConversationId;
  if (!conversationId) {
    throw new Error("continueAfterDecision blocked: no active conversation");
  }
  if (getRuntime(conversationId).isGenerating) {
    store.setError(
      "当前回合仍在生成中，请稍后再继续",
      null,
      conversationId,
      null,
    );
    throw new Error("continueAfterDecision blocked: turn is still generating");
  }

  const entry = (
    useInterruptedAfterDecisionStore.getState().byConversation[
      conversationId
    ] ?? []
  ).find((i) => i.messageId === messageId);
  if (!entry) {
    throw new Error("continueAfterDecision blocked: no interrupted entry");
  }

  const sidecarTarget = await resolveSidecarRoot(conversationId);
  if (!sidecarTarget) {
    store.setError(
      "本地引擎暂不可用，无法从决策点继续，请稍后重试",
      () => {
        clearSidecarHealth();
        void runContinueAfterDecision(messageId);
      },
      conversationId,
      null,
    );
    return;
  }

  const probe = await probeSidecar(sidecarTarget);
  if (!probe.healthy) {
    store.setError(
      probe.detail
        ? `${probe.detail}，本地引擎暂不可用，无法从决策点继续`
        : "本地引擎暂不可用，无法从决策点继续，请稍后重试",
      () => {
        clearSidecarHealth();
        void runContinueAfterDecision(messageId);
      },
      conversationId,
      null,
    );
    return;
  }

  store.clearError(conversationId);
  useInterruptedAfterDecisionStore.getState().remove(conversationId, messageId);

  const resumed = store.resumePausedAssistant(messageId, conversationId);
  if (!resumed) {
    store.createAssistantMessage(conversationId);
    store.setServerMessageIdOnLastMessage(messageId, conversationId);
  }

  const ac = new AbortController();
  store.setAbort(ac, conversationId);
  beginTurnPreflight(conversationId);
  try {
    await continueAfterDecisionViaSidecar({
      conversationId,
      rootId: sidecarTarget.rootId,
      subpath: sidecarTarget.subpath,
      messageId,
      userMessageId: entry.userMessageId,
      signal: ac.signal,
    });
  } catch (err) {
    if (isAbort(err)) return;
    if (isTransportDrop(err) && (await rejoinLiveTurn(conversationId))) {
      return;
    }
    // Put the interrupted card back for retry.
    useInterruptedAfterDecisionStore
      .getState()
      .setForConversation(conversationId, [
        ...(useInterruptedAfterDecisionStore.getState().byConversation[
          conversationId
        ] ?? []),
        entry,
      ]);
    const s = useConversationStore.getState();
    if (getRuntime(conversationId).isGenerating) {
      s.finalizeLastMessage(conversationId);
    }
    clearInteractionPrompts(conversationId);
    const msg = describeStreamError(err);
    if (msg) {
      s.setError(
        msg,
        () => void runContinueAfterDecision(messageId),
        conversationId,
        streamErrorAction(err),
      );
    }
  } finally {
    useConversationStore.getState().setAbort(null, conversationId);
  }
}
