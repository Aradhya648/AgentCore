import { api } from "@/services/api";

/**
 * Privacy gate for Worker conversation-log tools (`conversation_history_access`).
 *
 * Orthogonal to long-term `memory_enabled`. Off ⇒ Workers are not wired
 * `search_conversations` / `read_conversation`.
 *
 * Routes hang on the memory settings router (same `/users/me/memory` prefix):
 * GET/PUT `/v1/users/me/memory/conversation-history-access` with `{ enabled }`.
 */

export interface ConversationHistoryAccessDoc {
  /** Maps to `users.conversation_history_access` (default ON). */
  enabled: boolean;
}

/** Load whether AI may look up past conversation logs. */
export function getConversationHistoryAccess(): Promise<ConversationHistoryAccessDoc> {
  return api.get<ConversationHistoryAccessDoc>(
    "/v1/users/me/memory/conversation-history-access",
  );
}

/** Flip the conversation-history access gate (off = stop Worker log tools). */
export function setConversationHistoryAccess(
  enabled: boolean,
): Promise<ConversationHistoryAccessDoc> {
  return api.put<ConversationHistoryAccessDoc>(
    "/v1/users/me/memory/conversation-history-access",
    { enabled },
  );
}
