import { api } from "@/services/api";
import type { components } from "@/types/api.generated";

export type AdminConversationListItem =
  components["schemas"]["AdminConversationListItem"];
export type AdminConversationListResponse =
  components["schemas"]["AdminConversationListResponse"];
export type AdminTurnListItem = components["schemas"]["AdminTurnListItem"];
export type AdminTurnListResponse =
  components["schemas"]["AdminTurnListResponse"];

export type ConversationSort = "updated_at" | "created_at" | "cost";
export type SortOrder = "asc" | "desc";
export type TurnStatus = "ok" | "error";

export interface ListConversationsParams {
  page: number;
  pageSize: number;
  q?: string;
  userId?: string;
  hasErrors?: boolean;
  includeDeleted?: boolean;
  since?: string;
  until?: string;
  sort?: ConversationSort;
  order?: SortOrder;
}

export async function listConversations(
  params: ListConversationsParams,
): Promise<AdminConversationListResponse> {
  const search = new URLSearchParams({
    page: String(params.page),
    page_size: String(params.pageSize),
    sort: params.sort ?? "updated_at",
    order: params.order ?? "desc",
  });
  const q = params.q?.trim();
  if (q) search.set("q", q);
  if (params.userId) search.set("user_id", params.userId);
  if (params.hasErrors === true) search.set("has_errors", "true");
  if (params.hasErrors === false) search.set("has_errors", "false");
  if (params.includeDeleted === false) search.set("include_deleted", "false");
  if (params.since) search.set("since", params.since);
  if (params.until) search.set("until", params.until);
  return api.get<AdminConversationListResponse>(
    `/v1/admin/conversations?${search.toString()}`,
  );
}

export interface ListTurnsParams {
  page: number;
  pageSize: number;
  userId?: string;
  conversationId?: string;
  status?: TurnStatus;
  since?: string;
  until?: string;
  includeDeletedConversations?: boolean;
}

export async function listTurns(
  params: ListTurnsParams,
): Promise<AdminTurnListResponse> {
  const search = new URLSearchParams({
    page: String(params.page),
    page_size: String(params.pageSize),
  });
  if (params.userId) search.set("user_id", params.userId);
  if (params.conversationId) search.set("conversation_id", params.conversationId);
  if (params.status) search.set("status", params.status);
  if (params.since) search.set("since", params.since);
  if (params.until) search.set("until", params.until);
  if (params.includeDeletedConversations === false) {
    search.set("include_deleted_conversations", "false");
  }
  return api.get<AdminTurnListResponse>(
    `/v1/admin/conversations/turns?${search.toString()}`,
  );
}
