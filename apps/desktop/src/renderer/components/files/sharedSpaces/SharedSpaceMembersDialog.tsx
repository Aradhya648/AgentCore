import { EmptyHint, InlineError } from "@/components/files/parts";
import { avatarInitial } from "@/components/messages/chatDisplay";
import { Badge, Button, SearchField } from "@/components/ui";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useChangeSharedMemberRole,
  useInviteSharedMember,
  useRemoveOrLeaveSharedMember,
  useSharedSpaceMembers,
} from "@/hooks/useSharedSpaces";
import { notifyError, notifySuccess } from "@/lib/toast";
import {
  type UserSearchResult,
  messagingErrorMessage,
  searchUsers,
} from "@/services/messaging";
import {
  type InviteRole,
  type SharedSpaceRole,
  sharedSpaceRoleLabel,
} from "@/services/sharedSpaces";
import { useAuthStore } from "@/stores/auth";
import { Loader2, UserPlus, Users } from "lucide-react";
import { useEffect, useState } from "react";

function roleTone(role: SharedSpaceRole): "primary" | "success" | "muted" {
  if (role === "owner") return "primary";
  if (role === "editor") return "success";
  return "muted";
}

/**
 * Owner: invite (IM exact search) / change role / remove.
 * Member: view roster + leave self.
 */
export function SharedSpaceMembersDialog({
  open,
  onClose,
  spaceId,
  spaceName,
  myRole,
}: {
  open: boolean;
  onClose: () => void;
  spaceId: string;
  spaceName: string;
  myRole: SharedSpaceRole;
}) {
  const meId = useAuthStore((s) => s.user?.id ?? null);
  const isOwner = myRole === "owner";
  const { data, isLoading, isError, refetch } = useSharedSpaceMembers(
    open ? spaceId : null,
  );
  const members = data ?? [];
  const invite = useInviteSharedMember();
  const changeRole = useChangeSharedMemberRole();
  const removeOrLeave = useRemoveOrLeaveSharedMember();

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<UserSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [inviteRole, setInviteRole] = useState<InviteRole>("editor");

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setResults([]);
    setSearchError(null);
    setInviteRole("editor");
  }, [open]);

  useEffect(() => {
    if (!open || !isOwner) return;
    const q = query.trim();
    if (!q) {
      setResults([]);
      setSearchError(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const users = await searchUsers(q);
          if (!cancelled) {
            const memberIds = new Set(members.map((m) => m.user_id));
            setResults(users.filter((u) => !memberIds.has(u.id)));
            setSearchError(null);
          }
        } catch (err) {
          if (!cancelled) {
            setResults([]);
            setSearchError(messagingErrorMessage(err, "搜索失败，请重试"));
          }
        } finally {
          if (!cancelled) setSearching(false);
        }
      })();
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, open, isOwner, members]);

  const handleInvite = (user: UserSearchResult) => {
    invite.mutate(
      { spaceId, userId: user.id, role: inviteRole },
      {
        onSuccess: () => {
          notifySuccess(`已邀请 ${user.display_name || user.username}`);
          setQuery("");
          setResults([]);
        },
        onError: (err) => notifyError(err, "邀请失败"),
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent
        position="top"
        className="max-w-md"
        aria-describedby={undefined}
      >
        <DialogHeader>
          <DialogTitle>成员 · {spaceName}</DialogTitle>
        </DialogHeader>

        {isOwner && (
          <div className="space-y-2 border-b border-border px-5 pb-3">
            <div className="flex items-center gap-2">
              <UserPlus size={14} className="shrink-0 text-muted-foreground" />
              <span className="text-xs font-medium text-muted-foreground">
                邀请成员
              </span>
              <div className="ml-auto flex gap-1">
                {(
                  [
                    ["editor", "可编辑"],
                    ["viewer", "只读"],
                  ] as const
                ).map(([value, label]) => (
                  <Button
                    key={value}
                    size="sm"
                    variant={inviteRole === value ? "primary" : "ghost"}
                    onClick={() => setInviteRole(value)}
                  >
                    {label}
                  </Button>
                ))}
              </div>
            </div>
            <SearchField
              variant="plain"
              value={query}
              onValueChange={setQuery}
              placeholder="精确查找用户名或 ID…"
              aria-label="按用户名或 ID 邀请成员"
              className="rounded-lg border border-border px-2"
            />
            {searchError && (
              <p className="text-xs text-destructive">{searchError}</p>
            )}
            {searching && (
              <p className="text-xs text-muted-foreground">查找中…</p>
            )}
            {!searching &&
              query.trim() &&
              results.length === 0 &&
              !searchError && (
                <p className="text-xs text-muted-foreground">
                  未找到用户（需精确用户名或 ID）
                </p>
              )}
            {results.length > 0 && (
              <ul className="max-h-40 overflow-y-auto rounded-lg border border-border">
                {results.map((u) => (
                  <li key={u.id}>
                    <Button
                      variant="ghost"
                      disabled={invite.isPending}
                      onClick={() => handleInvite(u)}
                      className="h-auto w-full justify-start gap-2 rounded-none px-3 py-2 font-normal"
                    >
                      <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary">
                        {avatarInitial(u.display_name || u.username)}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-left text-sm">
                        {u.display_name || u.username}
                        <span className="ml-1 text-xs text-muted-foreground">
                          @{u.username}
                        </span>
                      </span>
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        <div className="max-h-[50vh] min-h-[8rem] overflow-y-auto px-5 pb-5">
          {isLoading ? (
            <div className="flex items-center justify-center py-10">
              <Loader2
                size={18}
                className="animate-spin text-muted-foreground/50"
              />
            </div>
          ) : isError ? (
            <InlineError onRetry={() => void refetch()} />
          ) : members.length === 0 ? (
            <EmptyHint
              inline
              icon={<Users size={22} className="text-muted-foreground/40" />}
              title="暂无成员"
              hint="邀请同伴加入后，他们会出现在这里。"
            />
          ) : (
            <ul className="divide-y divide-border">
              {members.map((m) => {
                const isSelf = m.user_id === meId;
                const label =
                  m.display_name || m.username || m.user_id.slice(0, 8);
                const busy =
                  (changeRole.isPending &&
                    changeRole.variables?.memberUserId === m.user_id) ||
                  (removeOrLeave.isPending &&
                    removeOrLeave.variables?.memberUserId === m.user_id);
                return (
                  <li
                    key={m.user_id}
                    className="flex items-center gap-2 py-2.5"
                  >
                    <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-medium text-primary">
                      {avatarInitial(label)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">
                        {label}
                        {isSelf ? (
                          <span className="ml-1 text-xs text-muted-foreground">
                            （你）
                          </span>
                        ) : null}
                      </p>
                      <div className="mt-0.5 flex flex-wrap items-center gap-1">
                        <Badge tone={roleTone(m.role)} pill>
                          {sharedSpaceRoleLabel(m.role)}
                        </Badge>
                        {m.state === "pending" && (
                          <Badge tone="muted" pill>
                            待接受
                          </Badge>
                        )}
                      </div>
                    </div>
                    {isOwner &&
                      m.role !== "owner" &&
                      m.state === "accepted" && (
                        <select
                          className="h-7 max-w-[5.5rem] rounded-lg border border-border bg-background px-1.5 text-xs"
                          value={m.role}
                          disabled={busy}
                          aria-label={`更改 ${label} 的角色`}
                          onChange={(e) => {
                            const role = e.target.value as InviteRole;
                            changeRole.mutate(
                              {
                                spaceId,
                                memberUserId: m.user_id,
                                role,
                              },
                              {
                                onSuccess: () =>
                                  notifySuccess(
                                    `已将 ${label} 设为${sharedSpaceRoleLabel(role)}`,
                                  ),
                                onError: (err) =>
                                  notifyError(err, "更改角色失败"),
                              },
                            );
                          }}
                        >
                          <option value="editor">可编辑</option>
                          <option value="viewer">只读</option>
                        </select>
                      )}
                    {isOwner && m.role !== "owner" && (
                      <Button
                        size="sm"
                        variant="danger"
                        disabled={busy}
                        onClick={() => {
                          if (
                            !window.confirm(
                              `确定移除成员「${label}」？其挂载将立即失效。`,
                            )
                          ) {
                            return;
                          }
                          removeOrLeave.mutate(
                            { spaceId, memberUserId: m.user_id },
                            {
                              onSuccess: () => notifySuccess(`已移除 ${label}`),
                              onError: (err) =>
                                notifyError(err, "移除成员失败"),
                            },
                          );
                        }}
                      >
                        移除
                      </Button>
                    )}
                    {!isOwner && isSelf && (
                      <Button
                        size="sm"
                        variant="danger"
                        disabled={busy}
                        onClick={() => {
                          if (
                            !window.confirm(
                              `确定退出共享空间「${spaceName}」？`,
                            )
                          ) {
                            return;
                          }
                          removeOrLeave.mutate(
                            { spaceId, memberUserId: m.user_id },
                            {
                              onSuccess: () => {
                                notifySuccess("已退出共享空间");
                                onClose();
                              },
                              onError: (err) => notifyError(err, "退出失败"),
                            },
                          );
                        }}
                      >
                        退出
                      </Button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
