import { api } from "@/services/api";
import type { RunLlmWindowResponse } from "@agentcore/contract-rest-types/llm-window";

export type { RunLlmWindowResponse };

/** Fold one run's LLM input window from turn_journal (owner-scoped, diagnostic). */
export async function fetchRunLlmWindow(
  conversationId: string,
  messageId: string,
  runId: string,
): Promise<RunLlmWindowResponse> {
  return api.get<RunLlmWindowResponse>(
    `/v1/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/runs/${encodeURIComponent(runId)}/llm-window`,
  );
}
