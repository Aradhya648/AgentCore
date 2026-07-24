import { api } from "@/services/api";
import type { components } from "@/types/api.generated";

type Schemas = components["schemas"];

/** Shared-space role (owner / editor / viewer). */
export type SharedSpaceRole = Schemas["SharedSpaceSummary"]["my_role"];
/** Membership lifecycle state. */
export type SharedSpaceMemberState = Schemas["SharedSpaceSummary"]["my_state"];
/** One accepted (or pending-as-invitee) space row. */
export type SharedSpaceSummary = Schemas["SharedSpaceSummary"];
/** Roster row. */
export type SharedSpaceMemberSummary = Schemas["SharedSpaceMemberSummary"];
/** Durable change-log row (attribution). */
export type SharedSpaceEventSummary = Schemas["SharedSpaceEventSummary"];
/** Mount of a space into a cloud conversation. */
export type SharedMountItem = Schemas["SharedMountItem"];

export type InviteRole = Schemas["InviteSharedSpaceMemberRequest"]["role"];

/** `ws_id = shared:<spaceId>` → space id. */
export function spaceIdOf(wsId: string): string | null {
  return wsId.startsWith("shared:") ? wsId.slice("shared:".length) : null;
}

/** Build the first-class workspace id for a shared space. */
export function sharedWsId(spaceId: string): string {
  return `shared:${spaceId}`;
}

/** True when the role may mutate files (owner / editor). */
export function canWriteSharedSpace(role: SharedSpaceRole): boolean {
  return role === "owner" || role === "editor";
}

/** Human label for a role chip. */
export function sharedSpaceRoleLabel(role: SharedSpaceRole): string {
  switch (role) {
    case "owner":
      return "所有者";
    case "editor":
      return "可编辑";
    case "viewer":
      return "只读";
  }
}

/** Human label for a mount mode chip. */
export function sharedMountModeLabel(mode: SharedMountItem["mode"]): string {
  return mode === "write" ? "可写" : "只读";
}

/** Short zh label for a change-log action (fallback = raw action). */
export function sharedSpaceEventActionLabel(action: string): string {
  const map: Record<string, string> = {
    space_created: "创建了空间",
    space_renamed: "重命名了空间",
    space_deleted: "删除了空间",
    member_invited: "邀请了成员",
    member_accepted: "接受了邀请",
    member_rejected: "拒绝了邀请",
    member_removed: "移除了成员",
    member_left: "退出了空间",
    member_role_changed: "变更了角色",
    file_written: "写入了文件",
    file_deleted: "删除了文件",
    file_moved: "移动了文件",
    dir_created: "创建了文件夹",
  };
  return map[action] ?? action;
}

export async function listSharedSpaces(): Promise<SharedSpaceSummary[]> {
  const res =
    await api.get<Schemas["SharedSpaceListResponse"]>("/v1/shared-spaces");
  return res.data;
}

/** Pending invites addressed to the current user (REST-discoverable on load). */
export async function listPendingSharedInvites(): Promise<
  SharedSpaceSummary[]
> {
  const res = await api.get<Schemas["SharedSpaceListResponse"]>(
    "/v1/shared-spaces/invites/pending",
  );
  return res.data;
}

export async function createSharedSpace(
  name: string,
): Promise<SharedSpaceSummary> {
  return api.post<SharedSpaceSummary>("/v1/shared-spaces", { name });
}

export async function getSharedSpace(
  spaceId: string,
): Promise<SharedSpaceSummary> {
  return api.get<SharedSpaceSummary>(`/v1/shared-spaces/${spaceId}`);
}

export async function renameSharedSpace(
  spaceId: string,
  name: string,
): Promise<SharedSpaceSummary> {
  return api.patch<SharedSpaceSummary>(`/v1/shared-spaces/${spaceId}`, {
    name,
  });
}

export async function deleteSharedSpace(spaceId: string): Promise<void> {
  await api.delete(`/v1/shared-spaces/${spaceId}`);
}

export async function listSharedSpaceMembers(
  spaceId: string,
): Promise<SharedSpaceMemberSummary[]> {
  const res = await api.get<Schemas["SharedSpaceMemberListResponse"]>(
    `/v1/shared-spaces/${spaceId}/members`,
  );
  return res.data;
}

export async function inviteSharedSpaceMember(
  spaceId: string,
  userId: string,
  role: InviteRole = "editor",
): Promise<SharedSpaceMemberSummary> {
  return api.post<SharedSpaceMemberSummary>(
    `/v1/shared-spaces/${spaceId}/invites`,
    { user_id: userId, role },
  );
}

export async function acceptSharedSpaceInvite(
  spaceId: string,
): Promise<SharedSpaceSummary> {
  return api.post<SharedSpaceSummary>(
    `/v1/shared-spaces/${spaceId}/invites/accept`,
    {},
  );
}

export async function rejectSharedSpaceInvite(spaceId: string): Promise<void> {
  await api.post(`/v1/shared-spaces/${spaceId}/invites/reject`, {});
}

export async function changeSharedSpaceMemberRole(
  spaceId: string,
  memberUserId: string,
  role: InviteRole,
): Promise<SharedSpaceMemberSummary> {
  return api.patch<SharedSpaceMemberSummary>(
    `/v1/shared-spaces/${spaceId}/members/${memberUserId}`,
    { role },
  );
}

/** Remove a member, or leave when `memberUserId` is self. */
export async function removeOrLeaveSharedSpaceMember(
  spaceId: string,
  memberUserId: string,
): Promise<void> {
  await api.delete(`/v1/shared-spaces/${spaceId}/members/${memberUserId}`);
}

export async function listSharedSpaceEvents(
  spaceId: string,
  opts?: { limit?: number; beforeId?: string | null },
): Promise<{ events: SharedSpaceEventSummary[]; total: number }> {
  const params = new URLSearchParams();
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  if (opts?.beforeId) params.set("before_id", opts.beforeId);
  const q = params.toString();
  const res = await api.get<Schemas["SharedSpaceEventListResponse"]>(
    `/v1/shared-spaces/${spaceId}/events${q ? `?${q}` : ""}`,
  );
  return { events: res.data, total: res.total };
}

export async function listSharedMounts(
  conversationId: string,
): Promise<SharedMountItem[]> {
  const res = await api.get<Schemas["SharedMountListResponse"]>(
    `/v1/conversations/${conversationId}/workspace/shared-mounts`,
  );
  return res.data;
}

export async function mountSharedSpace(
  conversationId: string,
  spaceId: string,
  aliasHint?: string | null,
): Promise<SharedMountItem> {
  const res = await api.post<Schemas["SharedMountResponse"]>(
    `/v1/conversations/${conversationId}/workspace/shared-mounts`,
    {
      space_id: spaceId,
      alias_hint: aliasHint ?? null,
    } satisfies Schemas["MountSharedSpaceRequest"],
  );
  return res.mount;
}

export async function unmountSharedSpace(
  conversationId: string,
  opts: { spaceId?: string; alias?: string },
): Promise<void> {
  const params = new URLSearchParams();
  if (opts.spaceId) params.set("space_id", opts.spaceId);
  if (opts.alias) params.set("alias", opts.alias);
  const q = params.toString();
  await api.delete(
    `/v1/conversations/${conversationId}/workspace/shared-mounts${
      q ? `?${q}` : ""
    }`,
  );
}
