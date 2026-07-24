import { useBackgroundProcessStore } from "@/stores/backgroundProcesses";
import { useBackgroundTasksStore } from "@/stores/backgroundTasks";
import { useInteractionStore } from "@/stores/interactions";
import { usePausedTurnStore } from "@/stores/pausedTurns";
import { useToolOutputLiveStore } from "@/stores/toolOutputLive";
import { useTurnModelStore } from "@/stores/turnModel";
import { useUserTerminalStore } from "@/stores/userTerminals";

/**
 * Delete-conversation cleanup for in-memory per-conversation runtime buckets
 * (paused resumes, interactions, model badge, handoff tasks, processes /
 * terminals / live tool output). Pair with {@link clearConversationUiState}
 * for persisted UI prefs — both run from {@link useDeleteConversation} onSuccess.
 */
export function purgeConversationRuntimeState(conversationId: string): void {
  usePausedTurnStore.getState().clear(conversationId);
  useInteractionStore.getState().clear(conversationId);
  useTurnModelStore.getState().clearConversation(conversationId);
  useBackgroundTasksStore.getState().clearConversation(conversationId);
  useBackgroundProcessStore.getState().clearConversation(conversationId);
  useUserTerminalStore.getState().clearConversation(conversationId);
  useToolOutputLiveStore.getState().clearConversation(conversationId);
}
