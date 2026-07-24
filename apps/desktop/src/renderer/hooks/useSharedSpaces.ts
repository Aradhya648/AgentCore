import { queryClient } from "@/lib/queryClient";
import { sharedSpaceKeys, workspaceKeys } from "@/lib/queryKeys";
import {
  type InviteRole,
  type SharedSpaceSummary,
  acceptSharedSpaceInvite,
  changeSharedSpaceMemberRole,
  createSharedSpace,
  deleteSharedSpace,
  inviteSharedSpaceMember,
  listPendingSharedInvites,
  listSharedMounts,
  listSharedSpaceEvents,
  listSharedSpaceMembers,
  listSharedSpaces,
  mountSharedSpace,
  rejectSharedSpaceInvite,
  removeOrLeaveSharedSpaceMember,
  renameSharedSpace,
  unmountSharedSpace,
} from "@/services/sharedSpaces";
import { useMutation, useQuery } from "@tanstack/react-query";

/** Accepted shared spaces for the files-page「共享空间」分区. */
export function useSharedSpaces() {
  return useQuery({
    queryKey: sharedSpaceKeys.list,
    queryFn: listSharedSpaces,
    staleTime: 30_000,
  });
}

/**
 * Pending invites for the current user — fetched at app load (AppShell) so they
 * are REST-discoverable without relying on the firehose.
 */
export function usePendingSharedInvites(enabled = true) {
  return useQuery({
    queryKey: sharedSpaceKeys.pendingInvites,
    queryFn: listPendingSharedInvites,
    staleTime: 30_000,
    enabled,
  });
}

export function useSharedSpaceMembers(spaceId: string | null) {
  return useQuery({
    queryKey: sharedSpaceKeys.members(spaceId ?? ""),
    queryFn: () => {
      if (!spaceId) return Promise.resolve([]);
      return listSharedSpaceMembers(spaceId);
    },
    enabled: !!spaceId,
    staleTime: 15_000,
  });
}

export function useSharedSpaceEvents(spaceId: string | null) {
  return useQuery({
    queryKey: sharedSpaceKeys.events(spaceId ?? ""),
    queryFn: () => {
      if (!spaceId) return Promise.resolve({ events: [], total: 0 });
      return listSharedSpaceEvents(spaceId, { limit: 50 });
    },
    enabled: !!spaceId,
    staleTime: 15_000,
  });
}

export function useSharedMounts(conversationId: string | null, enabled = true) {
  return useQuery({
    queryKey: sharedSpaceKeys.mounts(conversationId ?? ""),
    queryFn: () => {
      if (!conversationId) return Promise.resolve([]);
      return listSharedMounts(conversationId);
    },
    enabled: !!conversationId && enabled,
    staleTime: 15_000,
  });
}

function invalidateSharedSpaceSurfaces(spaceId?: string): void {
  void queryClient.invalidateQueries({ queryKey: sharedSpaceKeys.list });
  void queryClient.invalidateQueries({
    queryKey: sharedSpaceKeys.pendingInvites,
  });
  void queryClient.invalidateQueries({ queryKey: workspaceKeys.list });
  if (spaceId) {
    void queryClient.invalidateQueries({
      queryKey: sharedSpaceKeys.detail(spaceId),
    });
    void queryClient.invalidateQueries({
      queryKey: sharedSpaceKeys.members(spaceId),
    });
    void queryClient.invalidateQueries({
      queryKey: sharedSpaceKeys.events(spaceId),
    });
  }
}

/** Invalidate every shared-space query (firehose catch-up). */
export function invalidateAllSharedSpaces(): void {
  void queryClient.invalidateQueries({ queryKey: sharedSpaceKeys.all });
  void queryClient.invalidateQueries({ queryKey: workspaceKeys.list });
}

export function useCreateSharedSpace() {
  return useMutation({
    mutationFn: (name: string) => createSharedSpace(name),
    onSuccess: () => invalidateSharedSpaceSurfaces(),
  });
}

export function useRenameSharedSpace() {
  return useMutation({
    mutationFn: ({ spaceId, name }: { spaceId: string; name: string }) =>
      renameSharedSpace(spaceId, name),
    onSuccess: (_data, vars) => invalidateSharedSpaceSurfaces(vars.spaceId),
  });
}

export function useDeleteSharedSpace() {
  return useMutation({
    mutationFn: (spaceId: string) => deleteSharedSpace(spaceId),
    onSuccess: (_data, spaceId) => invalidateSharedSpaceSurfaces(spaceId),
  });
}

export function useAcceptSharedInvite() {
  return useMutation({
    mutationFn: (spaceId: string) => acceptSharedSpaceInvite(spaceId),
    onSuccess: (_data, spaceId) => invalidateSharedSpaceSurfaces(spaceId),
  });
}

export function useRejectSharedInvite() {
  return useMutation({
    mutationFn: (spaceId: string) => rejectSharedSpaceInvite(spaceId),
    onSuccess: (_data, spaceId) => invalidateSharedSpaceSurfaces(spaceId),
  });
}

export function useInviteSharedMember() {
  return useMutation({
    mutationFn: ({
      spaceId,
      userId,
      role,
    }: {
      spaceId: string;
      userId: string;
      role: InviteRole;
    }) => inviteSharedSpaceMember(spaceId, userId, role),
    onSuccess: (_data, vars) => invalidateSharedSpaceSurfaces(vars.spaceId),
  });
}

export function useChangeSharedMemberRole() {
  return useMutation({
    mutationFn: ({
      spaceId,
      memberUserId,
      role,
    }: {
      spaceId: string;
      memberUserId: string;
      role: InviteRole;
    }) => changeSharedSpaceMemberRole(spaceId, memberUserId, role),
    onSuccess: (_data, vars) => invalidateSharedSpaceSurfaces(vars.spaceId),
  });
}

export function useRemoveOrLeaveSharedMember() {
  return useMutation({
    mutationFn: ({
      spaceId,
      memberUserId,
    }: {
      spaceId: string;
      memberUserId: string;
    }) => removeOrLeaveSharedSpaceMember(spaceId, memberUserId),
    onSuccess: (_data, vars) => invalidateSharedSpaceSurfaces(vars.spaceId),
  });
}

export function useMountSharedSpace(conversationId: string) {
  return useMutation({
    mutationFn: ({
      spaceId,
      aliasHint,
    }: {
      spaceId: string;
      aliasHint?: string | null;
    }) => mountSharedSpace(conversationId, spaceId, aliasHint),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: sharedSpaceKeys.mounts(conversationId),
      });
    },
  });
}

export function useUnmountSharedSpace(conversationId: string) {
  return useMutation({
    mutationFn: (opts: { spaceId?: string; alias?: string }) =>
      unmountSharedSpace(conversationId, opts),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: sharedSpaceKeys.mounts(conversationId),
      });
    },
  });
}

/** Optimistic helper: patch a space name in the list cache after rename. */
export function patchSharedSpaceInCache(
  spaceId: string,
  patch: Partial<SharedSpaceSummary>,
): void {
  const cur = queryClient.getQueryData<SharedSpaceSummary[]>(
    sharedSpaceKeys.list,
  );
  if (!cur) return;
  queryClient.setQueryData<SharedSpaceSummary[]>(
    sharedSpaceKeys.list,
    cur.map((s) => (s.id === spaceId ? { ...s, ...patch } : s)),
  );
}
