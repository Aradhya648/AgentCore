import { api } from "@/services/api";
import type { components } from "@/types/api.generated";

export type AdminUser = components["schemas"]["AdminUserResponse"];
/** A roster row: the account record + its all-time cumulative spend (`cost_total`). */
export type AdminUserListItem = components["schemas"]["AdminUserListItem"];
export type AdminUserListResponse =
  components["schemas"]["AdminUserListResponse"];

export type UserRole = "user" | "admin";
export type UserStatus = "active" | "disabled";
export type UserSort = "created_at" | "cost";
export type SortOrder = "asc" | "desc";
export type AdminUpdateUserRequest =
  components["schemas"]["AdminUpdateUserRequest"];
export type AdminUserDetail = components["schemas"]["AdminUserDetail"];
export type AdminConversationLine =
  components["schemas"]["AdminConversationLine"];
export type RoleCostLine = components["schemas"]["RoleCostLine"];
export type ModelCostLine = components["schemas"]["ModelCostLine"];
export type AdminResetPasswordResponse =
  components["schemas"]["AdminResetPasswordResponse"];
export type AdminSetPasswordRequest =
  components["schemas"]["AdminSetPasswordRequest"];

export interface ListUsersParams {
  page: number;
  pageSize: number;
  q?: string;
  /** Pin the role / status dimension (omit = all). */
  role?: UserRole;
  status?: UserStatus;
  /** Sort key + direction (default: newest registration first). */
  sort?: UserSort;
  order?: SortOrder;
  /** Surface 注销 (soft-deleted, anonymized) accounts — hidden by default. */
  includeDeleted?: boolean;
}

export async function listUsers(
  params: ListUsersParams,
): Promise<AdminUserListResponse> {
  const search = new URLSearchParams({
    page: String(params.page),
    page_size: String(params.pageSize),
    sort: params.sort ?? "created_at",
    order: params.order ?? "desc",
  });
  const q = params.q?.trim();
  if (q) search.set("q", q);
  if (params.role) search.set("role", params.role);
  if (params.status) search.set("status", params.status);
  if (params.includeDeleted) search.set("include_deleted", "true");
  return api.get<AdminUserListResponse>(`/v1/admin/users?${search.toString()}`);
}

/**
 * Patch one account. Only the keys present in `patch` are applied (tri-state —
 * a quota key sent as `null` clears the override, a value sets it). Returns the
 * fresh record.
 */
export async function updateUser(
  userId: string,
  patch: AdminUpdateUserRequest,
): Promise<AdminUser> {
  return api.patch<AdminUser>(`/v1/admin/users/${userId}`, patch);
}

/**
 * 用户详情下钻: one account's record + its own usage (today/month/trend/by-role)
 * + recent conversations + recent turn activity (each drillable into 会话复盘).
 */
export async function fetchUserDetail(
  userId: string,
): Promise<AdminUserDetail> {
  return api.get<AdminUserDetail>(`/v1/admin/users/${userId}/detail`);
}

/**
 * Rotate an account's password to a fresh one-off string and kill every active
 * session (all refresh tokens revoked). The temp password is shown *once* in the
 * response — there is no way to retrieve it again — so the caller must surface it
 * to the operator immediately.
 */
export async function resetUserPassword(
  userId: string,
): Promise<AdminResetPasswordResponse> {
  return api.post<AdminResetPasswordResponse>(
    `/v1/admin/users/${userId}/reset-password`,
  );
}

/**
 * Set an account's password to an operator-chosen value and revoke every active
 * session. The plaintext is never returned — the caller already knows it.
 */
export async function setUserPassword(
  userId: string,
  body: AdminSetPasswordRequest,
): Promise<void> {
  await api.post(`/v1/admin/users/${userId}/set-password`, body);
}

/**
 * 注销 (soft-delete + anonymize) an account, admin-initiated. Anonymizes + disables
 * the account, revokes its sessions, and cascades cross-domain cleanup (conversations
 * / shares / BYOK / avatar). Returns the tombstone record (carries `deleted_at`).
 * Irreversible — the caller must confirm with the operator first.
 */
export async function deleteUser(userId: string): Promise<AdminUser> {
  return api.delete<AdminUser>(`/v1/admin/users/${userId}`);
}
