import { EmptyHint, InlineError } from "@/components/files/parts";
import { Button } from "@/components/ui";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { useSharedSpaceEvents } from "@/hooks/useSharedSpaces";
import {
  type SharedSpaceEventSummary,
  sharedSpaceEventActionLabel,
} from "@/services/sharedSpaces";
import { History, Loader2 } from "lucide-react";

function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function actorLabel(ev: SharedSpaceEventSummary): string {
  const who = ev.actor_user_id
    ? `用户 ${ev.actor_user_id.slice(0, 8)}…`
    : "未知";
  return ev.actor_via === "agent" ? `${who} 的 Agent` : who;
}

/**
 * Durable change log for a shared space — who (or whose Agent) mutated what.
 */
export function SharedSpaceEventsDialog({
  open,
  onClose,
  spaceId,
  spaceName,
}: {
  open: boolean;
  onClose: () => void;
  spaceId: string;
  spaceName: string;
}) {
  const { data, isLoading, isError, refetch } = useSharedSpaceEvents(
    open ? spaceId : null,
  );
  const events = data?.events ?? [];

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent
        position="top"
        className="max-w-lg"
        aria-describedby={undefined}
      >
        <DialogTitle>变更记录 · {spaceName}</DialogTitle>
        <div className="max-h-[60vh] min-h-[12rem] overflow-y-auto px-1 pb-2">
          {isLoading ? (
            <div className="flex items-center justify-center py-10">
              <Loader2
                size={18}
                className="animate-spin text-muted-foreground/50"
              />
            </div>
          ) : isError ? (
            <InlineError onRetry={() => void refetch()} />
          ) : events.length === 0 ? (
            <EmptyHint
              inline
              icon={<History size={22} className="text-muted-foreground/40" />}
              title="暂无变更"
              hint="成员或 Agent 改动文件后，会在这里留下可归因记录。"
            />
          ) : (
            <ul className="divide-y divide-border">
              {events.map((ev) => (
                <li key={ev.id} className="px-2 py-2.5">
                  <p className="text-sm text-foreground">
                    <span className="font-medium">{actorLabel(ev)}</span>
                    <span className="text-muted-foreground">
                      {" "}
                      {sharedSpaceEventActionLabel(ev.action)}
                    </span>
                  </p>
                  {ev.path ? (
                    <p className="mt-0.5 truncate text-xs text-muted-foreground">
                      {ev.path}
                    </p>
                  ) : null}
                  <p className="mt-0.5 text-xs text-muted-foreground/80">
                    {formatWhen(ev.created_at)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="flex justify-end px-1 pb-1">
          <Button variant="ghost" onClick={onClose}>
            关闭
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
