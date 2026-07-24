import type { ErrorAction } from "@/lib/errors";
import { activeRuntime, runtimeOf } from "./runtime";
import { useConversationStore } from "./store";
import type { ConversationRuntime, MemoryUpdate, Message } from "./types";

export const useActiveMessages = (): Message[] =>
  useConversationStore((s) => activeRuntime(s).messages);

/**
 * The `content` of one message in the active conversation by id (or "" when absent /
 * id is null). A narrow slice — subscribing to just this string means a consumer (the
 * SidePanel content tab) re-renders only when THAT message's text changes, not on every
 * streaming tick that mints a new `messages` array (白屏卡死修复·Stage 3 收窄订阅).
 */
export const useActiveMessageContent = (messageId: string | null): string =>
  useConversationStore((s) =>
    messageId
      ? (activeRuntime(s).messages.find((m) => m.id === messageId)?.content ??
        "")
      : "",
  );

export const useActiveMemoryUpdates = (): MemoryUpdate[] =>
  useConversationStore((s) => activeRuntime(s).memoryUpdates);

export const useActiveGenerating = (): boolean =>
  useConversationStore((s) => activeRuntime(s).isGenerating);

export const useActiveTurnPhase = () =>
  useConversationStore((s) => activeRuntime(s).turnPhase);

export const useConversationGenerating = (conversationId: string): boolean =>
  useConversationStore((s) => runtimeOf(s, conversationId).isGenerating);

export const useActiveError = (): string | null =>
  useConversationStore((s) => activeRuntime(s).error);

export const useActiveRetry = (): (() => void) | null =>
  useConversationStore((s) => activeRuntime(s).retry);

export const useActiveErrorAction = (): ErrorAction | null =>
  useConversationStore((s) => activeRuntime(s).errorAction);

export const useActiveMessageFocus = (): { id: string; nonce: number } | null =>
  useConversationStore((s) => activeRuntime(s).messageFocus);

export const useActiveHasMoreBefore = (): boolean =>
  useConversationStore((s) => activeRuntime(s).hasMoreBefore);

export const useActiveHasMoreAfter = (): boolean =>
  useConversationStore((s) => activeRuntime(s).hasMoreAfter);

export const useActiveLoadingOlder = (): boolean =>
  useConversationStore((s) => activeRuntime(s).loadingOlder);

export const useActiveLoadingNewer = (): boolean =>
  useConversationStore((s) => activeRuntime(s).loadingNewer);

export const getActiveRuntime = (): ConversationRuntime =>
  activeRuntime(useConversationStore.getState());

export const getRuntime = (
  conversationId?: string | null,
): ConversationRuntime =>
  runtimeOf(useConversationStore.getState(), conversationId);
