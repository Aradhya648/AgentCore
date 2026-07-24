import { isTurnRecoverable } from "@/lib/turnRecoverable";
import { acceptRunOutcome } from "@/services/runRedirect";
import { assistantProjectionId, getRuntime } from "@/stores/conversation";
import {
  execRuntime,
  projectRuntime,
  useExecutionStore,
} from "@/stores/execution";

/**
 * Implicit「忽略」when the user starts a new turn: audit `recovery_ignored` +
 * clear each recoverable execution projection. Replaces the explicit 忽略/放弃
 * button on the 救火行.
 */
export function dismissRecoverableExecutions(conversationId: string): void {
  const messages = getRuntime(conversationId).messages;
  const execStore = useExecutionStore.getState();

  for (const m of messages) {
    if (m.role !== "assistant") continue;
    const messageId = assistantProjectionId(m);
    const rt = execRuntime(execStore, messageId);
    const execution = projectRuntime(rt);
    if (!isTurnRecoverable(execution)) continue;

    void acceptRunOutcome(conversationId, {
      messageId,
      runId: messageId,
      reason: "recovery_ignored",
      note: "用户发起新回合，隐式忽略上次救火",
    }).catch(() => {
      /* local clear still proceeds */
    });
    execStore.clearExecution(messageId);
  }
}
