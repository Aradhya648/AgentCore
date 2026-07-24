import { BASE_URL, api } from "@/services/api";
import type { components } from "@/types/api.generated";

// REST DTOs generated from the backend OpenAPI spec (`pnpm gen:api`).
type Schemas = components["schemas"];

/** One public, read-only share link for a conversation (分享链接). `url` is a
 * relative path (`/shared/<id>`); use {@link shareLink} for the absolute URL. */
export type Share = Schemas["ShareSummary"];
type ShareListResponse = Schemas["ShareListResponse"];

export type CreateShareOptions = {
  /** 7 / 30 days, or null for never expires. Omit for server default (30d). */
  expires_in_days?: 7 | 30 | null;
};

/** The absolute, shareable URL for a link. The backend stays agnostic of its
 * public host and returns a relative `/shared/<id>`; the client prepends the API
 * origin (same pattern as `UserResponse.avatar_url`). */
export function shareLink(share: Share): string {
  return share.url.startsWith("/") ? `${BASE_URL}${share.url}` : share.url;
}

/** Create a new share link. Each call freezes an independent content-only snapshot
 * (问答正文) at this moment — later edits never change an existing link, and no
 * future turns are exposed (所见即所享). */
export async function createShare(
  conversationId: string,
  options?: CreateShareOptions,
): Promise<Share> {
  return api.post<Share>(`/v1/conversations/${conversationId}/shares`, options);
}

/** List the conversation's active (un-revoked) share links, newest first. */
export async function listShares(conversationId: string): Promise<Share[]> {
  const res = await api.get<ShareListResponse>(
    `/v1/conversations/${conversationId}/shares`,
  );
  return res.data;
}

/** Revoke a share link — its public page 404s immediately afterwards. */
export async function revokeShare(
  conversationId: string,
  shareId: string,
): Promise<void> {
  await api.delete(`/v1/conversations/${conversationId}/shares/${shareId}`);
}
