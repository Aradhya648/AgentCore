import { useActiveMessages, useConversationStore } from "@/stores/conversation";
import type { Execution } from "@/stores/execution";
import { type EndpointKind, useSidePanelStore } from "@/stores/sidePanel";
import { useCallback, useMemo } from "react";
import { INPUT_ID, isEndpointId } from "./constants";

export interface GraphDrillHandoff {
  interactive: boolean;
  messageId: string | null;
  onNodeSelect?: (runId: string) => void;
  onEndpointSelect?: (
    contentMessageId: string,
    title: string,
    endpoint: EndpointKind,
  ) => void;
  onClose?: () => void;
}

/** Drill-in / highlight contract for GraphView and its hosts. */
export function useGraphDrillIn(
  execution: Execution | null,
  {
    interactive,
    messageId,
    onNodeSelect,
    onEndpointSelect,
    onClose,
  }: GraphDrillHandoff,
) {
  const showRunDetail = useSidePanelStore((s) => s.showRunDetail);
  const messages = useActiveMessages();
  const focusMessage = useConversationStore((s) => s.focusMessage);

  const showRunDetailHere = useCallback(
    (runId: string) => {
      if (!messageId) return;
      const run = execution?.runs.find((r) => r.id === runId);
      const role = execution?.agents.find((a) => a.id === run?.agentId)?.role;
      showRunDetail(messageId, runId, role);
    },
    [execution, messageId, showRunDetail],
  );

  const litRunId = useSidePanelStore((s) => {
    if (!s.open) return null;
    const active = s.tabs.find((t) => t.id === s.activeTabId);
    return active?.kind === "run" && active.messageId === messageId
      ? active.runId
      : null;
  });

  const litEndpointMessageId = useSidePanelStore((s) => {
    if (!s.open) return null;
    const active = s.tabs.find((t) => t.id === s.activeTabId);
    return active?.kind === "content" && active.messageId === messageId
      ? active.contentMessageId
      : null;
  });

  const finalAnswer = useMemo(() => {
    if (!execution) return null;
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (m.role === "assistant" && m.executionId === execution.id) {
        return m.content ? { id: m.id, content: m.content } : null;
      }
    }
    return null;
  }, [messages, execution]);

  const taskMessage = useMemo(() => {
    if (!execution) return null;
    const answerIdx = messages.findIndex(
      (m) => m.role === "assistant" && m.executionId === execution.id,
    );
    if (answerIdx <= 0) return null;
    for (let i = answerIdx - 1; i >= 0; i--) {
      if (messages[i].role === "user") return { id: messages[i].id };
    }
    return null;
  }, [messages, execution]);

  const captainRun = useMemo(
    () => execution?.runs.find((r) => r.kind === "captain") ?? null,
    [execution],
  );

  const activateNode = useCallback(
    (id: string) => {
      if (id === INPUT_ID) {
        if (!taskMessage) return;
        if (onEndpointSelect) {
          onEndpointSelect(taskMessage.id, "提问", "prompt");
          return;
        }
        focusMessage(taskMessage.id);
        if (interactive) onClose?.();
        return;
      }
      if (captainRun && id === captainRun.id) {
        if (!finalAnswer) return;
        if (onEndpointSelect) {
          onEndpointSelect(finalAnswer.id, "最终回答", "answer");
          return;
        }
        focusMessage(finalAnswer.id);
        if (interactive) onClose?.();
        return;
      }
      if (isEndpointId(id)) return;
      if (onNodeSelect) {
        onNodeSelect(id);
        return;
      }
      showRunDetailHere(id);
      onClose?.();
    },
    [
      onNodeSelect,
      onEndpointSelect,
      showRunDetailHere,
      finalAnswer,
      taskMessage,
      captainRun,
      focusMessage,
      interactive,
      onClose,
    ],
  );

  return {
    activateNode,
    showRunDetailHere,
    litRunId,
    litEndpointMessageId,
    finalAnswer,
    taskMessage,
    captainRun,
  };
}
