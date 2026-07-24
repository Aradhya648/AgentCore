import { useInteractionStore } from "@/stores/interactions";

/**
 * Turn-boundary cleanup for interaction prompts.
 *
 * Sidecar / process death: hot-path cards flip to orphaned 灰态 (假卡可见) rather
 * than vanishing. Full wipe (logout / tests) still clears when no conversationId.
 */
export function clearInteractionPrompts(conversationId?: string): void {
  if (conversationId === undefined) {
    useInteractionStore.getState().clear();
    return;
  }
  useInteractionStore.getState().orphanConversation(conversationId, true);
}
