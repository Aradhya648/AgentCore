import { api } from "@/services/api";
import type { components } from "@/types/api.generated";

export type Invite = components["schemas"]["InviteResponse"];
export type InviteListResponse = components["schemas"]["InviteListResponse"];
export type InviteStats = components["schemas"]["InviteStatsResponse"];
export type InviteStatus = Invite["status"];
export type BatchCreateInviteRequest = components["schemas"]["BatchCreateInviteRequest"];

export type ListInvitesParams = {
  page?: number;
  pageSize?: number;
  status?: InviteStatus;
  search?: string;
};

/**
 * The full invite roster. Lives under `/v1/auth/invites` (cohesive with register)
 * but is admin-gated — the same authorization boundary as `/v1/admin/*`.
 */
export async function listInvites(
  params: ListInvitesParams = {},
): Promise<InviteListResponse> {
  const search = new URLSearchParams();
  if (params.page) search.set("page", String(params.page));
  if (params.pageSize) search.set("page_size", String(params.pageSize));
  if (params.status) search.set("status", params.status);
  if (params.search?.trim()) search.set("search", params.search.trim());
  const qs = search.toString();
  return api.get<InviteListResponse>(`/v1/auth/invites${qs ? `?${qs}` : ""}`);
}

/** Per-status invite counts for the admin overview cards. */
export async function getInviteStats(): Promise<InviteStats> {
  return api.get<InviteStats>("/v1/auth/invites/stats");
}

/**
 * Mint a new invite code. `expiresInDays` omitted (or ≤ 0) → a code that never
 * expires (the backend default); a positive number sets the TTL in days.
 */
export async function createInvite(expiresInDays?: number): Promise<Invite> {
  const body =
    expiresInDays && expiresInDays > 0
      ? { expires_in_days: expiresInDays }
      : undefined;
  return api.post<Invite>("/v1/auth/invites", body);
}

/**
 * Mint multiple invite codes in one request. `count` is capped at 100 server-side.
 */
export async function createInvitesBatch(
  count: number,
  expiresInDays?: number,
): Promise<InviteListResponse> {
  const body: BatchCreateInviteRequest = { count };
  if (expiresInDays && expiresInDays > 0) {
    body.expires_in_days = expiresInDays;
  }
  return api.post<InviteListResponse>("/v1/auth/invites/batch", body);
}

/**
 * Burn an *unused* code so it can no longer be registered against. Idempotent it
 * is not — the backend rejects an already-used or already-revoked code (422).
 * Returns the fresh record (now `status: "revoked"`).
 */
export async function revokeInvite(inviteId: string): Promise<Invite> {
  return api.post<Invite>(`/v1/auth/invites/${inviteId}/revoke`);
}
