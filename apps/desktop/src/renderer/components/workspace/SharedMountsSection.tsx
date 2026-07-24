import { Button } from "@/components/ui";
import {
  useMountSharedSpace,
  useSharedMounts,
  useSharedSpaces,
  useUnmountSharedSpace,
} from "@/hooks/useSharedSpaces";
import { notifyError, notifySuccess } from "@/lib/toast";
import {
  sharedMountModeLabel,
  sharedSpaceRoleLabel,
} from "@/services/sharedSpaces";
import { FolderPlus, Link2Off, Loader2, Users } from "lucide-react";
import { useMemo, useState } from "react";

/**
 * Cloud-conversation only: mount / unmount accepted shared spaces as
 * `shared/<alias>/` second roots. Hidden for local-bound chats (D2).
 */
export function SharedMountsSection({
  conversationId,
}: {
  conversationId: string;
}) {
  const spacesQuery = useSharedSpaces();
  const mountsQuery = useSharedMounts(conversationId, true);
  const mount = useMountSharedSpace(conversationId);
  const unmount = useUnmountSharedSpace(conversationId);
  const [pickerOpen, setPickerOpen] = useState(false);

  const mounts = mountsQuery.data ?? [];
  const mountedIds = useMemo(
    () => new Set(mounts.map((m) => m.space_id)),
    [mounts],
  );
  const available = useMemo(
    () => (spacesQuery.data ?? []).filter((s) => !mountedIds.has(s.id)),
    [spacesQuery.data, mountedIds],
  );

  if (mountsQuery.isLoading && mounts.length === 0) {
    return (
      <div className="flex items-center gap-1.5 border-t border-border px-3 py-2 text-xs text-muted-foreground">
        <Loader2 size={12} className="animate-spin" />
        加载共享挂载…
      </div>
    );
  }

  return (
    <div className="shrink-0 border-t border-border">
      <div className="flex items-center gap-1.5 px-3 py-1.5">
        <Users size={12} className="text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate text-xs font-medium text-muted-foreground">
          共享空间挂载
        </span>
        <Button
          size="sm"
          variant="ghost"
          disabled={available.length === 0 || mount.isPending}
          onClick={() => setPickerOpen((v) => !v)}
          icon={<FolderPlus size={12} />}
        >
          挂载
        </Button>
      </div>

      {pickerOpen && (
        <div className="border-t border-border bg-muted/30 px-2 py-1.5">
          {available.length === 0 ? (
            <p className="px-1 py-1 text-xs text-muted-foreground">
              没有可挂载的共享空间（需先加入或创建）
            </p>
          ) : (
            <ul className="max-h-36 space-y-0.5 overflow-y-auto">
              {available.map((s) => (
                <li key={s.id}>
                  <Button
                    variant="ghost"
                    disabled={mount.isPending}
                    onClick={() =>
                      mount.mutate(
                        { spaceId: s.id },
                        {
                          onSuccess: (m) => {
                            notifySuccess(
                              `已挂载「${m.label}」（${sharedMountModeLabel(m.mode)}）`,
                            );
                            setPickerOpen(false);
                          },
                          onError: (err) => notifyError(err, "挂载失败"),
                        },
                      )
                    }
                    className="h-auto w-full justify-start gap-2 rounded-lg px-2 py-1.5 font-normal"
                  >
                    <span className="min-w-0 flex-1 truncate text-left text-xs">
                      {s.name}
                      <span className="ml-1 text-muted-foreground">
                        · {sharedSpaceRoleLabel(s.my_role)}
                      </span>
                    </span>
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {mountsQuery.isError ? (
        <p className="px-3 pb-2 text-xs text-destructive">
          无法加载挂载列表
          <Button
            size="sm"
            variant="ghost"
            className="ml-1"
            onClick={() => void mountsQuery.refetch()}
          >
            重试
          </Button>
        </p>
      ) : mounts.length === 0 ? (
        <p className="px-3 pb-2 text-xs text-muted-foreground/80">
          尚未挂载。挂载后 Agent 可按你的角色读写该空间。
        </p>
      ) : (
        <ul className="space-y-0.5 px-2 pb-2">
          {mounts.map((m) => (
            <li
              key={`${m.space_id}:${m.alias}`}
              className="flex items-center gap-1.5 rounded-lg px-1.5 py-1"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium">{m.label}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {m.namespace} · {sharedMountModeLabel(m.mode)}
                </p>
              </div>
              <Button
                size="sm"
                variant="ghost"
                disabled={unmount.isPending}
                title="卸载"
                onClick={() =>
                  unmount.mutate(
                    { spaceId: m.space_id, alias: m.alias },
                    {
                      onSuccess: () => notifySuccess(`已卸载「${m.label}」`),
                      onError: (err) => notifyError(err, "卸载失败"),
                    },
                  )
                }
                icon={<Link2Off size={12} />}
              >
                卸载
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
